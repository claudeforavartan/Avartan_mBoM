"""End-to-end checks of the web app using FastAPI's test client.

The Excel import test needs the real workbook. Point MBOM_TEST_WORKBOOK at it,
otherwise that test is skipped:
    MBOM_TEST_WORKBOOK=path/to/MasterBOM_A02_AATPL_Prototype.xlsx python -m unittest
"""

import os
import re
import tempfile
import unittest

os.environ["MBOM_DATA_DIR"] = tempfile.mkdtemp(prefix="mbom-test-")

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_password  # noqa: E402

WORKBOOK = os.environ.get("MBOM_TEST_WORKBOOK", "")


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=True)


class WebAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()  # runs startup: creates tables and the admin user
        with db.SessionLocal() as s:
            for name, role in (("eng", "engineering"), ("sales", "sales"), ("buyer", "purchase")):
                s.add(db.User(username=name, role=role, password_hash=hash_password("password123")))
            s.add(db.PlasticMaterial(grade="Zytel 70G30 HSLR BK099", manufacturer="DuPont", cost_per_kg=300))
            s.add(db.RunnerSystem(name="Hot Runner system", wastage=0.1))
            s.add(db.MouldingMachine(tonnage="50T", machine_hour_rate=250))
            s.add(db.SheetMetalMaterial(grade="SGCD 180 / 275 GSM 1.0", thickness_mm=1.0, cost_per_kg=92.16))
            s.add(db.Coating(name="Zn- Ni", cost_per_sq_in=0.25))
            s.commit()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def setUp(self):
        self.client.cookies.clear()

    def test_requires_login(self):
        r = self.client.get("/", follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers["location"], "/login")

    def test_first_admin_login_forces_password_change(self):
        r = login(self.client, "admin", "admin")
        self.assertIn("Change password", r.text)

    def test_sales_cannot_edit(self):
        login(self.client, "sales", "password123")
        r = self.client.post("/products/new", data={"name": "X"})
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/rates/plastic", data={"grade": "Y", "cost_per_kg": "1"})
        self.assertEqual(r.status_code, 403)

    def test_purchase_can_edit_rates_but_not_bom(self):
        login(self.client, "buyer", "password123")
        r = self.client.post("/rates/coatings", data={"name": "Zn- 3 blue", "cost_per_sq_in": "0.12"}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Zn- 3 blue", r.text)
        self.assertEqual(self.client.post("/products/new", data={"name": "X"}).status_code, 403)

    def test_engineer_costs_plastic_and_sheet_metal_parts(self):
        login(self.client, "eng", "password123")
        r = self.client.post("/products/new", data={"name": "Calc test"}, follow_redirects=True)
        pid = int(re.search(r"/products/(\d+)/lines/new", r.text).group(1))
        with db.SessionLocal() as s:
            p = s.get(db.Product, pid)
            vid = p.variants[0].id
            ids = dict(mat=s.query(db.PlasticMaterial).first().id, run=s.query(db.RunnerSystem).first().id,
                       mac=s.query(db.MouldingMachine).first().id, sm=s.query(db.SheetMetalMaterial).first().id,
                       coat=s.query(db.Coating).filter_by(name="Zn- Ni").first().id)
        # Gear wheel from 'Plastic parts- Costing' -> 8.514
        r = self.client.post(f"/products/{pid}/lines/new", follow_redirects=True, data={
            "description": "Gear wheel", "weight_g": "24", f"qty_{vid}": "1", "costing_method": "plastic",
            "pl_material_id": ids["mat"], "pl_runner_id": ids["run"], "pl_machine_id": ids["mac"],
            "pl_cavities": "12", "pl_cycle_time_s": "56", "pl_ohp_pct": "12"})
        self.assertIn("₹8.514", r.text)
        # Centre plate from 'Sheet metal- Costing' -> 45.210 (the workbook shows #VALUE!)
        stages = {}
        for i, (name, t) in enumerate([("Blanking", 160), ("Forming-1", 160), ("Forming-2", 160),
                                       ("Piercing", 110), ("Push-through", 63)]):
            stages.update({f"st{i}_name": name, f"st{i}_tonnage": str(t), f"st{i}_cavities": "1"})
        r = self.client.post(f"/products/{pid}/lines/new", follow_redirects=True, data={
            "description": "Centre plate", "weight_g": "220", "economy_factor": "0.6", f"qty_{vid}": "2",
            "costing_method": "sheet_metal", "sm_material_id": ids["sm"], "sm_coating_id": ids["coat"],
            "sm_surface_area": "24", "sm_ohp_pct": "10", **stages})
        self.assertIn("₹45.210", r.text)
        r = self.client.get(f"/products/{pid}")
        self.assertIn("₹98.94", r.text)  # 8.5144 + 2 x 45.2103 = 98.935

    @unittest.skipUnless(WORKBOOK and os.path.exists(WORKBOOK), "set MBOM_TEST_WORKBOOK to run")
    def test_import_reproduces_workbook_totals(self):
        login(self.client, "eng", "password123")
        with open(WORKBOOK, "rb") as f:
            r = self.client.post("/import", data={"bom": "on"}, follow_redirects=True,
                                 files={"file": ("MasterBOM.xlsx", f.read())})
        self.assertIn("BOM lines", r.text)
        pid = int(re.search(r'href="/products/(\d+)"', r.text).group(1))
        page = self.client.get(f"/products/{pid}").text
        self.assertIn("₹2,009.33", page)        # MasterBOM AT3
        self.assertIn("₹32.96", page)           # Costing - Assy C17
        self.assertIn("₹2,042.29", page)        # cost including assembly
        self.assertIn("₹2,76,89,000", page)     # BJ7 total investment


if __name__ == "__main__":
    unittest.main()

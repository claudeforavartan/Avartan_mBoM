"""Check that the costing engine reproduces MasterBOM_A02_AATPL_Prototype.xlsx.

The expected numbers are the values Excel calculated and saved in the workbook.
Run with:  python -m unittest
"""

import unittest

from mbom.costing import (
    AssemblyInput, BomLine, PlasticPartInput, SheetMetalPartInput, StampingStage,
    assembly_cost, investment_by_owner, plastic_part_cost, rollup, sheet_metal_part_cost,
)

V = "A02_AATPL"  # the only variant in use (MasterBOM Column1)


def line(desc, w, qty, rate=0, ef=0, proc=0, ht=0, coat=0, bop=0, owner="", tool=0):
    return BomLine(desc, w, {V: qty}, rate, ef, proc, ht, coat, bop, owner, tool)


# MasterBOM rows 39-60, as entered in the workbook
A02_LINES = [
    line("Front End Housing", 170, 1, 235, 0.9, 38.5, coat=14, owner="Aditya", tool=370000),
    line("Back End Housing", 170, 1, 235, 0.9, 33.2, coat=14, owner="Aditya", tool=350000),
    line("Stator", 1820, 1, 95, 0.512, 87, ht=-58.8, coat=87, owner="Aditya", tool=954000),
    line("Rotor", 548, 1, 95, 0.512, 23.5, ht=-17.77),
    line("Fan", 26, 1, 350, 0.95, 5, owner="Aditya", tool=800000),
    line("Shaft", 66, 1, 90, 0.85, 46),
    line("Anti-Slip Sleeves", 1.6, 1, 400, 0.95, 12),
    line("Magnetic Disk Encoder", 24, 1, 98, 0.55, 1.8, owner="Aditya", tool=115000),
    line("Upper Insulation Half", 24, 1, 350, 0.98, 8.4, owner="Aditya", tool=800000),
    line("Lower Insulation Half", 21.242, 1, 350, 0.98, 9, owner="Aditya", tool=750000),
    line("Copper Wire", 350, 1, 1000, 0.98),
    line("Bearing Holder", 16, 2, 130, 0.8, 24),
    line("Bearing", 11, 2, bop=55),
    line("Wave Springs", 1, 1, bop=0.85),
    line("Hex Bolts", 8, 4, bop=3.7),
    line("Lock Nuts", 2, 4, bop=1.7),
    line("Screw Phillips", 1, 2, bop=0.9),
    line("Spring Washer", 1, 2, bop=0.6),
    line("Hex Socket Self Tapping Screw", 1, 2, bop=0.9),
    line("Sensor Board", 1, 1, bop=20),
    line("Controller Board", 1, 1, bop=400),
    line("Lead Board", 1, 1, bop=20),
]


class MasterBomRollup(unittest.TestCase):
    def test_single_line_matches_row_39(self):
        fe = A02_LINES[0]
        self.assertAlmostEqual(fe.norms_g, 188.888888, places=5)   # AM39
        self.assertAlmostEqual(fe.material, 44.388888, places=5)   # AN39
        self.assertAlmostEqual(fe.ohp, 18.865, places=6)           # AR39
        self.assertAlmostEqual(fe.total, 115.753888, places=5)     # AT39

    def test_variant_totals_match_row_3(self):
        r = rollup(A02_LINES, V)
        self.assertAlmostEqual(r.weight_g, 3324.842, places=6)      # E3
        self.assertAlmostEqual(r.material, 928.1707226, places=6)   # AN3
        self.assertAlmostEqual(r.process, 312.4, places=6)          # AO3
        self.assertAlmostEqual(r.heat_treatment, -76.57, places=6)  # AP3
        self.assertAlmostEqual(r.coating, 115, places=6)            # AQ3
        self.assertAlmostEqual(r.ohp, 153.076, places=6)            # AR3
        self.assertAlmostEqual(r.bop, 577.25, places=6)             # AS3
        self.assertAlmostEqual(r.total, 2009.3267226, places=6)     # AT3

    def test_investment_matches_bg3(self):
        inv = investment_by_owner(A02_LINES, "Aditya")
        self.assertEqual(inv["tooling"], 4139000)                   # BG3
        self.assertEqual(investment_by_owner(A02_LINES, "Customer")["total"], 0)  # BJ4


class PlasticSheet(unittest.TestCase):
    def test_gear_wheel_matches_sheet(self):
        c = plastic_part_cost(PlasticPartInput(
            part_weight_g=24, runner_wastage=0.10, rm_cost_per_kg=300,
            cavities=12, machine_hour_rate=250, cycle_time_s=56, ohp_rate=0.12))
        self.assertAlmostEqual(c.material_per_part_g, 26.4)         # F20
        self.assertAlmostEqual(c.material_cost, 7.92)               # F22
        self.assertEqual(c.output_per_hour, 655)                    # F31
        self.assertAlmostEqual(c.process_cost, 0.3816793893)        # F32
        self.assertAlmostEqual(c.ohp, 0.0458015267)                 # F35
        self.assertAlmostEqual(c.packing_transport, 0.1669496183)   # F36
        self.assertAlmostEqual(c.total, 8.5144305344)               # F38


class AssemblySheet(unittest.TestCase):
    def test_matches_sheet(self):
        c = assembly_cost(AssemblyInput(
            manpower=16, cycle_time_s=35.5, efficiency=0.8, man_hour_cost=150,
            line_cost_specific=4_000_000, amortization_volume=1_200_000))
        self.assertEqual(c.output_per_hour, 81)                     # C6
        self.assertAlmostEqual(c.labour_per_part, 29.6296296296)    # C7
        self.assertAlmostEqual(c.amortization_per_part, 3.3333333)  # C15
        self.assertAlmostEqual(c.total, 32.9629629630)              # C17


class SheetMetalSheet(unittest.TestCase):
    def test_centre_plate(self):
        stages = [StampingStage("Blanking", 160), StampingStage("Forming-1", 160),
                  StampingStage("Forming-2", 160), StampingStage("Piercing", 110),
                  StampingStage("Push-through", 63)]
        c = sheet_metal_part_cost(SheetMetalPartInput(
            part_weight_g=220, economy_factor=0.6, rm_cost_per_kg=92.16, stages=stages,
            surface_area_sq_in=24, coating_rate_per_sq_in=0.25, ohp_rate=0.10))
        # These match the cells Excel calculated correctly
        self.assertAlmostEqual(c.input_weight_g, 366.6666667)       # F16
        self.assertAlmostEqual(c.material_cost, 33.792)             # F17
        self.assertAlmostEqual(c.stamping_cost, 3.5915)             # F29
        self.assertAlmostEqual(c.coating_cost, 6.0)                 # F35
        # Excel shows #VALUE! from F36 onward; these are the intended values
        self.assertAlmostEqual(c.process_cost, 9.5915)
        self.assertAlmostEqual(c.ohp, 0.95915)
        self.assertAlmostEqual(c.packing_transport, 0.867670)
        self.assertAlmostEqual(c.total, 45.21032)


if __name__ == "__main__":
    unittest.main()

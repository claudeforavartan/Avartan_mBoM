"""Web routes for the mBoM costing app."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import costs, db, importer
from .formatting import inr, num, pct, val
from .security import ROLES, can, hash_password, verify_password

BASE = Path(__file__).resolve().parent
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _secret_key() -> str:
    path = db.DATA_DIR / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip()


app = FastAPI(title="Aditya mBoM")
app.add_middleware(SessionMiddleware, secret_key=_secret_key(), same_site="lax", max_age=60 * 60 * 12)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.filters.update(inr=inr, num=num, pct=pct, v=val)
templates.env.globals.update(can=can, ROLES=ROLES)


# ------------------------------------------------------------------ startup
@app.on_event("startup")
def startup() -> None:
    db.init_db()
    with db.SessionLocal() as s:
        if s.query(db.User).count() == 0:
            s.add(db.User(username="admin", full_name="Administrator", role="admin",
                          password_hash=hash_password("admin"), must_change_password=True))
            s.commit()


# ------------------------------------------------------------------ helpers
class LoginRequired(Exception):
    pass


class Forbidden(Exception):
    pass


class NotFound(Exception):
    pass


@app.exception_handler(LoginRequired)
def _login_required(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(Forbidden)
def _forbidden(request: Request, exc: Forbidden):
    return templates.TemplateResponse(request, "message.html", {
        "user": request.state.user if hasattr(request.state, "user") else None,
        "title": "Not allowed", "message": "Your role does not allow this action. Ask an admin if you need access."},
        status_code=403)


@app.exception_handler(NotFound)
def _not_found(request: Request, exc: NotFound):
    return templates.TemplateResponse(request, "message.html", {
        "user": request.state.user if hasattr(request.state, "user") else None,
        "title": "Not found", "message": "That item doesn't exist. It may have been deleted."}, status_code=404)


def current_user(request: Request, session) -> db.User:
    uid = request.session.get("user_id")
    user = session.get(db.User, uid) if uid else None
    if user is None or not user.active:
        request.session.clear()
        raise LoginRequired()
    request.state.user = user
    return user


def require(user: db.User, permission: str) -> None:
    if not can(user.role, permission):
        raise Forbidden()


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session.setdefault("flash", []).append([kind, message])


def render(request: Request, template: str, user: db.User | None, **ctx):
    messages = request.session.pop("flash", [])
    return templates.TemplateResponse(request, template, {"user": user, "messages": messages, **ctx})


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def fnum(form, key: str, default: float = 0.0) -> float:
    v = str(form.get(key, "")).replace(",", "").strip()
    if v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def ftext(form, key: str) -> str:
    return str(form.get(key, "")).strip()


def get_or_404(session, model, oid: int):
    obj = session.get(model, oid)
    if obj is None:
        raise NotFound()
    return obj


# ------------------------------------------------------------------ login
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", None)


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    with db.SessionLocal() as s:
        user = s.query(db.User).filter_by(username=ftext(form, "username").lower()).first()
        if user is None or not user.active or not verify_password(str(form.get("password", "")), user.password_hash):
            flash(request, "Wrong username or password.", "error")
            return redirect("/login")
        request.session["user_id"] = user.id
        if user.must_change_password:
            return redirect("/account/password")
    return redirect("/")


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login")


@app.get("/account/password", response_class=HTMLResponse)
def password_page(request: Request):
    with db.SessionLocal() as s:
        user = current_user(request, s)
        return render(request, "password.html", user)


@app.post("/account/password")
async def change_password(request: Request):
    form = await request.form()
    with db.SessionLocal() as s:
        user = current_user(request, s)
        if not verify_password(str(form.get("current", "")), user.password_hash):
            flash(request, "Current password is wrong.", "error")
            return redirect("/account/password")
        new = str(form.get("new", ""))
        if len(new) < 8 or new != form.get("confirm"):
            flash(request, "New password must be at least 8 characters and both entries must match.", "error")
            return redirect("/account/password")
        user.password_hash = hash_password(new)
        user.must_change_password = False
        s.commit()
    flash(request, "Password changed.")
    return redirect("/")


# ------------------------------------------------------------------ products
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with db.SessionLocal() as s:
        user = current_user(request, s)
        if user.must_change_password:
            return redirect("/account/password")
        products = s.query(db.Product).order_by(db.Product.updated_at.desc()).all()
        rows = []
        for p in products:
            summary = costs.summarize(s, p)
            rows.append((p, summary))
        return render(request, "home.html", user, rows=rows)


@app.post("/products/new")
async def product_new(request: Request):
    form = await request.form()
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "edit_bom")
        name = ftext(form, "name") or "New product"
        p = db.Product(name=name, customer=ftext(form, "customer"))
        p.variants.append(db.Variant(position=1, name=name, monthly_volume=0))
        s.add(p)
        s.commit()
        return redirect(f"/products/{p.id}")


@app.get("/products/{pid}", response_class=HTMLResponse)
def product_page(request: Request, pid: int):
    with db.SessionLocal() as s:
        user = current_user(request, s)
        p = get_or_404(s, db.Product, pid)
        summary = costs.summarize(s, p)
        return render(request, "product.html", user, p=p, sm=summary)


@app.post("/products/{pid}/edit")
async def product_edit(request: Request, pid: int):
    form = await request.form()
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "edit_bom")
        p = get_or_404(s, db.Product, pid)
        p.name = ftext(form, "name") or p.name
        p.customer = ftext(form, "customer")
        p.notes = ftext(form, "notes")
        for f in ("usd_inr", "eur_inr", "edd_cost", "validation_cost", "asm_manpower", "asm_cycle_time_s",
                  "asm_efficiency", "asm_man_hour_cost", "asm_line_cost_specific", "asm_line_cost_shared",
                  "asm_line_utilization", "asm_amortization_volume"):
            setattr(p, f, fnum(form, f))
        for v in p.variants:
            if form.get(f"v{v.id}_name") is not None:
                v.name = ftext(form, f"v{v.id}_name") or v.name
                v.part_no = ftext(form, f"v{v.id}_part_no")
                v.monthly_volume = fnum(form, f"v{v.id}_volume")
        if ftext(form, "new_variant_name"):
            p.variants.append(db.Variant(position=len(p.variants) + 1, name=ftext(form, "new_variant_name"),
                                         part_no=ftext(form, "new_variant_part_no"),
                                         monthly_volume=fnum(form, "new_variant_volume")))
        s.commit()
    flash(request, "Product saved.")
    return redirect(f"/products/{pid}")


@app.post("/products/{pid}/variants/{vid}/delete")
def variant_delete(request: Request, pid: int, vid: int):
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "edit_bom")
        v = get_or_404(s, db.Variant, vid)
        s.query(db.LineQuantity).filter_by(variant_id=vid).delete()
        s.delete(v)
        s.commit()
    flash(request, "Variant deleted.")
    return redirect(f"/products/{pid}")


@app.post("/products/{pid}/delete")
def product_delete(request: Request, pid: int):
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "edit_bom")
        p = get_or_404(s, db.Product, pid)
        for line in p.lines:
            for a in line.attachments:
                (db.UPLOAD_DIR / a.stored_name).unlink(missing_ok=True)
        s.delete(p)
        s.commit()
    flash(request, "Product deleted.")
    return redirect("/")


# ------------------------------------------------------------------ BOM lines
def _line_form_ctx(s, p, line, result=None):
    return dict(
        p=p, line=line, result=result,
        plastics=s.query(db.PlasticMaterial).order_by(db.PlasticMaterial.grade).all(),
        sheet_metals=s.query(db.SheetMetalMaterial).order_by(db.SheetMetalMaterial.grade).all(),
        machines=s.query(db.MouldingMachine).order_by(db.MouldingMachine.machine_hour_rate).all(),
        runners=s.query(db.RunnerSystem).all(),
        coatings=s.query(db.Coating).all(),
    )


@app.get("/products/{pid}/lines/new", response_class=HTMLResponse)
def line_new_page(request: Request, pid: int):
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "edit_bom")
        p = get_or_404(s, db.Product, pid)
        return render(request, "line.html", user, **_line_form_ctx(s, p, None))


@app.get("/lines/{lid}", response_class=HTMLResponse)
def line_page(request: Request, lid: int):
    with db.SessionLocal() as s:
        user = current_user(request, s)
        line = get_or_404(s, db.BomLine, lid)
        result = costs.cost_line(s, line, costs.load_settings(s))
        return render(request, "line.html", user, **_line_form_ctx(s, line.product, line, result))


def _apply_line_form(line: db.BomLine, form, p: db.Product) -> None:
    for f in ("part_no", "description", "material_spec", "new_cop", "mat_type", "supplier", "tooling_description",
              "tool_owner", "comments"):
        setattr(line, f, ftext(form, f))
    for f in ("weight_g", "rm_rate_per_kg", "economy_factor", "process_cost", "heat_treatment", "coating_cost",
              "bop_cost", "cavities", "cycle_time_s", "tooling_cost", "fixture_gauge_cost", "machinery_cost"):
        if f in form:  # fields in a hidden costing panel aren't sent; keep their saved values
            setattr(line, f, fnum(form, f))
    method = ftext(form, "costing_method")
    line.costing_method = method if method in ("manual", "plastic", "sheet_metal") else "manual"
    inputs: dict = {}
    if line.costing_method == "plastic":
        inputs = {k: ftext(form, f"pl_{k}") for k in ("material_id", "runner_id", "machine_id")}
        inputs.update(cavities=fnum(form, "pl_cavities", 1), cycle_time_s=fnum(form, "pl_cycle_time_s"),
                      ohp_rate=fnum(form, "pl_ohp_pct", 12) / 100)
    elif line.costing_method == "sheet_metal":
        stages = []
        for i in range(8):
            if fnum(form, f"st{i}_tonnage") > 0:
                stages.append({"name": ftext(form, f"st{i}_name"), "tonnage": fnum(form, f"st{i}_tonnage"),
                               "cavities": fnum(form, f"st{i}_cavities", 1) or 1})
        inputs = {"material_id": ftext(form, "sm_material_id"), "coating_id": ftext(form, "sm_coating_id"),
                  "surface_area_sq_in": fnum(form, "sm_surface_area"), "ohp_rate": fnum(form, "sm_ohp_pct", 10) / 100,
                  "stages": stages}
    line.calc_inputs_json = json.dumps(inputs)
    existing = {q.variant_id: q for q in line.quantities}
    for v in p.variants:
        qty = fnum(form, f"qty_{v.id}")
        if v.id in existing:
            existing[v.id].qty = qty
        elif qty:
            line.quantities.append(db.LineQuantity(variant_id=v.id, qty=qty))


@app.post("/products/{pid}/lines/new")
async def line_create(request: Request, pid: int):
    form = await request.form()
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "edit_bom")
        p = get_or_404(s, db.Product, pid)
        line = db.BomLine(position=len(p.lines))
        p.lines.append(line)
        s.flush()
        _apply_line_form(line, form, p)
        s.commit()
        flash(request, "Part added.")
        return redirect(f"/lines/{line.id}")


@app.post("/lines/{lid}")
async def line_save(request: Request, lid: int):
    form = await request.form()
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "edit_bom")
        line = get_or_404(s, db.BomLine, lid)
        _apply_line_form(line, form, line.product)
        line.product.updated_at = db.datetime.now()
        s.commit()
    flash(request, "Part saved and costed.")
    return redirect(f"/lines/{lid}")


@app.post("/lines/{lid}/delete")
def line_delete(request: Request, lid: int):
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "edit_bom")
        line = get_or_404(s, db.BomLine, lid)
        pid = line.product_id
        for a in line.attachments:
            (db.UPLOAD_DIR / a.stored_name).unlink(missing_ok=True)
        s.delete(line)
        s.commit()
    flash(request, "Part deleted.")
    return redirect(f"/products/{pid}")


@app.post("/lines/{lid}/attachments")
async def attachment_upload(request: Request, lid: int, file: UploadFile):
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "edit_bom")
        line = get_or_404(s, db.BomLine, lid)
        data = await file.read()
        if not data:
            flash(request, "Choose a file to upload.", "error")
        elif len(data) > MAX_UPLOAD_BYTES:
            flash(request, "File is larger than 50 MB.", "error")
        else:
            name = Path(file.filename or "file").name
            stored = f"{secrets.token_hex(8)}{Path(name).suffix.lower()}"
            (db.UPLOAD_DIR / stored).write_bytes(data)
            line.attachments.append(db.Attachment(filename=name, stored_name=stored, size_bytes=len(data),
                                                  uploaded_by=user.username))
            s.commit()
            flash(request, f"Uploaded {name}.")
    return redirect(f"/lines/{lid}#files")


@app.get("/attachments/{aid}")
def attachment_download(request: Request, aid: int):
    with db.SessionLocal() as s:
        current_user(request, s)
        a = get_or_404(s, db.Attachment, aid)
        return FileResponse(db.UPLOAD_DIR / a.stored_name, filename=a.filename)


@app.post("/attachments/{aid}/delete")
def attachment_delete(request: Request, aid: int):
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "edit_bom")
        a = get_or_404(s, db.Attachment, aid)
        lid = a.line_id
        (db.UPLOAD_DIR / a.stored_name).unlink(missing_ok=True)
        s.delete(a)
        s.commit()
    return redirect(f"/lines/{lid}#files")


# ------------------------------------------------------------------ import
@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "import")
        return render(request, "import.html", user, report=None)


@app.post("/import", response_class=HTMLResponse)
async def import_upload(request: Request, file: UploadFile):
    form = await request.form()
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "import")
        data = await file.read()
        rates = form.get("rates") == "on"
        bom = form.get("bom") == "on"
        if rates and not can(user.role, "edit_rates"):
            rates = False
        try:
            report = importer.import_workbook(s, data, file.filename or "", rates, bom, ftext(form, "product_name"))
        except Exception as exc:  # a bad or non-Excel file
            s.rollback()
            flash(request, f"Could not read this file as an Excel workbook ({exc.__class__.__name__}).", "error")
            return redirect("/import")
        return render(request, "import.html", user, report=report)


# ------------------------------------------------------------------ rate databases
RATE_TABLES = {
    "plastic": dict(model=db.PlasticMaterial, title="Plastic raw materials", order="grade", fields=[
        ("sap_no", "SAP #", "text"), ("manufacturer", "Manufacturer", "text"), ("grade", "Grade", "text"),
        ("family", "Family", "text"), ("filler", "Filler", "text"), ("fill_pct", "Fill %", "text"),
        ("cost_per_kg", "₹ / kg", "number")]),
    "sheet-metal": dict(model=db.SheetMetalMaterial, title="Sheet-metal raw materials", order="grade", fields=[
        ("division", "Division", "text"), ("category", "Category", "text"), ("sub_category", "Sub-category", "text"),
        ("grade", "Grade", "text"), ("thickness_mm", "Thickness (mm)", "number"), ("cost_per_kg", "₹ / kg", "number")]),
    "machines": dict(model=db.MouldingMachine, title="Moulding machines (tonnage → machine hour rate)",
                     order="machine_hour_rate", fields=[
        ("tonnage", "Tonnage", "text"), ("machine_hour_rate", "MHR (₹ / hr)", "number")]),
    "runners": dict(model=db.RunnerSystem, title="Runner systems", order="name", fields=[
        ("name", "Runner system", "text"), ("wastage", "Wastage (fraction, 0.1 = 10%)", "number")]),
    "coatings": dict(model=db.Coating, title="Surface coatings", order="name", fields=[
        ("name", "Coating", "text"), ("cost_per_sq_in", "₹ / sq in", "number")]),
}


def _rate_cfg(table: str) -> dict:
    if table not in RATE_TABLES:
        raise NotFound()
    return RATE_TABLES[table]


@app.get("/rates", response_class=HTMLResponse)
def rates_index(request: Request):
    return redirect("/rates/plastic")


@app.get("/rates/{table}", response_class=HTMLResponse)
def rates_page(request: Request, table: str, q: str = ""):
    cfg = _rate_cfg(table)
    with db.SessionLocal() as s:
        user = current_user(request, s)
        model = cfg["model"]
        rows = s.query(model).order_by(getattr(model, cfg["order"])).all()
        if q:
            ql = q.lower()
            rows = [r for r in rows if any(ql in str(getattr(r, f[0]) or "").lower() for f in cfg["fields"])]
        dupes = set()
        if table == "plastic":
            seen: dict[str, int] = {}
            for r in s.query(model).all():
                seen[r.grade.lower()] = seen.get(r.grade.lower(), 0) + 1
            dupes = {g for g, n in seen.items() if n > 1}
        return render(request, "rates.html", user, table=table, cfg=cfg, rows=rows, q=q, tables=RATE_TABLES,
                      dupes=dupes)


def _apply_rate(obj, cfg, form, prefix=""):
    for name, _, kind in cfg["fields"]:
        key = prefix + name
        if kind == "number":
            raw = ftext(form, key)
            setattr(obj, name, None if raw == "" and name == "thickness_mm" else fnum(form, key))
        else:
            setattr(obj, name, ftext(form, key))


@app.post("/rates/{table}")
async def rates_add(request: Request, table: str):
    cfg = _rate_cfg(table)
    form = await request.form()
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "edit_rates")
        obj = cfg["model"]()
        _apply_rate(obj, cfg, form)
        key_field = "grade" if table in ("plastic", "sheet-metal") else cfg["fields"][0][0]
        if not getattr(obj, key_field):
            flash(request, "Fill in the name/grade.", "error")
        else:
            s.add(obj)
            s.commit()
            flash(request, "Added.")
    return redirect(f"/rates/{table}")


@app.post("/rates/{table}/{rid}")
async def rates_update(request: Request, table: str, rid: int):
    cfg = _rate_cfg(table)
    form = await request.form()
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "edit_rates")
        obj = get_or_404(s, cfg["model"], rid)
        if form.get("delete"):
            s.delete(obj)
            flash(request, "Deleted. Parts that used this rate will show a calculator error until you pick another.")
        else:
            _apply_rate(obj, cfg, form)
            flash(request, "Saved.")
        s.commit()
    q = ftext(form, "q")
    return redirect(f"/rates/{table}" + (f"?q={q}" if q else ""))


# ------------------------------------------------------------------ settings and users
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    with db.SessionLocal() as s:
        user = current_user(request, s)
        values = costs.load_settings(s)
        return render(request, "settings.html", user, values=values, labels=costs.SETTING_LABELS,
                      defaults=costs.eng.DEFAULT_SETTINGS)


@app.post("/settings")
async def settings_save(request: Request):
    form = await request.form()
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "edit_settings")
        for key in costs.SETTING_LABELS:
            if ftext(form, key) == "":
                continue
            row = s.get(db.Setting, key) or db.Setting(key=key)
            row.value = fnum(form, key)
            s.add(row)
        s.commit()
    flash(request, "Settings saved. All costs now use the new values.")
    return redirect("/settings")


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "manage_users")
        users = s.query(db.User).order_by(db.User.username).all()
        return render(request, "users.html", user, users=users)


@app.post("/users")
async def users_add(request: Request):
    form = await request.form()
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "manage_users")
        username = ftext(form, "username").lower()
        password = str(form.get("password", ""))
        role = ftext(form, "role")
        if not username or role not in ROLES or len(password) < 8:
            flash(request, "Username, a role and a password of at least 8 characters are required.", "error")
        elif s.query(db.User).filter_by(username=username).first():
            flash(request, f"User {username} already exists.", "error")
        else:
            s.add(db.User(username=username, full_name=ftext(form, "full_name"), role=role,
                          password_hash=hash_password(password), must_change_password=True))
            s.commit()
            flash(request, f"User {username} created. They will be asked to change the password at first login.")
    return redirect("/users")


@app.post("/users/{uid}")
async def users_update(request: Request, uid: int):
    form = await request.form()
    with db.SessionLocal() as s:
        user = current_user(request, s)
        require(user, "manage_users")
        u = get_or_404(s, db.User, uid)
        role = ftext(form, "role")
        if role in ROLES:
            if u.id == user.id and role != "admin":
                flash(request, "You can't remove your own admin role.", "error")
                return redirect("/users")
            u.role = role
        u.full_name = ftext(form, "full_name")
        if u.id != user.id:
            u.active = form.get("active") == "on"
        if ftext(form, "password"):
            if len(str(form.get("password"))) < 8:
                flash(request, "Password must be at least 8 characters.", "error")
                return redirect("/users")
            u.password_hash = hash_password(str(form.get("password")))
            u.must_change_password = True
        s.commit()
    flash(request, "User saved.")
    return redirect("/users")

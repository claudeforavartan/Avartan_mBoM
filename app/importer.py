"""Import a MasterBOM workbook (same layout as MasterBOM_A02_AATPL_Prototype.xlsx).

Columns are found by their header text, not by position, so small layout
changes in the workbook don't break the import. Values are read from what
Excel last calculated (the cached values), so the file should have been
saved in Excel after its last change.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from io import BytesIO

import openpyxl
from sqlalchemy.orm import Session

from . import db


@dataclass
class ImportReport:
    product: db.Product | None = None
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip().lower() if v is not None else ""


def _num(v) -> float:
    if isinstance(v, bool) or v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return 0.0


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _find(ws, label: str, exact: bool = True):
    """Return (row, col) of the first cell whose text matches label."""
    target = _norm(label)
    for row in ws.iter_rows():
        for c in row:
            t = _norm(c.value)
            if t and (t == target if exact else t.startswith(target)):
                return c.row, c.column
    return None


def _sheet(wb, name):
    for ws in wb.worksheets:
        if _norm(ws.title) == _norm(name):
            return ws
    return None


def _rows_below(ws, row, col, ncols=2):
    """Yield value tuples under a header cell until the first blank row."""
    r = row + 1
    while r <= ws.max_row:
        vals = [ws.cell(r, col + i).value for i in range(ncols)]
        if vals[0] is None or _text(vals[0]) == "":
            break
        yield vals
        r += 1


def load_workbook(data: bytes):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(BytesIO(data), data_only=True)


# --------------------------------------------------------------------- rates
def import_rates(session: Session, wb, report: ImportReport) -> None:
    ws = _sheet(wb, "Plastic RM DBase")
    if ws is None:
        report.warnings.append("Sheet 'Plastic RM DBase' not found, plastic rates not imported.")
    else:
        hdr = _find(ws, "Grade")
        n = 0
        if hdr:
            r0, gcol = hdr
            existing = {(m.manufacturer, m.grade): m for m in session.query(db.PlasticMaterial).all()}
            for r in range(r0 + 1, ws.max_row + 1):
                grade = _text(ws.cell(r, gcol).value)
                if not grade:
                    continue
                vals = dict(sap_no=_text(ws.cell(r, gcol - 2).value), manufacturer=_text(ws.cell(r, gcol - 1).value),
                            grade=grade, family=_text(ws.cell(r, gcol + 1).value), filler=_text(ws.cell(r, gcol + 2).value),
                            fill_pct=_text(ws.cell(r, gcol + 3).value), cost_per_kg=_num(ws.cell(r, gcol + 4).value))
                m = existing.get((vals["manufacturer"], grade))
                if m is None:
                    m = db.PlasticMaterial(**vals)
                    session.add(m)
                    existing[(vals["manufacturer"], grade)] = m
                else:
                    for k, v in vals.items():
                        setattr(m, k, v)
                n += 1
        report.counts["Plastic materials"] = n

        n = 0
        hdr = _find(ws, "Machine tonage") or _find(ws, "Machine tonnage")
        if hdr:
            existing = {m.tonnage: m for m in session.query(db.MouldingMachine).all()}
            for t, mhr in _rows_below(ws, *hdr):
                t = _text(t)
                m = existing.get(t) or db.MouldingMachine(tonnage=t)
                m.machine_hour_rate = _num(mhr)
                session.add(m)
                existing[t] = m
                n += 1
        report.counts["Moulding machines"] = n

        n = 0
        hdr = _find(ws, "Runner System")
        if hdr:
            existing = {m.name: m for m in session.query(db.RunnerSystem).all()}
            for name, w in _rows_below(ws, *hdr):
                name = _text(name)
                m = existing.get(name) or db.RunnerSystem(name=name)
                m.wastage = _num(w)
                session.add(m)
                existing[name] = m
                n += 1
        report.counts["Runner systems"] = n

    ws = _sheet(wb, "Sheet Metal RM DBase")
    if ws is None:
        report.warnings.append("Sheet 'Sheet Metal RM DBase' not found, sheet-metal rates not imported.")
    else:
        n = 0
        hdr = _find(ws, "Commodity Grade")
        if hdr:
            r0, gcol = hdr
            existing = {m.grade: m for m in session.query(db.SheetMetalMaterial).all()}
            for r in range(r0 + 1, ws.max_row + 1):
                grade = _text(ws.cell(r, gcol).value)
                if not grade:
                    continue
                thick = ws.cell(r, gcol + 1).value
                vals = dict(division=_text(ws.cell(r, gcol - 3).value), category=_text(ws.cell(r, gcol - 2).value),
                            sub_category=_text(ws.cell(r, gcol - 1).value), grade=grade,
                            thickness_mm=_num(thick) if thick not in (None, "") else None,
                            cost_per_kg=_num(ws.cell(r, gcol + 2).value))
                m = existing.get(grade)
                if m is None:
                    m = db.SheetMetalMaterial(**vals)
                    session.add(m)
                    existing[grade] = m
                else:
                    for k, v in vals.items():
                        setattr(m, k, v)
                n += 1
        report.counts["Sheet-metal materials"] = n

    ws = _sheet(wb, "Sheet metal- Costing")
    n = 0
    hdr = _find(ws, "Surface coating", exact=False) if ws is not None else None
    if hdr:
        existing = {m.name: m for m in session.query(db.Coating).all()}
        for name, rate in _rows_below(ws, *hdr):
            name = _text(name)
            m = existing.get(name) or db.Coating(name=name)
            m.cost_per_sq_in = _num(rate)
            session.add(m)
            existing[name] = m
            n += 1
    report.counts["Coatings"] = n


# --------------------------------------------------------------------- BOM
LINE_COLUMNS = {
    "part#, rev": "part_no", "description": "description", "material spec.": "material_spec",
    "weight": "weight_g", "new /cop": "new_cop", "mat. type": "mat_type", "rm - rate": "rm_rate_per_kg",
    "econ factor": "economy_factor", "process": "process_cost", "ht": "heat_treatment",
    "coating": "coating_cost", "bop": "bop_cost", "supplier": "supplier",
    "tooling description": "tooling_description", "#cavities": "cavities", "cycle time (s)": "cycle_time_s",
    "tool owner": "tool_owner", "tooling cost": "tooling_cost", "f&g cost": "fixture_gauge_cost",
    "machinery cost": "machinery_cost", "comments": "comments",
}
NUMERIC = {"weight_g", "rm_rate_per_kg", "economy_factor", "process_cost", "heat_treatment", "coating_cost",
           "bop_cost", "cavities", "cycle_time_s", "tooling_cost", "fixture_gauge_cost", "machinery_cost"}


def import_bom(session: Session, wb, report: ImportReport, product_name: str) -> None:
    ws = _sheet(wb, "MasterBOM")
    if ws is None:
        report.warnings.append("Sheet 'MasterBOM' not found, no BOM imported.")
        return
    hdr = _find(ws, "RM - RATE")
    if not hdr:
        report.warnings.append("Could not find the child part table (no 'RM - RATE' header) on MasterBOM.")
        return
    hrow = hdr[0]
    cols: dict[str, int] = {}
    qty_cols: dict[int, int] = {}  # variant number -> column
    for c in range(1, ws.max_column + 1):
        h = _norm(ws.cell(hrow, c).value)
        m = re.fullmatch(r"column(\d+)", h)
        if m:
            qty_cols[int(m.group(1))] = c
        elif h in LINE_COLUMNS and LINE_COLUMNS[h] not in cols:
            cols[LINE_COLUMNS[h]] = c

    # Variant summary block at the top: header row has 'MONTHLY VOLUME'
    vhdr = _find(ws, "MONTHLY VOLUME")
    product = db.Product(name=product_name)
    session.add(product)
    variants: dict[int, db.Variant] = {}
    qty_rows = range(hrow + 1, ws.max_row + 1)
    if vhdr:
        vrow, vcol = vhdr
        pcol = _find(ws, "PART#, REV")[1] if _find(ws, "PART#, REV") else 1
        dcol = pcol + 1
        for k, qc in sorted(qty_cols.items()):
            r = vrow + k
            name = _text(ws.cell(r, dcol).value)
            vol = _num(ws.cell(r, vcol).value)
            used = any(_num(ws.cell(rr, qc).value) for rr in qty_rows)
            if name or vol or used:
                v = db.Variant(position=k, part_no=_text(ws.cell(r, pcol).value),
                               name=name or f"Variant {k}", monthly_volume=vol)
                product.variants.append(v)
                variants[k] = v
        if variants and not product_name:
            product.name = next(iter(variants.values())).name

    # Product-level figures
    for label, attr in (("Exchange Rate (USD:INR)", "usd_inr"), ("Exchange Rate (EUR:INR)", "eur_inr"),
                        ("ED&D", "edd_cost"), ("VALIDATION", "validation_cost")):
        pos = _find(ws, label)
        if pos:
            setattr(product, attr, _num(ws.cell(pos[0], pos[1] + 1).value))

    session.flush()
    n = 0
    for r in qty_rows:
        vals = {attr: ws.cell(r, c).value for attr, c in cols.items()}
        if not _text(vals.get("description")) and not _text(vals.get("part_no")):
            continue
        line = db.BomLine(position=n, costing_method="manual")
        for attr, v in vals.items():
            setattr(line, attr, _num(v) if attr in NUMERIC else _text(v))
        for k, qc in qty_cols.items():
            q = _num(ws.cell(r, qc).value)
            if q and k in variants:
                line.quantities.append(db.LineQuantity(variant_id=variants[k].id, qty=q))
            elif q:
                report.warnings.append(f"Row {r}: quantity in Column{k} but that variant has no name or volume.")
        product.lines.append(line)
        n += 1
    report.counts["BOM lines"] = n
    report.counts["Variants"] = len(variants)

    ws = _sheet(wb, "Costing - Assy")
    if ws is not None:
        for label, attr in (("Manpower", "asm_manpower"), ("Cycle Time", "asm_cycle_time_s"),
                            ("Efficiency", "asm_efficiency"), ("Man-Hour Cost", "asm_man_hour_cost"),
                            ("Assembly Line Cost - Specific", "asm_line_cost_specific"),
                            ("Assembly Line Cost - Shared", "asm_line_cost_shared"),
                            ("Assembly Line Utilization", "asm_line_utilization"),
                            ("Amortization Volume (Realistic)", "asm_amortization_volume")):
            pos = _find(ws, label)
            if pos:
                setattr(product, attr, _num(ws.cell(pos[0], pos[1] + 2).value))
    report.product = product


def import_workbook(session: Session, data: bytes, filename: str, rates: bool, bom: bool,
                    product_name: str = "") -> ImportReport:
    report = ImportReport()
    wb = load_workbook(data)
    if rates:
        import_rates(session, wb, report)
    if bom:
        import_bom(session, wb, report, product_name.strip())
        if report.product is not None and not report.product.name:
            report.product.name = re.sub(r"\.xls[xm]?$", "", filename, flags=re.I)
    session.commit()
    return report

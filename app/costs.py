"""Turns database rows into costing-engine inputs and works out product totals."""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from sqlalchemy.orm import Session

from mbom import costing as eng

from . import db

# Settings shown on the Settings page: key -> (label, help)
SETTING_LABELS = {
    "masterbom_ohp_rate": ("MasterBOM OHP rate (fraction of process cost)", "Workbook uses 0.27 + 0.20 + 0.02 = 0.49"),
    "packing_transport_rate": ("Packing & transport rate", "Both calculators use 2%"),
    "moulding_efficiency": ("Injection moulding efficiency", "Plastic calculator uses 85%"),
    "stamping_profit_rejection": ("Stamping profit & rejection", "Sheet-metal calculator adds 10%"),
    "stamping_rate_below_200t": ("Stamping Rs/tonne/stroke, below 200 T", "Formula uses 0.005 (the note on the sheet says 0.0055)"),
    "stamping_rate_upto_300t": ("Stamping Rs/tonne/stroke, 200-300 T", ""),
    "stamping_rate_upto_400t": ("Stamping Rs/tonne/stroke, 300-400 T", ""),
    "capacity_seconds_per_month": ("Production seconds per month (capacity)", "Workbook: 20 days x 3 shifts x 25,900 s = 1,554,000"),
}


def load_settings(session: Session) -> eng.CostSettings:
    stored = {s.key: s.value for s in session.query(db.Setting).all()}
    values = {f.name: stored.get(f.name, getattr(eng.DEFAULT_SETTINGS, f.name)) for f in fields(eng.CostSettings)}
    return eng.CostSettings(**values)


@dataclass
class LineResult:
    line: db.BomLine
    engine_line: eng.BomLine
    monthly_volume: float = 0.0
    capacity: float | None = None
    detail: object | None = None      # PlasticPartCost / SheetMetalPartCost for calculator lines
    detail_inputs: dict = field(default_factory=dict)
    error: str = ""


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def cost_line(session: Session, line: db.BomLine, s: eng.CostSettings) -> LineResult:
    el = eng.BomLine(
        description=line.description,
        weight_g=line.weight_g or 0,
        qty_per_variant={q.variant_id: q.qty for q in line.quantities},
        rm_rate_per_kg=line.rm_rate_per_kg or 0,
        economy_factor=line.economy_factor or 0,
        process=line.process_cost or 0,
        heat_treatment=line.heat_treatment or 0,
        coating=line.coating_cost or 0,
        bop=line.bop_cost or 0,
        tool_owner=line.tool_owner or "",
        tooling_cost=line.tooling_cost or 0,
        fixture_gauge_cost=line.fixture_gauge_cost or 0,
        machinery_cost=line.machinery_cost or 0,
        ohp_rate=s.masterbom_ohp_rate,
    )
    result = LineResult(line, el)
    inp = line.calc_inputs
    try:
        if line.costing_method == "plastic":
            mat = session.get(db.PlasticMaterial, int(inp["material_id"])) if inp.get("material_id") else None
            runner = session.get(db.RunnerSystem, int(inp["runner_id"])) if inp.get("runner_id") else None
            machine = session.get(db.MouldingMachine, int(inp["machine_id"])) if inp.get("machine_id") else None
            missing = [n for n, v in (("material", mat), ("runner system", runner), ("machine tonnage", machine)) if v is None]
            if missing:
                raise ValueError("Choose " + ", ".join(missing))
            p = eng.PlasticPartInput(
                part_weight_g=line.weight_g, runner_wastage=runner.wastage, rm_cost_per_kg=mat.cost_per_kg,
                cavities=int(_num(inp.get("cavities"), 1)), machine_hour_rate=machine.machine_hour_rate,
                cycle_time_s=_num(inp.get("cycle_time_s")), ohp_rate=_num(inp.get("ohp_rate"), 0.12))
            c = eng.plastic_part_cost(p, s)
            el.rm_rate_per_kg = mat.cost_per_kg
            el.material_override, el.process = c.material_cost, c.process_cost
            el.ohp_override, el.packing_transport = c.ohp, c.packing_transport
            result.detail = c
            result.detail_inputs = {"material": mat, "runner": runner, "machine": machine, "input": p}
        elif line.costing_method == "sheet_metal":
            mat = session.get(db.SheetMetalMaterial, int(inp["material_id"])) if inp.get("material_id") else None
            if mat is None:
                raise ValueError("Choose a sheet-metal material")
            coat = session.get(db.Coating, int(inp["coating_id"])) if inp.get("coating_id") else None
            stages = [eng.StampingStage(st.get("name", ""), _num(st.get("tonnage")), int(_num(st.get("cavities"), 1)) or 1)
                      for st in inp.get("stages", []) if _num(st.get("tonnage")) > 0]
            p = eng.SheetMetalPartInput(
                part_weight_g=line.weight_g, economy_factor=line.economy_factor, rm_cost_per_kg=mat.cost_per_kg,
                stages=stages, surface_area_sq_in=_num(inp.get("surface_area_sq_in")),
                coating_rate_per_sq_in=coat.cost_per_sq_in if coat else 0, ohp_rate=_num(inp.get("ohp_rate"), 0.10))
            c = eng.sheet_metal_part_cost(p, s)
            el.rm_rate_per_kg = mat.cost_per_kg
            el.material_override, el.process, el.coating = c.material_cost, c.stamping_cost, c.coating_cost
            el.ohp_override, el.packing_transport = c.ohp, c.packing_transport
            result.detail = c
            result.detail_inputs = {"material": mat, "coating": coat, "input": p}
    except (ValueError, ZeroDivisionError, KeyError) as exc:
        result.error = "Calculator could not run: " + (str(exc) if not isinstance(exc, ZeroDivisionError)
                                                        else "a value used for division is zero (weight, economy factor, cycle time or cavities)")
        el.material_override, el.ohp_override, el.packing_transport = 0.0, 0.0, 0.0
        el.process = 0.0
    if line.cavities and line.cycle_time_s:
        result.capacity = eng.monthly_capacity(int(line.cavities), line.cycle_time_s, s)
    return result


@dataclass
class ProductSummary:
    lines: list[LineResult]
    variants: list[tuple[db.Variant, eng.VariantRollup]]
    investment: dict[str, dict[str, float]]
    assembly: eng.AssemblyCost | None
    assembly_error: str
    total_investment: float


def summarize(session: Session, product: db.Product) -> ProductSummary:
    s = load_settings(session)
    results = [cost_line(session, line, s) for line in product.lines]
    vol = {v.id: v.monthly_volume or 0 for v in product.variants}
    for r in results:
        r.monthly_volume = sum(vol.get(vid, 0) * q for vid, q in r.engine_line.qty_per_variant.items())  # MasterBOM F
    engine_lines = [r.engine_line for r in results]
    variants = [(v, eng.rollup(engine_lines, v.id)) for v in product.variants]
    investment = {o: eng.investment_by_owner(engine_lines, o) for o in ("Aditya", "Customer")}
    total_inv = investment["Aditya"]["total"] + (product.edd_cost or 0) + (product.validation_cost or 0)

    assembly, asm_err = None, ""
    if product.asm_cycle_time_s and product.asm_amortization_volume:
        try:
            assembly = eng.assembly_cost(eng.AssemblyInput(
                manpower=int(product.asm_manpower or 0), cycle_time_s=product.asm_cycle_time_s,
                efficiency=product.asm_efficiency or 0, man_hour_cost=product.asm_man_hour_cost or 0,
                line_cost_specific=product.asm_line_cost_specific or 0,
                line_cost_shared=product.asm_line_cost_shared or 0,
                line_utilization=product.asm_line_utilization or 0,
                amortization_volume=product.asm_amortization_volume))
        except ZeroDivisionError:
            asm_err = "Assembly output per hour is zero. Check cycle time and efficiency."
    return ProductSummary(results, variants, investment, assembly, asm_err, total_inv)

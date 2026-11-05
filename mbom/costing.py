"""Costing formulas carried over from MasterBOM_A02_AATPL_Prototype.xlsx.

Each function mirrors one sheet of the workbook. The cell each value came
from is noted next to it, so the numbers can be checked against Excel.
Where the workbook has a bug, the intended formula is used and the bug is
described in docs/excel-analysis.md.

All money is in INR and all weights are in grams unless the name says otherwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Hard-coded constants found in the workbook. Later these become settings.
MOULDING_EFFICIENCY = 0.85        # 'Plastic parts- Costing'!F31
PACKING_TRANSPORT_RATE = 0.02     # 2% used on both costing sheets
STAMPING_PROFIT_REJECTION = 0.10  # 'Sheet metal- Costing'!F28
# MasterBOM column AR: OHP = PROCESS * (27% + 20% + 2%)
MASTERBOM_OHP_RATES = (0.27, 0.20, 0.02)
# MasterBOM column BC: 20 days x 3 shifts x 25,900 s
CAPACITY_SECONDS_PER_MONTH = 20 * 3 * 25900


# --------------------------------------------------------------------------
# Plastic (injection moulded) part  -- sheet 'Plastic parts- Costing'
# --------------------------------------------------------------------------
@dataclass
class PlasticPartInput:
    part_weight_g: float          # F16
    runner_wastage: float         # F18, looked up from runner system (Hot runner 10%, ...)
    rm_cost_per_kg: float         # F21, looked up from the plastic RM database
    cavities: int                 # F25
    machine_hour_rate: float      # F29, looked up from machine tonnage
    cycle_time_s: float           # F30
    ohp_rate: float               # F34, overhead & profit as a fraction of process cost


@dataclass
class PlasticPartCost:
    material_per_part_g: float
    material_cost: float          # [A]
    output_per_hour: int
    process_cost: float           # [B]
    ohp: float                    # [C]
    packing_transport: float      # [D]
    total: float                  # [A+B+C+D]


def plastic_part_cost(p: PlasticPartInput) -> PlasticPartCost:
    sprue_g = p.runner_wastage * p.part_weight_g                       # F19
    material_g = p.part_weight_g + sprue_g                             # F20
    material = p.rm_cost_per_kg * material_g / 1000                    # F22
    output = math.floor(3600 * p.cavities * MOULDING_EFFICIENCY / p.cycle_time_s)  # F31
    process = p.machine_hour_rate / output                             # F32
    ohp = p.ohp_rate * process                                         # F35
    pt = PACKING_TRANSPORT_RATE * (ohp + process + material)           # F36
    return PlasticPartCost(material_g, material, output, process, ohp, pt,
                           material + process + ohp + pt)              # F38


# --------------------------------------------------------------------------
# Sheet metal (stamped) part  -- sheet 'Sheet metal- Costing'
# --------------------------------------------------------------------------
def stamping_cost_per_stroke(tonnage: float) -> float:
    """Thumb rule from D21:D26. Rs per 100 T: 0.5 below 200 T, 1.0 to 300 T, 1.5 to 400 T.

    The note on the sheet says 0.55 per 100 T below 200 T, but the formula
    uses 0.5. The formula is kept here; see the analysis doc.
    """
    if tonnage < 200:
        return tonnage * 0.005
    if tonnage <= 300:
        return tonnage * 0.01
    if tonnage <= 400:
        return tonnage * 0.015
    raise ValueError(f"No stamping rate defined for presses above 400 T (got {tonnage} T)")


@dataclass
class StampingStage:
    name: str
    tonnage: float
    cavities: int = 1

    @property
    def cost(self) -> float:
        return stamping_cost_per_stroke(self.tonnage) / self.cavities   # F21:F26


@dataclass
class SheetMetalPartInput:
    part_weight_g: float          # F14
    economy_factor: float         # F15 (yield: part weight / input weight)
    rm_cost_per_kg: float         # F13, looked up from the sheet metal RM database
    stages: list[StampingStage]   # rows 21-26
    surface_area_sq_in: float = 0.0       # F33
    coating_rate_per_sq_in: float = 0.0   # looked up from B76:C79 (Zn-Ni = 0.25)
    ohp_rate: float = 0.10                # F37


@dataclass
class SheetMetalPartCost:
    input_weight_g: float
    material_cost: float          # [A]
    stamping_cost: float          # [B]
    coating_cost: float           # [C]
    process_cost: float           # [D] = B + C
    ohp: float
    packing_transport: float
    total: float


def sheet_metal_part_cost(p: SheetMetalPartInput) -> SheetMetalPartCost:
    input_g = p.part_weight_g / p.economy_factor                       # F16
    material = input_g * p.rm_cost_per_kg / 1000                       # F17
    stages = sum(s.cost for s in p.stages)                             # F27
    stamping = stages * (1 + STAMPING_PROFIT_REJECTION)                # F28:F29
    coating = p.coating_rate_per_sq_in * p.surface_area_sq_in          # F35
    process = stamping + coating                                       # F36 (fixed: Excel adds F34, a text cell)
    ohp = process * p.ohp_rate                                         # F38
    pt = (material + process) * PACKING_TRANSPORT_RATE                 # F39 (excludes OHP, unlike plastics)
    return SheetMetalPartCost(input_g, material, stamping, coating, process, ohp, pt,
                              material + process + ohp + pt)           # F41


# --------------------------------------------------------------------------
# Assembly labour + line amortization  -- sheet 'Costing - Assy'
# --------------------------------------------------------------------------
@dataclass
class AssemblyInput:
    manpower: int                       # C2
    cycle_time_s: float                 # C3 (bottleneck station)
    efficiency: float                   # C4
    man_hour_cost: float                # C5
    line_cost_specific: float           # C10
    line_cost_shared: float = 0.0       # C11
    line_utilization: float = 1.0       # C12
    amortization_volume: float = 1.0    # C13


@dataclass
class AssemblyCost:
    output_per_hour: int
    labour_per_part: float      # [A]
    amortization_per_part: float  # [B]
    total: float


def assembly_cost(a: AssemblyInput) -> AssemblyCost:
    output = math.floor(3600 * a.efficiency / a.cycle_time_s)            # C6
    labour = a.man_hour_cost * a.manpower / output                       # C7
    # C14 = C11*C12 + C10: the utilization factor applies only to a shared line.
    amortizable = a.line_cost_shared * a.line_utilization + a.line_cost_specific
    amort = amortizable / a.amortization_volume                          # C15
    return AssemblyCost(output, labour, amort, labour + amort)           # C17


# --------------------------------------------------------------------------
# MasterBOM child part rows and the roll-up for each product variant
# --------------------------------------------------------------------------
@dataclass
class BomLine:
    description: str
    weight_g: float = 0.0                 # E
    qty_per_variant: dict[str, float] = field(default_factory=dict)  # I:AJ
    rm_rate_per_kg: float = 0.0           # AK
    economy_factor: float = 0.0           # AL
    process: float = 0.0                  # AO (typed in, or taken from a costing calculator)
    heat_treatment: float = 0.0           # AP
    coating: float = 0.0                  # AQ
    bop: float = 0.0                      # AS (bought-out part price)
    tool_owner: str = ""                  # BF ("Aditya" / "Customer")
    tooling_cost: float = 0.0             # BG
    fixture_gauge_cost: float = 0.0       # BH
    machinery_cost: float = 0.0           # BI

    @property
    def norms_g(self) -> float:           # AM
        return self.weight_g / self.economy_factor if self.economy_factor else 0.0

    @property
    def material(self) -> float:          # AN
        return self.rm_rate_per_kg * self.norms_g / 1000

    @property
    def ohp(self) -> float:               # AR
        return self.process * sum(MASTERBOM_OHP_RATES)

    @property
    def total(self) -> float:             # AT
        return self.material + self.process + self.heat_treatment + self.coating + self.ohp + self.bop


@dataclass
class VariantRollup:
    weight_g: float
    material: float
    process: float
    heat_treatment: float
    coating: float
    ohp: float
    bop: float

    @property
    def total(self) -> float:
        return self.material + self.process + self.heat_treatment + self.coating + self.ohp + self.bop


def rollup(lines: list[BomLine], variant: str) -> VariantRollup:
    """MasterBOM rows 3-30: SUMPRODUCT of each cost column with the variant's quantities."""
    def sp(attr: str) -> float:
        return sum(getattr(l, attr) * l.qty_per_variant.get(variant, 0) for l in lines)
    return VariantRollup(sp("weight_g"), sp("material"), sp("process"), sp("heat_treatment"),
                         sp("coating"), sp("ohp"), sp("bop"))


def investment_by_owner(lines: list[BomLine], owner: str) -> dict[str, float]:
    """MasterBOM BG3:BJ4: SUMIF of investment columns by tool owner."""
    sel = [l for l in lines if l.tool_owner.lower() == owner.lower()]
    tooling = sum(l.tooling_cost for l in sel)
    fg = sum(l.fixture_gauge_cost for l in sel)
    mach = sum(l.machinery_cost for l in sel)
    return {"tooling": tooling, "fixture_gauge": fg, "machinery": mach, "total": tooling + fg + mach}


def monthly_capacity(cavities: int, cycle_time_s: float) -> float:
    """MasterBOM column BC."""
    return CAPACITY_SECONDS_PER_MONTH * cavities / cycle_time_s

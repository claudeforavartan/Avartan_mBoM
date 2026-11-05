# Analysis of `MasterBOM_A02_AATPL_Prototype.xlsx`

This is the spreadsheet the app replaces. Every formula below is implemented in
`mbom/costing.py`. `tests/test_costing_matches_excel.py` checks the code against
the values Excel saved in the workbook.

## 1. What the workbook contains

| Sheet | Visible | What it does |
|---|---|---|
| **MasterBOM** | yes | Main sheet. Child parts for the product, a quantity per part for up to 28 variants, a cost breakdown per part, a roll-up per variant, and investment (tooling) |
| Plastic parts- Costing | yes | Cost calculator for one injection-moulded part (the example is a gear wheel) |
| Sheet metal- Costing | yes | Cost calculator for one stamped part (the example is a centre plate) |
| Costing - Assy | yes | Assembly labour and assembly-line amortization per unit |
| Plastic RM DBase | yes | 169 plastic grades with ₹/kg, plus machine-tonnage → MHR and runner-system → wastage tables |
| Sheet Metal RM DBase | yes | 62 steel, SS and brass grades with ₹/kg |
| Cover Sheet | yes | Purpose, revision history (Ver 0, 2015 → Ver 9, 2024) and legend |
| Sheet Metal - Costing | hidden | Older (2013) stamping calculator based on press-day costs |
| MasterBOM (Rev 0) | hidden | Older template (MX3 window regulator) with target cost, build levels (Proto/T0–T3/PTR), stock and assembly cost |
| Sheet1 | hidden | Scratch notes on part materials and machine power ratings |

**The current product (A02_AATPL MG Motor – AICI)** has 22 child parts, 1 variant in
use (out of 28 variant columns) and a monthly volume of 10,000.
- **Cost per unit: ₹2,009.33.** Material ₹928.17, process ₹312.40, heat treatment
  −₹76.57, coating ₹115, OHP ₹153.08, bought-out parts ₹577.25.
- **Investment: ₹2.77 Cr.** Aditya-owned tooling ₹41.39 L, ED&D ₹2.115 Cr, validation ₹24 L.

## 2. How the cost is calculated

### MasterBOM, per child part (one row)
```
Norms (input weight, g) = Weight / Economy factor
Material                = RM rate (₹/kg) × Norms / 1000
OHP                     = Process × (27% + 20% + 2%) = Process × 0.49
Total                   = Material + Process + HT + Coating + OHP + BOP
```
### MasterBOM, per variant (rows 3–30)
`Σ (part cost × qty of that part in the variant)` for each cost column.
Investment is summed separately for each tool owner (Aditya or Customer).
Capacity per month is `20 days × 3 shifts × 25,900 s × cavities / cycle time`.

### Plastic part calculator
```
Material/part (g) = Part wt × (1 + runner wastage)     Hot runner 10%, Hot sprue 5%, Cold runner 30%
Material  [A]     = ₹/kg × material g / 1000
Output/hr         = ROUNDDOWN(3600 × cavities × 85% / cycle time)
Process   [B]     = MHR (from tonnage) / output per hr  50T=250 … 1000T=4000
OHP       [C]     = OHP% × B
P&T       [D]     = 2% × (A + B + C)
Total             = A + B + C + D
```
### Sheet metal calculator
```
Material [A]   = (Part wt / economy factor) × ₹/kg / 1000
Stage cost     = tonnage × 0.005 (<200T) | 0.01 (≤300T) | 0.015 (≤400T), ÷ cavities
Stamping [B]   = Σ stages × 1.10          (10% profit & rejection)
Coating  [C]   = surface area (sq in) × ₹/sq in   Zn-blue 0.12, Zn-yellow 0.15, Zn-black 0.11, Zn-Ni 0.25
Process  [D]   = B + C
OHP            = D × OHP%
P&T            = 2% × (A + D)
Total          = A + D + OHP + P&T
```
### Assembly
```
Output/hr     = ROUNDDOWN(3600 × efficiency / bottleneck cycle time)
Labour/part   = man-hour cost × manpower / output per hr
Amortization  = (shared line cost × utilization + specific line cost) / amortization volume
```

### What the user types in, and what is calculated
- **Typed in for each part:** description, material spec, weight, qty per variant,
  RM rate, economy factor, process cost, HT, coating, BOP price, tool owner, tooling cost.
- **Typed in for each product:** monthly volume per variant, exchange rates, ED&D, validation.
- **Typed in for each calculator:** part weight, cavities, cycle time, tonnage, OHP %,
  stamping stages, surface area.
- **Looked up from the databases:** plastic ₹/kg, MHR from tonnage, runner wastage,
  sheet-metal ₹/kg and thickness, coating rate.

## 3. Problems found in the workbook

**Bugs (they give wrong numbers):**
1. **The sheet-metal total shows `#VALUE!`.** `F36 = F29 + F34` adds the coating *name*
   (`"Zn- Ni"`) instead of the coating cost in `F35`. Every cell after it fails.
   The intended total for the example part is **₹45.21**, and the app uses that formula.
2. **The plastic material rate lookup is wrong.** `F21` searches for the *grade* name
   in the *Manufacturer* column, and uses approximate match (`TRUE`) on an unsorted
   list. It returns ₹300, which is correct for this grade only by chance. A different
   grade can silently pick up another material's price. The app will match the grade exactly.
3. **The surface-treatment labels are swapped.** `B32` says "Surface area" but is blank,
   and `B33` says "Cost/Surface Area" but holds the area (24).
4. **The stamping note and formula disagree.** The note says ₹0.55 per 100 T below
   200 T, but the formula uses ₹0.50. Presses above 400 T give a blank cost.
   The app keeps 0.50 until you confirm which is right.

**The sheets aren't connected:**
5. **The calculators aren't linked to MasterBOM.** Process cost in MasterBOM is typed by
   hand, so the plastic and sheet-metal sheets are worked out on the side and then
   re-keyed. The fan, for example, is costed with a different method (economy factor,
   49% OHP) from the plastic calculator (runner wastage, 12% OHP, 2% P&T).
6. **The assembly cost isn't included in the total.** The Costing - Assy sheet gives
   ₹32.96 per unit, but nothing references it, so the ₹2,009.33 total leaves out
   assembly labour. Rev 0 had an "Assy Cost" column; the current version dropped it.
7. **Investment isn't amortized into the piece price.** That includes ₹41 L of tooling
   and ₹2.1 Cr of ED&D.
8. **RM rates in MasterBOM are typed by hand.** The materials used (ADC12 die-cast,
   50WW470 lamination, copper wire, 40Cr bar, 6063 Al) are not in either database.
9. **OHP percentages are inconsistent.** MasterBOM uses 49%, the plastic sheet 12% and
   the sheet-metal sheet 10% + 10%. P&T includes OHP for plastic parts but excludes it
   for sheet metal.

**Data quality:**
10. **The plastic database has duplicates and doubtful prices.** "Celcon M90 Beige"
    appears as both DuPont PA66 and Ticona POM, and "Duracon AW09 NC" has two prices
    (276 and 327.68). Several SAP numbers repeat. A few prices look like typos:
    Delrin 500AF ₹4,200/kg, PPC 1640 ₹1,900/kg, PP GFB 599 ₹799.73/kg.
11. **The sheet-metal costing sheet keeps its own copy of the RM table**
    (`H7:J68`) instead of reading the database, so the two copies can drift apart.
12. **There are hard-coded constants and leftovers.** `ED&D = 2500×94×90` has no
    explanation; the USD/EUR rates are entered but never used; a broken drop-down
    (`#REF!`) sits on MasterBOM C31; a stray test formula sits in Plastic RM DBase I6.
13. **Heat treatment has negative values** (stator −58.8, rotor −17.77). These look like
    a scrap credit entered under HT.

## 4. Gaps for producing a quotation

The workbook stops at the cost of goods. A quotation also needs:
- assembly labour (problem 6);
- rejection/scrap allowance and packing/logistics at the assembly level;
- tooling, ED&D and validation amortized over a chosen volume, or quoted as one-time charges;
- Aditya's margin, and optionally ICC and warranty;
- currency conversion, revision control, and a customer-facing PDF;
- target cost compared with estimated cost (Rev 0 had this, the current sheet doesn't).

## 5. What "upload mechanical drawings" can realistically do

| Input | What the app can pull out | Reliability |
|---|---|---|
| **3D CAD (STEP/IGES)** | Volume → weight (using material density), surface area (for coating), bounding box (blank and strip size), projected area (for moulding tonnage estimate) | High, done by calculation |
| **2D PDF drawing** | Title block (part no, material, weight, finish) and BOM table, read by AI | Medium: needs a human to confirm |
| **Assembly BOM export (Excel/CSV)** | Full child-part list with quantities | High |

The recommended flow is: upload the drawings, the app proposes the part list, material
and weight, a person reviews and confirms, then the costing runs. Drawings are stored
against each part (the `COMMENTS` column today holds file names such as `Fan.pdf`).

## 6. Proposed app

- **Database:** materials and rates, machines (tonnage → MHR), processes, coatings,
  suppliers, customers. Products have variants and BOM lines; every quotation is saved
  as a revision.
- **Costing engine:** `mbom/costing.py`, pure Python and tested against the workbook.
  More calculators to add: die casting, machining, lamination, winding.
- **Screens:**
  - Projects → BOM tree → part costing form
  - Rate databases (Purchase team edits them)
  - Quotation builder → PDF
  - Excel import for existing BOMs
- **Stack:** Python (FastAPI) backend, SQLite now and PostgreSQL later, and a web front end.

### Phases
1. **Costing engine and data model.** Import this workbook, then reproduce ₹2,009.33 from the database.
2. **Web UI.** BOM editing, part calculators and rate databases.
3. **Quotations.** Margin, amortization and PDF output.
4. **Drawing uploads.** File storage per part, then STEP geometry extraction, then AI extraction from PDFs.
5. **Users, roles and approvals.**

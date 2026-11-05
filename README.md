# Aditya mBoM

A web app that replaces the MasterBOM Excel workbook. You can import a BOM, cost
each part with the MasterBOM columns or the plastic and sheet-metal calculators,
keep the rate databases in one place, attach drawings to parts, and give each
team member a login with their own permissions.

## Run it on your computer

You need Python 3.11 or newer (check with `python --version`).

1. Get the latest code:
   ```bash
   git pull
   ```
2. Install the packages. This is needed the first time only, and again if `requirements.txt` changes:
   ```bash
   pip install -r requirements.txt
   ```
3. Start the app:
   ```bash
   python run.py
   ```
   In VS Code you can instead press **F5** and choose **Run mBoM app**.
4. Open **http://localhost:8000** in your browser.
5. Log in as `admin` with password `admin`. The app will ask you to choose a new password.
6. Go to **Import Excel** and upload your MasterBOM workbook. This loads the BOM, the
   assembly cost and all the rate databases.

To stop the app, press `Ctrl+C` in the terminal where it's running.

Your data (the database, uploaded drawings and the login key) is kept in the `data/`
folder. That folder is never committed to git. To start again from nothing, stop the
app and delete `data/`.

## What's in the app

| Page | Who can change it |
|---|---|
| Products: BOM, cost roll-up per variant, investment, assembly cost | Admin, Engineering |
| Part page: costing method, plastic or sheet-metal calculator, drawings and documents | Admin, Engineering |
| Rate databases: plastic and sheet-metal materials, moulding machines, runners, coatings | Admin, Purchase |
| Import Excel | Admin, Engineering (rate tables only with Purchase or Admin rights) |
| Settings: the constants from the workbook formulas | Admin |
| Users | Admin |

Anyone who is logged in, including Sales, can view everything.

## Code layout

- `mbom/costing.py`: the cost formulas taken from the workbook.
- `app/`: the web app (FastAPI). It contains `db.py` (database tables), `importer.py`
  (Excel import), `costs.py` (links the database to the formulas), `main.py` (pages)
  and `templates/` (HTML).
- `docs/excel-analysis.md`: what the workbook does, and the problems found in it.

## Tests

```bash
python -m unittest -v
```

The tests check the costing against the numbers in the workbook. One of them imports
the real workbook. It runs only if you tell it where the file is:

```bash
MBOM_TEST_WORKBOOK=path/to/MasterBOM_A02_AATPL_Prototype.xlsx python -m unittest -v
```

(On Windows PowerShell, run `$env:MBOM_TEST_WORKBOOK="path\to\file.xlsx"` first, then `python -m unittest -v`.)

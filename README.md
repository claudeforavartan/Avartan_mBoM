# Aditya_mBoM

Starter repository. For now it holds a hello-world script that checks the Python setup.

## Run it

From a terminal in the repo folder:

```bash
python hello.py
```

In VS Code you can also open `hello.py` and press **F5**. That runs the
"Python: Run hello.py" configuration and needs the Python extension.

## Costing engine

`mbom/costing.py` holds the cost formulas taken from the MasterBOM Excel workbook.
`docs/excel-analysis.md` explains what the workbook does and lists the problems found in it.

Run the tests, which check the code against the numbers in the workbook:

```bash
python -m unittest -v
```

"""Start the mBoM app:  python run.py   then open http://localhost:8000"""

import os
import sys

if sys.version_info < (3, 10):
    sys.exit(
        f"This app needs Python 3.10 or newer, but this is Python {sys.version.split()[0]} "
        f"({sys.executable}).\n"
        "On Windows, create the project environment with:  py -3.14 -m venv .venv\n"
        "then run:  .venv\\Scripts\\python -m pip install -r requirements.txt\n"
        "and start the app with:  .venv\\Scripts\\python run.py"
    )

import uvicorn  # noqa: E402

if __name__ == "__main__":
    host = os.environ.get("MBOM_HOST", "127.0.0.1")
    port = int(os.environ.get("MBOM_PORT", "8000"))
    print(f"\n  Aditya mBoM is starting. Open http://localhost:{port} in your browser.")
    print("  First login: username admin, password admin (you'll be asked to change it).")
    print("  Press Ctrl+C here to stop the app.\n")
    uvicorn.run("app.main:app", host=host, port=port, reload=os.environ.get("MBOM_RELOAD") == "1")

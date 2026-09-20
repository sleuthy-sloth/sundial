"""Confirm the venv really has its dependencies (the hollow-venv check) and that
the app imports. Run:  backend/.venv/bin/python scripts/verify_install.py
"""

import importlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))

for name in ("fastapi", "uvicorn", "pytest", "httpx"):
    mod = importlib.import_module(name)
    print(f"  {name} {getattr(mod, '__version__', '?')}")

import app  # noqa: E402

routes = sorted(r.path for r in app.app.routes if r.path.startswith("/api"))
print("  app imports OK — api routes:", ", ".join(routes))

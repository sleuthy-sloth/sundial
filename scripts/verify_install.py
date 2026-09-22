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

# The API's paths, taken from the document the app serves rather than from `app.routes`: an
# included router is a node in that list rather than a flat path, and the document is the same
# list stated the way a caller sees it. It also carries the debug docs, which is why the
# printed set is the paths a browser can ask for rather than only the hand-written ones.
routes = sorted(p for p in app.app.openapi()["paths"] if p.startswith("/api"))
print("  app imports OK — api routes:", ", ".join(routes))

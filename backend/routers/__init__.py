"""The API, one module per area of the app. `main.py` mounts them.

The modules are flat — `routers.blocks`, not a package per area — because the file layout is
the map: `routers/blocks.py` holds the routes, `schemas/blocks.py` the body they accept,
`services/blocks.py` the rules behind them. A feature adds one file to each rather than growing
one of them.
"""

# tools/native_rig — FOBJ track reader (dev only)

Nothing here ships in the installer, and the app never imports it.

| Module | What it does |
|---|---|
| `fobj_reader.py` | The FOBJ (figatree) track reader: `decode`, `native_value`, `read_figatree`. The Watch Lite audit (`tools/liteaudit/`) reads it |

Importing the package puts `app/backend` on `sys.path` (the readers use `vault.echo`).

The fighter-rig readers that used to sit beside it (rig inventory, movement ownership, the rig preflight)
are maintained in `tools/fighterport/fighter_port/compat/`, where the fighter-port engine loads them.

# Import a stage model (not built)

A placeholder. No code lives here yet, and none of Randall runs anything for it.

**Today.** "Import a stage model" is the fourth starting point (`recipes.LAUNCHABLE`, task id `stage_import`),
listed with `available: false` so the panel shows it as a disabled tile marked "Use MCP". It has no card,
no tools and no routing: `recipes.startable` leaves it out, so the blueprint (`routes/assistant_bp.py`) drops a
`context.task` of `stage_import` and a chat that claims it is an ordinary chat
(`tests/backend/test_assistant_stage_recolor.py`). The sidebar and the "Start another" row do not offer it.

**What it will be.** A 3D stage model in (the same kinds of files a character model import takes), a playable
Melee stage out, saved to the vault like the other two pipelines' results. It is the stage counterpart of
`../model_import/`, which turns a model into a costume.

**Open questions for the owner** before any code is written:

- **Collision.** Generated from the model's walkable surfaces, drawn by hand, or borrowed from an existing
  stage's collision (and how a ledge, a platform and a wall are told apart)?
- **Blast zones.** Fixed defaults per stage size, measured from the model, or set by the user?
- **Camera bounds.** The camera's limits and its default framing; who checks that the whole stage reads at
  match start?
- **Spawn points.** Where the four players and respawn platforms go, and how many are required.
- **Stage slot.** A new stage in a free slot (custom stage, needs a stage-select entry), a Dynamic Alternate
  Stages variant of one of the six tournament stages, or replacing an existing stage's files outright (and so
  inheriting that stage's collision, music and hazards)?
- **Textures and animation budget.** How many textures, at what sizes and formats, and whether moving parts or
  animated scenery are in scope; what is cut when a model is over budget.

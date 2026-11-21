# Create a character (not built)

A placeholder. No code lives here yet, and none of Randall runs anything for it. The owner will build it later.

**Today.** "Create a character" is the third Characters starting point (`recipes.LAUNCHABLE`, task id
`create_character`), listed with `available: false` so the panel shows it as a disabled tile marked "Use MCP"
(hint: "Use MCP (Settings > AI): build a whole new fighter, starting from a model."). It has no card, no tools and no
routing: `recipes.startable` leaves it out, so the blueprint (`routes/assistant_bp.py`) drops a `context.task` of
`create_character` and a chat that claims it is an ordinary chat (`tests/backend/test_assistant_stage_recolor.py`).
The sidebar, the task pill and the "Start another" row do not offer it.

It is not the ordinary `create_clone_character` ability (`assistant/clone_character.py`), which clones an existing
fighter in any chat. That ability stays as it is and is not this feature.

**What it will be.** A whole new playable fighter, built in the vault and added to the game, not just a new costume
on an existing one.

**Step one is model import.** The fighter starts from a 3D model, so the first step is `../model_import/`, which
turns a model into a costume. Everything after it (moves, sounds, menu art, the slot) is what this feature adds.

**Open questions for the owner** before any code is written:

- **Moveset source.** Clone an existing fighter's moves (and which one), or author new moves?
- **Animations.** Reuse the cloned fighter's animations on the new rig, or retarget or build new ones?
- **Sounds.** Reuse an existing fighter's voice and effect sounds, or bring new ones?
- **CSS icon, portraits and stock icons.** Where the character-select art comes from: generated from the model,
  supplied by the user, or both.
- **Fighter slot.** A new fighter slot through m-ex, and how it is named and ordered on the select screen.
- **Balance and attributes.** Weight, speed, jump and the rest: copied from the base fighter, set by the user, or
  checked against limits.

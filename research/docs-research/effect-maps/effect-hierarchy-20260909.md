# Effects hierarchy: human editing and record access

The user clarified this requirement during the roster investigation on 2026-09-09: an effect or move is the unit; recognizable visual parts are its editable children; individual offsets/records remain available to Randall's future extras-creation tool. The human editor stops at visual parts. Building Randall's tool follows this investigation.

The user further clarified that human controls should be curated for worthwhile, noticeable changes. Mapping a small hit spark or incidental flash does not justify another menu item. Prioritize signature flames, trails, projectiles, shine and sword trails; keep tiny technical details available to later tooling without turning them into human UI clutter. Optional hit-spark discovery is not a completion gate for this review.

## Three levels

1. **Move/effect unit** — Firefox/Firebird, Screw Attack, Fireball, etc. This is the entry point in the character's extras menu.
2. **Human subpart** — startup rings, flame puffs, wisps, flight streamers, electrical arcs, rotating swirl. One part may have meaningful Core/Tint or color/texture controls. Related animation records change together; record ordinals and addresses are not extra UI sliders.
3. **Technical records** — exact RGB/RGBA operands, packed vertex colors, texture/palette entries, animation variants and model anchors. Preserve these individually, including their membership in each human control, for precise investigation and later Randall access.

Storage recipe IDs and DAT boundaries are implementation details. A single human part can span multiple recipes or files; conversely one recipe can contain several human parts. The menu projection must not redefine the patch or protocol identity.

## Up-B example

| Human context / part | Existing technical bindings | Scope |
|---|---|---|
| Charge: startup rings and streaks | `upb.rings`, `upb.charge_lines` | Fox/Falco |
| Charge: rising flame puffs | `charge_flames.flame_c1/c2`, EfCo scripts 299 | Fox |
| Charge: wisps | `charge_flames.wisp_c1/c2`, EfCo script 300 | Fox |
| Main flame shape/glow | `upb.tip`, `upb.body` | Fox/Falco; individual body timing remains unproven |
| Flight: fire puffs | `upb.trail`, `upb.small_trail`, `upb_charge_fire.color1` | Fox/Falco |
| Flight: streamers | `upb.fire` invokes `upb_texture` | Fox/Falco |
| Flight: accents | `upb.dots`, `upb.flare` | Fox/Falco |

The legacy `upb_charge_fire` ID means **Flight Fire Texture**, not startup flames. It remains unchanged for saved mods and imports. New charge flames are Fox-only despite other Up-B components being shared.

## Current integration boundary

> **Superseded the same day (2026-09-09, later session).** The presentation-only
> workspace (`effectHierarchy.js` / `EffectWorkspaceNav`) was replaced by a real
> unit contract: a move IS one extra type, its parts are nested in the mod
> (`modifications.parts`, registry `core.extra_types.UNIT_PARTS`, writer
> `blueprints/extras/unit_parts.py`), and the editor is one full page of part
> rows (`frontend/src/components/storage/extras/EffectEditorPage.jsx`). The
> three-level model below still describes the intent; the paragraph after it
> describes the deleted implementation.

An explicit presentation registry grouped existing types into move workspaces in both Storage and MEX. `getExtraTypes()` continues to describe the original installable recipe types. The workspace uses human phase/part names and routes saved selection, edit, import and install actions to each original recipe and owner. Saves remain scoped to the selected recipe; there is no atomic whole-move bundle contract yet.

The standard editor groups related native keys into visual cards. Main Colors macros must update the real native keys even when those already have saved values. A diagram highlights the visual group it actually explains. Core/Tint can share the same spatial element; do not invent separate geometry for them. Mixed recolor captures are effect overviews, not isolated per-control evidence.

## Record contract for later Randall work

Retain stable record identities within a reference revision, original file and format, native color/alpha/count bytes, guarded relocation/structural identity, owning script/model/texture, human-group membership, shared consumers, and the evidence/trigger that demonstrates the part. Keep original per-record variation even when the human control has one representative swatch. Never flatten animation variants irreversibly into that swatch.

Future record-level edits should use those identities and the existing guarded write/restore paths. They must preserve alpha, command counts, pointers, and sibling groups. They should distinguish an unproven visual role from an invalid record. There is no new Randall write tool or arbitrary-offset API in this change.

See the retired roster-live report for current in-game evidence and the retired roster-control-routes report for native write/save/restore coverage.

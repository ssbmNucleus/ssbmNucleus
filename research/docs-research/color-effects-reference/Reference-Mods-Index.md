# Reference Mods Index — working effect mods in the backup

Curated from the mod-pool backup (`ssbm-backup`, DB dump
`db/2026-06-10_17-45-01.json`, files under `uploads/posts/YYYY/MM/post_<id>/`)
for the extras audit campaign. **Workflow** (see `docs/EXTRAS_AUDIT.md`): a
same-size DAT byte-diffed against `storage/test-base/files/` gives free offset
candidates — but recolor mods are often global find-replace, so diffs contain
do-nothing shrapnel; treat regions as candidates to live-poke, not answers.
Survey script: rerun `survey_effect_mods.py` pattern against the dump for new
queries.

## Per-character effect mods

| Target | Post | Title | Files | Why it matters |
|---|---|---|---|---|
| C. Falcon kick/raptor | 14832 | Blue Falcon Kick and Raptor Boost | EfCaData.dat | exactly the remaining Falcon 🔴s |
| C. Falcon effects | 14009 | American Falcon Effects | EfCaData - America.dat | broad EfCa coverage |
| C. Falcon punch | 14803 / 13734 | Scar Punch / Honduran Falcon Punch | EfCaData*.dat | punch fire/texture cross-checks |
| Mario fireball | 15777 | Better Fire Ball for Mario | PlMr.dat | fireball bytes in the PLAYER file |
| Mario cape | 14851 | Unmirrored Mario Cape | PlMr.dat | cape structure |
| Dr. Mario cape | 13332 | Blue Cape - Dr. Mario | PlDr*.dat | the 🔴 doc cape color |
| Luigi fireball | 15437 | Luigi Fireball - Trollface | PlLg.dat | green fireball bytes |
| Samus effects | **17088** | Samus Rainbow Effects | EfSsData rainbow **+ og**, PlSs rainbow **+ og**, EfCoData rainbow **+ original** | ships modded+vanilla PAIRS — self-contained diff kit |
| Samus | 13986 / 14701 | Vaporwave Samus / Powerbeam | EfSsData, PlSs | charge shot / beam |
| Ness + Pikachu (+more) | **15070** | Purple Electric Pack | EfNsData, EfPkData, EfCoData, EfFxData, EfSsData, PlFc | electric effect records across five files |
| Yoshi eggs | 15750 | Multicolored Egg Shields/Egg Rolls | PlYs<color>.dat ×5 | egg shield/roll colors (per-costume — diff two colors against each other too) |
| Pichu | 14819 | Blue Lightning (Pichu) | PlPc.dat | cross-check for our thunder offsets |
| Link items | 15262 / 15263 | Trans boomerang/bow/hookshot / Watermelon Bombs | PlLk.dat | boomerang/arrow/bomb regions |
| Falcon/Fox/Falco knee | 13903 / 13909 | knee electric mods | PlFc.dat / PlFx.dat | electric hit effect location |

## Cross-cutting leads

- **`EfCoData.dat` = the COMMON effects file** ("rainbow fire whole cast" in
  17088 recolors it): shared fire (and likely other elemental hit effects)
  used across the cast probably lives here — map it once, benefit everywhere.
  17088 ships original+modded EfCoData for a clean diff.
- 16443 "Animelee Energy Texture Overhaul" (EfCoData/EfCaData/EfFxData/
  EfSsData) and 14328 "YTG 20XX AGM" (many Ef*Data files) are broader texture
  overhauls — useful for locating texture regions, too invasive for offset
  diffs.
- No usable effect mods found for: Kirby (cutter/hammer), Jigglypuff (sing),
  Peach (turnip/umbrella visuals), ICs (blizzard/belay), Ganondorf
  (warlock punch color — only skins). Those missions start from the
  reference doc's cites + live pokes alone.

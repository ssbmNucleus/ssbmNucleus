# HSDRawViewer model export regression checks

From the repo root, on Windows with the .NET 8 SDK. The checks link the prebuilt HSDRawViewer
from the ssbmNucleus-hsdlib release (fetched, not built here):

```powershell
python tools/build/fetch_native.py hsdlib
dotnet run --project tests/backend/hsdraw_export -c Release -p:UseSharedCompilation=false --disable-build-servers
```

The console checks use synthetic DAT structures and the actual ModelExporter /
IONET SMD writer. They need no game assets or additional test packages. Coverage:

- Unique names, unnamed-DOBJ fallbacks, and case-sensitive names stay unchanged.
- Repeated labels get deterministic suffixes, reserving all original names.
- Explicit labels can collide with generated names or `_SINGLE` suffixes across joints.
- Export leaves source DAT labels intact and retains every triangle and its weights.
- Material hashing terminates on reference cycles while preserving the old hash
  for shared acyclic references (and thus existing material names).
- Empty texture descriptors produce a warning without dropping geometry or
  creating dangling texture links; later valid textures can still be exported.
- Null joint references use the exporter's existing missing-bone fallback,
  retaining the weight values (including a fully weighted missing joint).

For the local community corpus, use
[`verify_smd_exports.py`](../../../../tools/admin/verify_smd_exports.py). It reads
`scan.json` and `index.json`, selects every `model_changed` row, exports one
archive at a time, and records logs and checksums under a new output directory.
The executable defaults to `core.config.HSDRAW_EXE`; `--exe` can select an isolated
build. It does not modify the corpus or terminate processes.

```powershell
python tools/admin/verify_smd_exports.py --corpus PATH/website-imports --output scratch/smd-before --vanilla PATH/PlSsNr.dat
# Apply the fix and rebuild before the second run.
python tools/admin/verify_smd_exports.py --corpus PATH/website-imports --output scratch/smd-after --vanilla PATH/PlSsNr.dat --compare scratch/smd-before/results.json
```

Before the fix, a nonzero exit is expected. The comparison checks all previously
successful exports plus the vanilla control byte for byte. Results and extracted
assets belong in ignored `scratch/`, never in Git.

## Verified 2026-09-26

Compared a clean Release build of `8fbd92151aaf7a856711125b81beba8b8853c679`
(`origin/rebuild/model-import` at branch creation) with the fixed Release build.
Both runs used the default `--model export` options, including PNG export.

| Check | Before | After |
| --- | --- | --- |
| All model-changed costumes (45 posts) | 108/168 | 168/168 |
| Vanilla Samus `PlSsNr.dat` | Pass | Byte-identical |
| Previously successful community exports | 108 | All 108 byte-identical |
| Synthetic regression checks | Duplicate-name check fails | 9/9 pass |

The 60 previously failing costumes comprised 57 duplicate-name failures, two
material-hash cycles (Mist Valley Thunderbird and Chao), and Wii U Mario's empty
texture descriptor. After skipping that invalid texture, Wii U Mario also
exposed a null joint reference; it now uses the existing missing-bone root
fallback without changing weight values. All six Brawl Samus variants pass,
including `PlSsBkMod.dat` / `PlySamus5KBk_Share_joint` from post 17098.

The input DAT hashes match between every before/after pair. Vanilla Samus has
10,211 triangles and SMD SHA-256
`891fd5ef2f8e4866814a2bd3e44b28e5995c0aa612f7db78c710e25d47c004f5`.
Corpus `scan.json` SHA-256:
`6d3276f5d026148cb83b560a712678604c1330abad66879ee5e9ec5f2258b3c7`;
`index.json` SHA-256:
`e21289ea050446ee31410d790442e0355fad8aa4eafb9f812ab8034669be5673`.

Only HSDRawViewer source changed. HSDRaw library source is unchanged, so the
MexCLI HSDRaw DLL replacement rule does not apply to this fix.

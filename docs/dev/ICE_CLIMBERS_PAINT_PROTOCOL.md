# Combined Ice Climbers painting protocol

The painting editor starts its normal single-file preview, then sends
`loadPaintPair`. No new native command-line flags or Electron IPC channel are
required. Embedded Windows, streaming Windows, and Linux/macOS headless servers
dispatch the same runtime protocol through `Rendering/Models/PaintPairSession.cs`.

```json
{
  "type": "loadPaintPair",
  "sessionId": "editor-session-uuid",
  "requestId": "load-request-uuid",
  "members": [
    {"memberId": "popo", "datFile": "/resolved/Popo.dat", "sceneFile": "/resolved/Popo.yml", "dataFile": "/resolved/PlPp.dat"},
    {"memberId": "nana", "datFile": "/resolved/Nana.dat", "sceneFile": "/resolved/Nana.yml", "dataFile": "/resolved/PlNn.dat"}
  ]
}
```

`datFile` is required; `sceneFile` and `dataFile` are optional. The caller reuses
the paired source resolver and passes actual resolved custom-pair paths. The
two member IDs must be exactly `popo` and `nana`, and their DAT paths must differ.
The successful response is `paintPairLoaded` with `success: true`, echoed
`sessionId`/`requestId`, and labeled members. Both files and renderers are loaded
before the original preview is replaced. A failure preserves the old preview;
member-specific errors include `memberId`.

The preview uses one drawable containing two independent renderer/raw-file
owners. Each renderer receives its own scene pose, hidden nodes, accessories,
and texture cache. Display offsets are applied only to live world transforms,
without modifying the exported DAT descriptors. The camera is shared and its
framing is widened. The pair painting preview uses the saved poses; animation
commands cannot silently change only one member.

All pair painting requests require string `sessionId` and `requestId`, echoed
on both success and error responses. A pair request for an unknown session
never falls through to the single-file handler. An active pair cannot be
replaced by a delayed second load; opening a different pair creates a new
viewer session.

| Command | Response | Payload |
| --- | --- | --- |
| `getTextures` | `textureList` | Combined `textures` array; each row has `memberId`, `label`, `textureId`, local `index`, and existing texture metadata. |
| `getFullTexture` | `fullTexture` | Requires `memberId` and local `index`; returns that owner's PNG `data`, dimensions and texture identity. |
| `getUVLayout` | `uvLayout` | Combined owner-tagged geometry, or one owner's geometry when `memberId` is supplied. |
| `updateTexture` | `textureUpdated` | Requires `memberId`, local `index`, and PNG base64 `data`; acknowledges only after the owner update finishes. |
| `exportPaintPair` | `exportPaintPair` | Returns `members: [{memberId, data}, ...]` only after both DAT serializations succeed. |

Texture identity is `memberId:index`, for example `popo:0` and `nana:0`.
The optional `textureId` on targeted requests is validated against the member
and local index. Owners are never flattened into a global native texture index.
Texture lists encode the current cached pixels, so lists requested after edits
do not revert to initial thumbnails. Single-file requests without pair identity
keep their existing protocol.

Pair export acquires a mutation lease on the render thread. Frame generation
pauses while the serializer reads the two independent raw structures, keeping
the last published preview. Both exports complete before one success response
is sent. No partial `members` array is returned on failure, and edits remain
in the session. Legacy `exportDat` is rejected for a pair.

The serializer has a 25-second response deadline. If it exceeds that deadline,
the caller receives a correlated error identifying the member in progress. The
lease remains held until the background serializer actually exits; queued edits
and second exports cannot race an outstanding save. A late success is never
published. Temporary DATs use unique system-temp names and are removed by the
worker's `finally` block. Final paired ZIP/Vault persistence remains the frontend
and backend paired-save flow's responsibility.

The paired editor accepts Vault persistence only when the importer confirms
`imported_count: 2` and `pairing_complete: true`. The latter acknowledges that
both reciprocal links exist and the metadata transaction committed. An import
or linking failure retains editor changes and does not display pair-save
success; existing partial Vault entries are left for inspection before retry.

Native validation (the static test, the in-memory queue/protocol harnesses and the Roslyn
typecheck) now lives in the `ssbmNucleus-hsdlib` fork repo with the host source. Its checks use
synthetic data and do not rebuild or restart the application. The maintenance agent still needs to rebuild the native viewer and
visually verify vanilla/custom pairs, framing, painting, and paired save/reopen
on each packaged render path.

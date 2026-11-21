# Storage location integration

`electron/storage/storage-host.js` integrates the storage manager with startup recovery,
the progress window and trusted IPC (`electron/ipc/storage.js`). `electron/runtime/backend-launch.js` supplies the
same backend command for normal startup and maintenance. The host integrator
owns those modules, `electron/main.js` and `preload.js`.

## Required startup order and interface

1. Apply the existing `NUCLEUS_USERDATA_DIR` override, then acquire Electron's
   single-instance lock. Only the primary instance may run storage preparation.
2. The storage host constructs `StorageLocationManager` from `electron/storage/storage-location.js` with
   `{bootstrapDir: app.getPath('userData'), defaultRoot: defaultDataRoot(),
   migrate: createMigrationRunner({command, args, cwd, env}), onProgress}`.
   Bootstrap remains in this stable profile; do not relocate Electron userData.
   `command/args/cwd` use the same backend executable selection as normal startup;
   development uses the Python command with `[absoluteMexApiPath]` as args.
3. Disable the manager in development (`disabledReason: 'Storage relocation is
   available in installed builds; development data shares the source checkout.'`)
   and when inherited `NUCLEUS_STORAGE_DIR`, `NUCLEUS_DATA_ROOT` or `NUCLEUS_USERDATA_DIR` overrides are
   present (explain the override in `disabledReason`). Development root can be
   displayed using the repository app directory as `defaultRoot`.
4. After `app.whenReady()`, await `manager.prepareLaunch()` **before spawning any
   Flask backend, starting database consumers, or delivering queued protocol
   imports**. Merge the returned environment last into the normal backend env.
   Keep protocol URLs queued throughout preparation. Its asynchronous worker
   reports `{phase, files?, bytes?}` to `onProgress`; expose progress in the
   startup window, which must not claim the backend has started yet.
5. A preparation error blocks backend startup. Show its message and explicit
   recovery actions: retry after reconnecting the drive; cancel the failed
   pending move and use the retained current/original root; or use the previous
   root (`rollback`) when available. Do not automatically fall back. Rollback is
   startup-only and must not be exposed as a live root-switch operation. For
   failed copies, cancel then schedule a new empty destination for a future
   attempt. Partial stages and published-but-unselected copies are retained.

The host registers these with the existing trusted-renderer IPC wrapper. Errors
return `{success:false,error:message}`; successful calls return
`{success:true,...await manager.status()}` (or manager mutation result).

| Preload method on `window.electron` | IPC | Host action |
| --- | --- | --- |
| `getStorageLocation()` | `storage:status` | `manager.status()` |
| `chooseStorageLocation()` | `storage:choose` | native openDirectory dialog; return `{success:true,path: selectedParent}` or `{success:true,canceled:true}` |
| `scheduleStorageLocation(path)` | `storage:schedule` | `manager.schedule(path)` |
| `cancelStorageLocation()` | `storage:cancel` | `manager.cancel()` |

The Settings card appends `SSBM Nucleus Data` to the selected parent and shows
the exact candidate before its explicit **Schedule move** button. No restart
IPC is requested. A normal complete quit and next launch performs the copy.

The standalone worker is `backend/storage_relocation.py`; its maintenance CLI
is `app.py --storage-maintenance --source SOURCE --stage STAGE --target TARGET`.
The supplied Node runner also passes `--await-activation`: it resolves at the
verified event with `release(success)`/`assertAlive()` on the result. The manager
publishes the verified root and atomic bootstrap selection, then acknowledges
activation over stdin and awaits worker exit. Source/SQLite locks stay held
through publication. Failure sends abort; host death closes stdin and releases
locks without selecting or deleting data. Custom migration callbacks must
implement this same lease lifetime when they run real data copies.
Dispatch must occur after multiprocessing freeze support/safe streams but before
Flask/core imports, including config. Core's package initializer imports config,
so the maintenance module deliberately lives outside `core`.

## Scope and recovery

The full writable backend root moves: Vault/SQLite/JSON, projects, build/output,
logs, extracted assets and other app-owned backend files. Source remains for
rollback. Scratch is recreated under the chosen root; `TMP`, `TEMP`, `TMPDIR`
are passed to the backend and children and Python tempfile is pinned there.
The model import tools (`tools/model-import/`, `storage_relocation.REGENERABLE`) are not copied: they are a
download the app repeats from Settings, and on macOS and Linux they hold symlinks the worker refuses. The new
root has none until the user downloads them again; the old root keeps its copy.
Electron profile/account browser storage and browser/runtime caches stay in the
ordinary profile. External replay and ISO locations remain external.

File copies are verified and SQLite uses committed snapshots under write locks.
Updated backends hold a shared lifetime lease from `storage_data_lock.py`;
relocation requires its exclusive lease before inventory. This permits existing
short-lived backend workers while refusing moves until all updated consumers
have exited. Older binaries and external tools do not implement that lease, so
the primary Electron instance must still run preparation before starting any
consumer; SQLite locks and source rechecks provide additional protection.
Known absolute references are rebased only when the referenced source entry was
actually copied. Unknown arbitrary text/history is never string-replaced.
The bootstrap pointer changes atomically after verified staging publication;
selected roots carry a library identity marker. Source/destination overlap,
linked paths, unrelated destination contents, insufficient space and changed
sources fail closed. No original data or partial stage is automatically deleted.

Separate packaged Windows cross-drive/import/reopen testing and Linux/macOS
filesystem smoke tests remain release gates; unit tests do not substitute for
those platform and native-tool checks. No app rebuild or real migration is
performed by this implementation task.

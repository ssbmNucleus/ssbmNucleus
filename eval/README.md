# eval/ - benchmarks that call the app (not tests of it)

Two parts. None is imported by the shipped app and none runs in CI. Tests of
the app's own code live in `tests/backend/`, not here; only the tests of these
benchmark scripts live in `tests/eval/` (`pytest tests/eval/randall`; its `conftest.py` puts the harness folder and `app/backend` on `sys.path`). Run scripts by path from the repo root; each one
puts `app/backend` on `sys.path` itself. There is deliberately no `__init__.py` in
either folder: a package named `randall` here would shadow `app/backend/randall`.

## `randall/` - the Randall coach and assistant benchmark

Decides which LLM Randall runs. `v2_lane.py` drives `coach_tools_v2` through an
OpenAI-format tool loop and writes one transcript per run (`--out eval/randall/lanes_v2/<name>.json`,
untracked). `assistant_lane.py`, `routing_benchmark.py` + `routing_cases.py` + `fast_lane_check.py` (routing benchmark and the
coach's fast lane, see `ROUTING_BENCHMARK.md`), `skin_quality_lane.py` (recolors vanilla Fox for real
once per model and keeps the renders to compare by eye), `tool_cli.py` and `workflow_check.py`.
`runner.py` is the shared OpenRouter helper (`load_api_key`, `SpendTracker`, `estimate_cost_usd`).

```
app/venv/Scripts/python.exe eval/randall/v2_lane.py --model z-ai/glm-5.2 --question "why am i so bad against dr mario..." --out eval/randall/lanes_v2/glm.json
```

Needs `OPENROUTER_API_KEY` (env var, the Nucleus key store, or `.env` at the repo root; never printed).

## `corpus/` - eval corpus and the Randall task suite

`randall_tasks/` is the frozen randall20-v1 suite (manifest, lock, `run.py` / `grader.py` / `promote.py`,
`smoke5.json`; its tests are `tests/backend/test_eval_randall_tasks.py` and
`test_assistant_tasks_smoke_manifest.py`). Run by path from the repo root, e.g.
`app/venv/Scripts/python.exe -B eval/corpus/randall_tasks/run.py preflight`; the scripts put `eval/corpus`
and `app/backend` on `sys.path` themselves. Nothing in `app/` imports it.

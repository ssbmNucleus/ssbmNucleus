# Randall tool-calling benchmark

`routing_benchmark.py` compares complete next-action responses using Randall's
production schemas and prompts. Cases in `routing_cases.py` are synthetic; the
harness never calls a tool executor, reads a replay database, or changes a vault.
Only prompts, schemas and synthetic fixture state go to OpenRouter. The existing
encrypted development key is read in memory; no credentials are saved in receipts.
A case's `domain` is the prompt and roster it is asked under: `mod` is the
assistant's (`prompt.PROMPT`, `tools.SCHEMAS`), `coach` the Tracker coach's.

2026-10-03: the assistant's permanent prompt changed (its capability index: two
starting points, finding a mod as an ordinary ability, no menu background) and
an assistant turn no longer has a fast lookup lane, so the main model answers
every `mod` case in production. Earlier results predate both; rerun the live
benchmark into a new directory before comparing. `fast_lane_check.py` now checks
the coach lane only.

From the repository root, with the Nucleus virtualenv:

```powershell
app/venv/Scripts/python.exe -m pytest tests/eval/randall/test_routing_benchmark.py -q -p no:cacheprovider
app/venv/Scripts/python.exe eval/randall/routing_benchmark.py --out ../artifacts/routing-new --dry-run
app/venv/Scripts/python.exe eval/randall/routing_benchmark.py --out ../artifacts/routing-new --resume --ids m01 c03
app/venv/Scripts/python.exe eval/randall/routing_benchmark.py --out ../artifacts/routing-new --resume
```

Network access and a valid cached OpenRouter key are required for live requests.
Use a new directory for changed cases, prompts, schemas, or provider settings.
`--models`, `--modes`, `--ids`, `--workers` and `--budget` bound a run. The default
spend allowance is $3; the scheduler reserves $0.025 per in-flight request and
unknown-cost error. Rejected configurations stop new scheduling for that model.
There are no automatic retries. Always test compatibility on a few cases first.

A configuration OpenRouter rejects (on 2026-09-16 a GLM reasoning-disabled
control failed because reasoning was mandatory) produces no model completion. Do
not treat such rejection latency as model speed.

Output contains the complete input manifest, one JSONL receipt per request, and
an incremental summary.

Focused tool groups are chosen by the fixture. This measures the effect of
removing unrelated schemas, not a learned router's accuracy or overhead. Accuracy
checks exact next actions, not eventual task completion; unnecessary reads can
fail even when benign. Review all ambiguous/no-call cases and equivalent argument
forms before interpreting results. Cost includes observed caching. Use fresh
held-out requests and repeated latency samples before making product decisions.

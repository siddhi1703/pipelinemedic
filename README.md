# PipelineMedic

**Bounded, independently‑verified repair of e‑commerce data pipelines.**

PipelineMedic investigates failures in e‑commerce data pipelines (renamed
columns, changed date formats, replayed ingestion batches, and combinations of
these), proposes a *bounded* repair plan, executes it on a sandboxed copy, and
gates every change behind a separate Python verifier so an automated fix can
never silently corrupt valid data.

Team: **Siddhi Sandip Kakani**, **Bernice Mercy Sharon Malaiarasu**.

---

## What works today

- Clean pipeline + reporting over a reproducible 5,000‑order Olist sample.
- Fixed‑rule repair controller for rename / date / replay / combined faults.
- Bounded, sandboxed executor (raw inputs are never mutated).
- Independent six‑check verifier (schema, keys, foreign keys, record
  preservation, replay exclusion, report invariants).
- Live Claude CLI adapter returning strict‑JSON repair plans.
- 30‑scenario development pilot + hand‑built checker negative controls.
- 22/22 unit tests pass.

See `PipelineMedic_Progress_Report.pdf` for measured results.

---

## Requirements

- **Python 3.11+** (the bundled DuckDB binary in `.deps/` is built for CPython
  3.12 on macOS; use 3.12 to reuse it, or `pip install duckdb==1.5.6` for your
  own interpreter — see below).
- Only dependency: `duckdb==1.5.6` (`requirements.txt`).
- **Optional:** the `claude` CLI (for the live integration). Everything except
  `live-pilot` / `demo --agent` runs fully offline without it.

## Installation

```bash
cd pipelinemedic

# Option A — use your own Python and install DuckDB
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export PIPELINEMEDIC_PYTHON="$(command -v python)"

# Option B — reuse the bundled DuckDB in .deps/ with a CPython 3.12
export PIPELINEMEDIC_PYTHON=/path/to/python3.12   # must be 3.12 for .deps/
```

`run_local.sh` puts `.deps/` on `PYTHONPATH` and runs `python -m pipelinemedic`.
Set `PIPELINEMEDIC_PYTHON` to pick the interpreter.

## Exact commands

```bash
# 0. (only if data/ is missing) rebuild the 5,000-order sample from raw Olist CSVs
./run_local.sh prepare --source /path/to/olist_csvs --size 5000

# 1. Clean baseline — order count, payment total, late-delivery rate (verified)
./run_local.sh baseline

# 2. 30-scenario development pilot (unrepaired / fixed-rules / fixed-rules+verifier)
./run_local.sh evaluate

# 3. Checker negative controls — full verifier vs. weakened schema-only verifier
./run_local.sh checker-tests

# 4. Live Claude pilot (needs the claude CLI; makes real, budgeted API calls)
./run_local.sh live-pilot --max-cases 4

# 5. Run the test suite
PYTHONPATH="$PWD/.deps:$PWD" "$PIPELINEMEDIC_PYTHON" -m unittest discover -s tests

# 6. Regenerate the progress-report PDF from saved artifacts
"$PIPELINEMEDIC_PYTHON" make_report.py     # needs reportlab
```

### Simple demo

```bash
# Inject a replayed payment batch and repair it with fixed rules
./run_local.sh demo --fault replay

# Same, but ask Claude for the plan (needs the claude CLI)
./run_local.sh demo --fault replay --agent
```

The demo injects a fault, proposes a bounded plan, executes it on a copy, runs
the verifier, and writes `artifacts/demo.json` (plan, decision, metrics,
ingestion ledger). Fault choices: `rename`, `date`, `replay`, `combined`,
`ambiguous`.

## Modules

| File | Responsibility |
|------|----------------|
| `pipelinemedic/data.py` | Reproducible sampling, source contracts, CSV I/O, SHA‑256 fingerprints. |
| `pipelinemedic/core.py` | Fixed repair rules, plan validation, sandboxed execution, DuckDB reports, and the independent verifier (`full` and `schema_only`). |
| `pipelinemedic/agent.py` | Claude CLI adapter: sends only headers/contracts/date samples, enforces a JSON schema, disables tools/hooks/MCP, records cost & usage. |
| `pipelinemedic/scenarios.py` | Controlled fault injection (development pilot, **not** a held‑out benchmark). |
| `pipelinemedic/evaluate.py` | Pilot runner, gold scoring (isolated from runtime), checker challenges, live pilot. |
| `pipelinemedic/__main__.py` | CLI: `prepare`, `baseline`, `evaluate`, `checker-tests`, `live-pilot`, `demo`. |
| `tests/test_pipeline.py` | 22 unit tests. |
| `make_report.py` | Renders the 4‑page progress PDF from `artifacts/*.json`. |

### Outputs (`artifacts/`)

`baseline.json` / `baseline.duckdb`, `pilot_results.json`,
`checker_challenges.json`, `claude_pilot_results.json` + `claude_traces/`,
`demo.json`, and `evaluation_only/reference_metrics.json` (gold — **never** read
by the runtime agent or verifier).

## Limitations

- The 30 scenarios are a **development pilot**, not a genuinely held‑out
  benchmark; the held‑out evaluation is still to be built.
- The live Claude comparison is **4 smoke cases** and reuses one proposal for
  the paired run — preliminary, not a performance claim. On this set the
  fixed‑rule baseline currently outperforms the agent (it failed the `date`
  case by omitting ISO canonicalization; the verifier correctly rejected it).
- No monitoring **dashboard** yet.
- The bundled `.deps/` DuckDB is macOS / CPython‑3.12 specific; other platforms
  should `pip install duckdb==1.5.6`.
- Ambiguous dates with no documented source format are escalated to human
  review by design — they are not auto‑resolved.

## Safety / ethics

Repairs are limited to three auditable operations on a deep copy; the verifier
must confirm every valid source record and report total is preserved before a
candidate is promoted; ambiguous cases go to a human; the model sees no customer
rows and executes no code; failed live calls are recorded as failures, never
replaced with fabricated successes.

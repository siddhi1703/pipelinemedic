#!/bin/sh
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PROJECT_ROOT"
# Make the bundled DuckDB (if present) importable without installation.
export PYTHONPATH="$PROJECT_ROOT/.deps${PYTHONPATH:+:$PYTHONPATH}"

CODEX_PY="/Users/siddhisandipkakani/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"

# Pick the first interpreter that can actually import duckdb (either the bundled
# .deps copy via PYTHONPATH, or one where the user ran 'pip install duckdb').
RUNTIME_PYTHON=""
for cand in "${PIPELINEMEDIC_PYTHON:-}" "$CODEX_PY" python3.12 python3 python3.11; do
    [ -n "$cand" ] || continue
    if command -v "$cand" >/dev/null 2>&1 || [ -x "$cand" ]; then
        if "$cand" -c "import duckdb" >/dev/null 2>&1; then
            RUNTIME_PYTHON="$cand"
            break
        fi
    fi
done

if [ -z "$RUNTIME_PYTHON" ]; then
    echo "run_local.sh: no Python with duckdb found." >&2
    echo "  Fix: 'pip install -r requirements.txt' and set PIPELINEMEDIC_PYTHON," >&2
    echo "  or point PIPELINEMEDIC_PYTHON at a CPython 3.12 (to reuse .deps/)." >&2
    RUNTIME_PYTHON="${PIPELINEMEDIC_PYTHON:-python3}"
fi

exec "$RUNTIME_PYTHON" -m pipelinemedic "$@"

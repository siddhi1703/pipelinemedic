#!/bin/sh
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PROJECT_ROOT"
RUNTIME_PYTHON="/Users/siddhisandipkakani/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ -n "${PIPELINEMEDIC_PYTHON:-}" ]; then
    RUNTIME_PYTHON="$PIPELINEMEDIC_PYTHON"
elif [ ! -x "$RUNTIME_PYTHON" ]; then
    RUNTIME_PYTHON=python3
fi
export PYTHONPATH="$PROJECT_ROOT/.deps${PYTHONPATH:+:$PYTHONPATH}"
exec "$RUNTIME_PYTHON" -m pipelinemedic "$@"

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077
ROOT="$PWD"
if [[ ! -x .venv/bin/python ]]; then echo "Run bash setup.sh first" >&2; exit 1; fi
CUDA_LIBS="$("$ROOT/.venv/bin/python" - <<'PY'
from pathlib import Path
import nvidia.cublas, nvidia.cudnn
print(f"{Path(nvidia.cublas.__path__[0]) / 'lib'}:{Path(nvidia.cudnn.__path__[0]) / 'lib'}")
PY
)"
export LD_LIBRARY_PATH="$CUDA_LIBS${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export HF_HOME="$ROOT/models"
export HF_HUB_DISABLE_TELEMETRY=1
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-2}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-2}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-2}"
export WHISPER_CPU_THREADS="${WHISPER_CPU_THREADS:-2}"
export WHISPER_COMPUTE_TYPE="${WHISPER_COMPUTE_TYPE:-int8_float16}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
PORT="${PORT:-17860}"
exec nice -n 10 "$ROOT/.venv/bin/python" -m uvicorn app:app --host 127.0.0.1 --port "$PORT" --workers 1

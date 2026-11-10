#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077
ROOT="$PWD"
mkdir -p .tools/bin .cache/uv .python models data
export UV_CACHE_DIR="$ROOT/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$ROOT/.python"
if [[ -x .tools/bin/uv ]]; then
 UV="$ROOT/.tools/bin/uv"
elif command -v uv >/dev/null 2>&1; then
 UV="$(command -v uv)"
else
 curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$ROOT/.tools/bin" sh
 UV="$ROOT/.tools/bin/uv"
fi
"$UV" venv --python 3.12 "$ROOT/.venv"
"$UV" pip install --python "$ROOT/.venv/bin/python" -r requirements.txt
chmod u+x run.sh
echo "Installed in project-only .venv. Run: ./run.sh"

#!/usr/bin/env bash
set -euo pipefail
# /opt is inside D:\WSL\CALC-Research\ext4.vhdx, not on the Windows C drive.
export UV_CACHE_DIR=/mnt/d/CALC-experiments/cache/uv
export PIP_CACHE_DIR=/mnt/d/CALC-experiments/cache/pip
export HF_HOME=/mnt/d/CALC-experiments/cache/hf
export UV_PYTHON_INSTALL_DIR=/opt/calc/python
export UV_LINK_MODE=copy
export PYTHONDONTWRITEBYTECODE=1
export TMPDIR=/opt/calc/tmp/clm
mkdir -p "$TMPDIR" /opt/calc/envs
/opt/calc/tools/uv venv --python 3.12 /opt/calc/envs/clm
# Reuse the fully downloaded author dependencies; no new packages/model requests.
/opt/calc/tools/uv pip install --offline --python /opt/calc/envs/clm/bin/python -e /mnt/d/CALC-experiments/upstreams/CLM pytest

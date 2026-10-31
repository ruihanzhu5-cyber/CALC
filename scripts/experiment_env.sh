#!/usr/bin/env bash
# This WSL distribution's VHD and all mounted experiment paths are on D:.
export CALC_EXPERIMENT_ROOT=/mnt/d/CALC-experiments
export PATH="/opt/calc/tools:/opt/calc/envs/calc/bin:$PATH"
export UV_CACHE_DIR=/opt/calc/cache/uv
export UV_PYTHON_INSTALL_DIR=/opt/calc/python
export UV_LINK_MODE=copy
export PIP_CACHE_DIR="$CALC_EXPERIMENT_ROOT/cache/pip-linux"
export HF_HOME="$CALC_EXPERIMENT_ROOT/cache/hf"
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_DISABLE_XET=1
export TMPDIR="$CALC_EXPERIMENT_ROOT/tmp"
export NO_PROXY="localhost,127.0.0.1,::1,host.docker.internal"
export no_proxy="$NO_PROXY"

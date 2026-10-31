#!/usr/bin/env bash
set -euo pipefail
ROOT="${CALC_EXP_ROOT:-/mnt/d/CALC-experiments}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export UV_CACHE_DIR="$ROOT/cache/uv-linux"
export HF_HOME="$ROOT/cache/hf"
export HF_HUB_CACHE="$ROOT/cache/hf/hub"
export HF_HUB_DISABLE_XET=1
export TMPDIR="$ROOT/tmp"
export TOKENIZERS_PARALLELISM=false
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
# Pyserini eagerly constructs its unused OpenAI encoder client on import.
# BM25 never calls it; supply a non-secret placeholder and unreachable endpoint.
export OPENAI_API_KEY=unused-bm25-no-api-calls
export OPENAI_BASE_URL=http://127.0.0.1:9/v1
SOURCE_ROOT="${BCP_SOURCE_ROOT:-/opt/calc/upstreams/BrowseComp-Plus}"
exec "${BCP_PYTHON:-/opt/calc/envs/bcp/bin/python}" "$SCRIPT_DIR/service.py" \
  --source-root "$SOURCE_ROOT" \
  --index-path "$ROOT/bench/browsecomp-plus/indexes/bm25" \
  --cache-dir "$ROOT/cache/hf" \
  --tokenizer-revision c1899de289a04d12100db370d81485cdf75e47ca \
  --host 0.0.0.0 --port 8765

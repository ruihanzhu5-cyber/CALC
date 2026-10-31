#!/usr/bin/env bash
set -eu
source /mnt/d/CALC-experiments/code/CALC/scripts/experiment_env.sh
if curl --noproxy '*' -fsS http://127.0.0.1:8767/health >/dev/null 2>&1; then
  echo 'Model gateway already running'
  exit 0
fi
: "${DEEPSEEK_API_KEY:?Provider key must be forwarded for gateway startup only}"
: "${CALC_GATEWAY_KEY:?Local authentication key is required}"
nohup python -m calc.adapters.model_gateway \
  --log-dir "$CALC_EXPERIMENT_ROOT/runs/model-calls" \
  --host 127.0.0.1 --port 8767 --token-limit "${CALC_TOKEN_LIMIT:-160000}" \
  --concurrency "${CALC_MODEL_CONCURRENCY:-1}" \
  > "$CALC_EXPERIMENT_ROOT/logs/model-gateway.log" 2>&1 < /dev/null &
echo "$!" > "$CALC_EXPERIMENT_ROOT/logs/model-gateway.pid"
for _ in $(seq 1 30); do
  if curl --noproxy '*' -fsS http://127.0.0.1:8767/health; then
    echo
    exit 0
  fi
  sleep 0.5
done
echo 'Model gateway did not become healthy; inspect logs/model-gateway.log' >&2
exit 1

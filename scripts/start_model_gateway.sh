#!/usr/bin/env bash
set -eu
source /mnt/d/CALC-experiments/code/CALC/scripts/experiment_env.sh
if curl --noproxy '*' -fsS http://127.0.0.1:8767/health >/dev/null 2>&1; then
  echo 'Model gateway already running'
  exit 0
fi
: "${DEEPSEEK_API_KEY:?Provider key must be forwarded for gateway startup only}"
: "${CALC_GATEWAY_KEY:?Local authentication key is required}"
extra=()
if [[ "${CALC_NATIVE_SETTINGS:-0}" == "1" ]]; then extra+=(--native-settings); fi
command=(python -m calc.adapters.model_gateway \
  --log-dir "$CALC_EXPERIMENT_ROOT/runs/model-calls" \
  --host 127.0.0.1 --port 8767 --token-limit "${CALC_TOKEN_LIMIT:-160000}" \
  --concurrency "${CALC_MODEL_CONCURRENCY:-1}" \
  --max-output-tokens "${CALC_MAX_OUTPUT_TOKENS:-4096}" \
  "${extra[@]}")
if [[ "${CALC_SYSTEMD:-0}" == "1" ]]; then
  systemd-run --unit=calc-model-gateway --collect \
    --setenv=DEEPSEEK_API_KEY --setenv=CALC_GATEWAY_KEY \
    --setenv=DEEPSEEK_BASE_URL --setenv=PATH --setenv=PYTHONPATH \
    --property=WorkingDirectory=/mnt/d/CALC-experiments/code/CALC \
    --property=StandardOutput=append:"$CALC_EXPERIMENT_ROOT/logs/model-gateway.log" \
    --property=StandardError=inherit "${command[@]}"
  systemctl show calc-model-gateway --property=MainPID --value > "$CALC_EXPERIMENT_ROOT/logs/model-gateway.pid"
else
  nohup "${command[@]}" > "$CALC_EXPERIMENT_ROOT/logs/model-gateway.log" 2>&1 < /dev/null &
  echo "$!" > "$CALC_EXPERIMENT_ROOT/logs/model-gateway.pid"
fi
for _ in $(seq 1 240); do
  if curl --noproxy '*' -fsS http://127.0.0.1:8767/health 2>/dev/null; then
    echo
    exit 0
  fi
  sleep 0.5
done
echo 'Model gateway did not become healthy; inspect logs/model-gateway.log' >&2
exit 1

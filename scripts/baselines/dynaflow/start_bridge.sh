#!/usr/bin/env bash
# Start only the local corpus tool bridge. No model or judge requests.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${CALC_PYTHON:-/opt/calc/envs/calc/bin/python}"
state_dir="${CALC_SERVICE_DIR:-/mnt/d/CALC-experiments/runs/services}"
upstream="${CALC_BCP_URL:-http://127.0.0.1:8765}"
mkdir -p -- "$state_dir"
pid_file="$state_dir/dynaflow-bridge.pid"
if [[ -f "$pid_file" ]]; then
  read -r service_pid < "$pid_file"
  if [[ "$service_pid" =~ ^[0-9]+$ ]] && kill -0 "$service_pid" 2>/dev/null; then
    if [[ -r "/proc/$service_pid/cmdline" ]] && tr '\0' ' ' < "/proc/$service_pid/cmdline" | grep -Fq "$script_dir/bridge.py"; then
      echo "DynaFlow tool bridge already running (PID $service_pid)."
      exit 0
    fi
    echo 'Saved PID belongs to a different process; no service was modified.' >&2
    exit 1
  fi
fi
if ss -lntH | awk '{print $4}' | grep -Eq '(^|:)8766$'; then
  echo 'Port 8766 is already occupied; no existing service was modified.' >&2
  exit 1
fi
export PYTHONDONTWRITEBYTECODE=1
nohup "$python_bin" "$script_dir/bridge.py" --upstream "$upstream" \
  --log "$state_dir/dynaflow-bridge-tools.jsonl" \
  > "$state_dir/dynaflow-bridge.stdout.log" 2>&1 < /dev/null &
service_pid=$!
printf '%s\n' "$service_pid" > "$pid_file"
echo "DynaFlow tool bridge started (PID $service_pid), loopback port 8766."

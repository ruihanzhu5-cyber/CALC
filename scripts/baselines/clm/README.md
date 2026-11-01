# Official CLM ZeroShot: D-drive preparation

Upstream pin: `483198229ab7b90c0eed4651306ab3b3505aaf50`.
Original source: https://github.com/facebookresearch/context-language-models .
The official `ClmAgent`, `ContextEnv`, editable context mirror, nudges,
rollback/retry and edit gate are used. No heuristic context compressor replaces them.

## Installed host environment
Python 3.12.13 and harbor==0.16.1, litellm, tiktoken and pyyaml are installed
under D:\CALC-experiments\envs\clm. Windows entry points can inspect the package.
Actual bash/Docker trials use the Linux venv at `/opt/calc/envs/clm` in
CALC-Research. This ext4 filesystem is physically on D:\\WSL\\CALC-Research,
so it satisfies the D-drive storage requirement while avoiding slow /mnt/d imports.
The earlier /mnt/d Linux install was interrupted during copying and is not the
runtime. The host Windows environment is not a Linux venv.

## Tool/task port
Add `CLM/calc_port` to PYTHONPATH, then:
```bash
python -m calc_clm_port.pack_tasks --tasks /path/to/public_queries.jsonl \
  --task-ids /path/to/frozen_ids.json --output /path/to/new_harbor_tasks
```
Only query_id and query are copied. Gold answers/qrels are not installed.
Every task contains native Harbor task.toml/instruction/environment/tests.
Inside the container:
- `search "query"` forwards POST /retrieve {query}.
- `get_document "DOCID"` forwards POST /document {docid}.
The common gateway, not this CLI, controls top10/snippet/reader caps.
No API credentials appear in the image, task or build arguments.
Default compose uses host networking in the dedicated Linux WSL distro so
`BCP_BASE_URL=http://127.0.0.1:8765` reaches its shared service.

The answer goes to /workspace/answer.txt. The local verifier exports the answer
and an empty Harbor reward map. It does not grade accuracy. Run the official BCP
judge outside the task; no local numeric correctness reward is fabricated.

## DeepSeek compatibility
Use `calc_clm_port.agent:DeepSeekClmAgent` with canonical deepseek-flash.
This subclass changes only model transport, not the author context algorithm.
It explicitly enables thinking/high, omits ineffective temperature, preserves
reasoning_content on real assistant messages, and projects edited synthetic
assistant text into attributed user context notes to avoid fabricating old
reasoning after author parse_back rebuilds a conversation.
Transport request/usage sidecars record these projections and unknown usage.
No credentials or request headers are logged. Normal metered runs use the common
host proxy with CALC_GATEWAY_KEY and per-task CLM_API_BASE; CLM does not need the
provider key. Only a deliberate direct api.deepseek.com configuration reads it.

Author cost_usd can be zero for an unknown gateway alias; it is not authoritative
billing. Use recorded provider usage and the common locked price table.
max_total_tokens is available as a between-request reported-token guard; it
can overshoot by one request and must be labelled soft unless a common outer
gateway enforces the exact task budget. lm_call_cap bounds model calls; context
edits still count as model calls even when native CLM marks them free task steps.

The author bcp config is context_budget_tokens=28672 with reserve=2048, so its
strict pre-request target is 26624. Report both figures. The token counter is
author tiktoken with response calibration, not an exact DeepSeek tokenizer.

## Run command (paid; not executed during preparation)
```bash
export CALC_GATEWAY_KEY # inherited local proxy token, never print/write it
export CLM_API_BASE=http://127.0.0.1:8767/v1/RUNID/QID
bash /mnt/d/CALC-experiments/upstreams/CLM/calc_port/run_clm_bcp.sh TASK_DIRECTORY
```
The prepared launcher uses native max_steps=500/lm_call_cap=100 as pilot values.
Override to the final common protocol before a comparison.
Docker daemon + Docker Compose v2 + the corpus gateway must be ready.
Native environment setup and model authentication have not been established
by a paid rollout in this preparation task.

## Verification status
Author context-string round-trip tests: 6 passed plus 11 subtests on Windows.
No model API request or correctness judge was called.

## Queue integration and source-only backup

The launcher locates this port beside itself; `CLM_RUNTIME_ROOT` defaults to
`/mnt/d/CALC-experiments/upstreams/CLM`, and `CLM_TRIALS_DIR` may set the output.
For every task, set `CLM_API_BASE=http://127.0.0.1:8767/v1/RUNID/QID`, inherit
`CALC_GATEWAY_KEY`, and pass the task directory plus a unique --trial-name.
The frozen first20 manifest has `tasks:[{query_id,directory},...]` in order.

Only calc_clm_port/*.py, tests/test_port.py, README and preparation/launch .sh
files belong in the main repository backup. Do not copy upstream author source,
environments, generated tasks, preflight_logs, trials, provider keys or data.

The host API client bypasses inherited HTTP proxy settings for the common local
metered endpoint (`httpx trust_env=False`). Direct provider configuration may
retain environment proxies. This prevents WSL proxy variables from rerouting
127.0.0.1:8767 outside the local runtime.

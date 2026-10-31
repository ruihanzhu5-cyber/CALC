# DynaFlow Base/Dynamic on the common BCP service

Environment preparation only, 2026-10-31. No model or judge calls have been made by this setup.

This directory contains only original CALC adapters, checks and documentation. Official DynaFlow source, node_modules, datasets, inputs, snapshots and model credentials must remain outside the CALC code repository. There are no repository-specific AGENTS instructions in this directory's ancestry as checked during integration.

`start_bridge.sh` starts the loopback tool bridge using `/opt/calc/envs/calc/bin/python`. It writes its PID, stdout and full tool audit under `D:\CALC-experiments\runs\services`. It refuses to replace another process or occupied port. `/health` checks only the local bridge and reports `upstream_check:not_requested`; `/ready` additionally checks the common BCP upstream and returns 503 while that service is unavailable. Neither endpoint invokes a model.

```sh
bash /mnt/d/CALC-experiments/code/CALC/scripts/baselines/dynaflow/start_bridge.sh
```

The shared queue at `scripts/run_first20.py` consumes the prepared `shards.json` command arrays. Every command explicitly selects the Linux Python and `/opt/calc/upstreams/DynaFlow/src`, so it does not fall back to Ubuntu's Python3.10. The common Windows `invoke_wsl_experiment.ps1` injects only `CALC_GATEWAY_KEY` into model clients; the real provider key remains in the gateway.

Official checkout: `https://github.com/amiya-special/Dynaflow`, commit `7451639d197ef844b4157cf40eadac68e9eba8ca`. This is the released portable inference runtime with an untrained main agent and a common API backbone. It is not a reproduction of the paper's trained Stage-1/Stage-2 checkpoint results.

## Prepared files

- `bridge.py`: standard-library HTTP bridge, listening on loopback port 8766. Accepts the author's `/execute` protocol and forwards `search(query)` to the common service's `POST /retrieve`, and `get_document(docid)` to `POST /document` on port 8765. Responses are preserved, including original document text and its `truncated` flag. It never reads a scoring file or calls a model. The common service applies top-10 search, 512-token snippets and 8192-token document limits.
- `prepare_inputs.py`: converts only `query_id` and `query` from JSONL into the author's native question JSON list and writes a credential-free explicit config. It does not start a run. Native task IDs are preserved.
- `inputs-first20`: generated from the common `first20.dev.jsonl`; 20 answer-free questions and an explicit `deepseek-flash` config. Max output 4096 and 1200s question deadline are preparation defaults to align before freezing a formal run. Thinking is enabled, effort high. No temperature/seed determinism claim is made.
- `test_bridge.py`: two local-fixture contract checks. They exercise real local HTTP request serialization, raw document retrieval, rejection of invalid/auth requests, audit records, input allowlisting, and the author's native DeepSeek request construction. These are not benchmark results.
- `prepare_shards.py`: creates and verifies one native immutable run per query, with both Main and worker API URLs set to `http://127.0.0.1:8767/v1/dynaflow/{qid}`. Preparation makes zero model calls. `shards-first20-gateway/shards.json` records each prepared run and its later execution command. These gateway shards are the executable preparation; the unsplit `inputs-first20` is only an input/config example with an `unassigned` endpoint.
- `offline_runtime_check.py`: runs the author's Docker engine with an explicit local callback fixture and records `offline_fixture_not_benchmark`; no API clients are instantiated.

Final executable prepared runs live at `D:\CALC-experiments\runs\dynaflow-flash-first20-prepared` (WSL `/mnt/d/CALC-experiments/runs/dynaflow-flash-first20-prepared`). All 20 native snapshots were generated and verified; no `run` command was executed. The earlier checkout-local `shards-first20-gateway` is an interrupted slow preparation and must not be launched.

## Installed on Windows, all new data on D:

- Python venv: `D:\CALC-experiments\envs\dynaflow-host` (editable official package; no external Python runtime dependencies).
- Node 24.14.0 already present. `npm ci --ignore-scripts` and `npm run build` succeeded in `workflow_runtime`; pinned ajv/zod installed and generated engine/tool JSON present.
- npm/pip caches: `D:\CALC-experiments\envs\cache`; TEMP/TMP: `D:\CALC-experiments\envs\tmp`.
- No native research tool image, Tavily/Exa/Jina service, scientific Python requirements, or trained checkpoints are needed for this corpus-only tool bridge.

## Linux execution plan

The official engine hard-requires Linux Docker and runs its Node container with networking disabled. Python handles model HTTP and external tool RPC outside the container. With the D-backed `CALC-Research` WSL Docker Engine, execute DynaFlow Python and this bridge inside the same WSL distribution. This avoids Windows Docker contexts and Windows-to-Linux bind-mount conversion. Ubuntu22's system Python3.10 is below the declared Python>=3.11 requirement; use the common Linux Python>=3.11 environment. No Linux npm reinstall is needed: the dependency graph is pure JS and can be reused under `/mnt/d`.

For actual execution use the ext4 copy `/opt/calc/upstreams/DynaFlow`, which is inside `D:\WSL\CALC-Research`'s VHD. The original Windows checkout remains the source backup. Set `PYTHONPATH=/opt/calc/upstreams/DynaFlow/src` with `/mnt/d/CALC-experiments/envs/calc-linux/bin/python` (Python3.12.16). The required Docker image `node:24.14.0-bookworm-slim` was pulled successfully, digest `sha256:d8e448a56fc63242f70026718378bd4b00f8c82e78d20eefb199224a4d8e33d8`. Do not build `dynaflow-tools:py311-v1` for this external-tool configuration. Native Docker/Node/RPC passed a zero-model fixture check; Windows-to-WSL per-file filesystem access was slow, hence the ext4 working copy.

Run the bridge with Linux Python, after the common BCP service is reachable from that WSL:

```sh
python /mnt/d/CALC-experiments/upstreams/DynaFlow/calc_bcp/bridge.py \
  --upstream http://127.0.0.1:8765 \
  --log /mnt/d/CALC-experiments/upstreams/DynaFlow/calc_bcp/tools.jsonl
```

The optional `DYNAFLOW_TOOL_API_KEY` must match in DynaFlow Python and the bridge. It is read from environment and never printed or written by the bridge. Both Main and worker model requests authenticate to the local gateway using the random `CALC_GATEWAY_KEY` environment variable. The real DeepSeek key belongs only to the gateway process, never to DynaFlow clients. No credentials belong in JSON configuration.

Use the author's `prepare` command to freeze a run only after common budgets and concurrency are agreed; it makes no model calls:

```sh
python -m dynaflow prepare --mode dynamic \
  --questions /mnt/d/CALC-experiments/upstreams/DynaFlow/calc_bcp/inputs-first20/questions.json \
  --config /mnt/d/CALC-experiments/upstreams/DynaFlow/calc_bcp/inputs-first20/config.json \
  --out /mnt/d/CALC-experiments/upstreams/DynaFlow/calc_bcp/run-first20
```

Do not use `demo`/`--managed-tools` for this port: they configure native live-web providers and may summarize fetched pages through an extra model. The native `run` preflight calls the model with a diagnostic arithmetic task. It is not an offline environment check; count its diagnostic usage separately when eventually authorized to execute models.

## Fairness and logging details to settle before execution

The supplied config sets **question concurrency** to 1. Native **subagent concurrency** is a different control: every Main-generated `Workflow` call can provide `maxConcurrency`; default 3, maximum 16. The native config has no global single-worker hard cap, and separate Workflow invocations have separate semaphores. The common gateway enforces one active upstream model request, preserving native parallel workflow construction while queueing actual API execution. The gateway also enforces the common per-question 100-request/160k-token stop threshold and preserves requests, responses, raw usage and spans. This needs no changes to the author's algorithm or runtime. Do not claim native subagent scheduling itself is serial.

The native DeepSeek adapter correctly preserves assistant `reasoning_content` through tool rounds and sends `thinking={type:enabled}` / `reasoning_effort=high`; its OpenAI adapter strips reasoning fields and must not be substituted. `max_tokens=4096` includes reasoning and may yield incomplete responses; this needs the same sanity check and budget choice across all arms. `deepseek-flash` is the requested stable API alias, replacing the earlier retired `deepseek-v4-flash` alias; record the provider's actual response model/version in raw receipts.

The author's `calls/`, `token-usage.jsonl`, diagnostic usage, per-question `main-messages.json`, workflow `events.jsonl`/journal, and `tools.jsonl` remain the native source of truth. Bridge audit JSONL additionally preserves full tool requests/results with task IDs. Cached/reasoning token fields are contained in raw usage; do not sum these subcategories on top of prompt/completion totals. Official BCP result export/judging is a later integration step, not completed by this environment setup.

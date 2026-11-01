# Recovery of the interrupted native-settings pilot

- Previous attempt: `dev5-native-retry19-v2`; original six valid submissions remain unchanged.
- Linux persistent journal shows an orderly shutdown starting 2026-10-31 21:11:13 Asia/Shanghai. Initiator unknown; no OOM evidence established.
- The prior main/177 `completed` artifact contained raw DSML tool requests, not a final answer. Qwen evaluation is preserved (incorrect, no extracted answer). This is a protocol-based missing submission, so all 19 unfinished tasks remain eligible; correctness never selects retries.
- New attempt: `dev5-native-recovery19-v3`, 19 concurrent episodes, gateway 32 model requests. Original per-baseline native settings retained.
- Windows Task Scheduler owns the host process; a foreground WSL `systemd-run --wait` owns the actor service. No automatic paid restart.
- Shared CLM image built once, verified identical Dockerfile/tool hashes, pinned by local image ID, then supplied through Harbor's prebuilt-image configuration. Task instructions, tools, CPU/memory and model parameters unchanged.
- Main/CALC: a truncated model generation no longer forces early submission with tools removed; raw DSML tool protocol is rejected as an answer. Existing task-step limit and output size remain unchanged.
- Queue writes a heartbeat every 5 seconds and records scheduler PID and boot ID. On host interruption a separate interruption snapshot is written; original records preserved.
- All model calls from interrupted and recovery attempts remain in cost accounting; missing usage is unknown, never zero. This mixed conditional recovery is not a fresh paired SOTA comparison.
- Validation: 25 local tests passed; Ruff passed. Actual search/document and prebuilt-container connectivity checks run before any new model calls.

# Native POrchestra port to BrowseComp-Plus

`porchestra_bcp.py` imports the separately cloned original MainAgent,
DelegateTaskTool, ReActSubAgent, memory bus and session/revision protocol. It
adds only the BCP retrieval environment, final submission and output runner.
This ports POrchestra to BCP; it does not claim an original GAIA2 score.
The pinned commit is `371aef619aec6f2918690a2fbaf9bf797b3025d3`.

The tested environment is `/opt/calc/envs/porchestra`, with dependencies in
`requirements.lock.txt`. Source defaults to `/opt/calc/upstreams/POrchestra`.
No ARE or cloud-service dependency bundle is needed for this BCP port.

```bash
python porchestra_bcp.py --check  # native import + live retriever health; zero LLM requests
python -m pytest -q test_porchestra_bcp.py --disable-warnings
```

The native-class fixture uses scripted local responses and a local mock
retriever. It verifies delegate→search→revise→Main revise_task→get_document→
finish→complete preserves the same worker/attempt and advances revision0→1.

Real single-task execution requires `CALC_GATEWAY_KEY`, injected by the
repository's `scripts/invoke_wsl_experiment.ps1`. The runner receives no real
provider credential. All native model calls share the task-scoped cost proxy
`http://127.0.0.1:8767/v1/porchestra/{query_id}`.

```bash
python porchestra_bcp.py --query-id SELECTED_DEV_ID --model deepseek-flash \
  --max-main-decisions 100 --max-tool-calls 200 --max-subagent-steps 100
```

Choose one task explicitly; batches are not started implicitly. Task path
defaults to `$CALC_EXP_ROOT/bench/browsecomp-plus/tasks/first20.dev.jsonl` and
can be overridden with `--tasks`. EXP_ROOT defaults to the D experiment root,
not the source directory. Native attempts10/session30 remain recorded
defaults. Task-global retrieval count does not reset on worker replacement.
The native memory/compression policy is preserved and any resulting model
calls pass through the same proxy. The runner never reads scoring labels.

# POrchestra baseline and optional CALC–GAIA2 integration

CALC reuses the external POrchestra inference runtime. It does not vendor its
agent implementation or replace the official GAIA2 environment/evaluator.
The initial adapter keeps **one native active SubAgent session**. The default
`calc` agent uses CALC's executable heuristic `JointController`; this is a V0
method implementation, not a trained policy or a reproduced SOTA result.

## Source versions

`configs/baselines.lock.json` pins these upstream sources:

| Source | Commit | Use |
| --- | --- | --- |
| POrchestra | `371aef619aec6f2918690a2fbaf9bf797b3025d3` | Native inference baseline and GAIA2 interfaces |
| Context Language Models | `483198229ab7b90c0eed4651306ab3b3505aaf50` | Context-management reference; not yet a reproduced baseline |
| BrowseComp-Plus | `046949032b0328319cc9a02663a759ec601d9402` | Official task/retriever/evaluation code |

Download only the source checkouts with:

```bash
python scripts/bootstrap_baselines.py
python scripts/bootstrap_baselines.py --check
```

The destination defaults to ignored `.upstreams/`. This command never installs
packages, downloads benchmark/model data, or calls a model. `--check` is read-only
and performs no network calls. Existing dirty or unrelated checkouts are reported
instead of overwritten. To use a particular Git executable, pass `--git-bin`.
On Windows installations that need OpenSSL, add `--ssl-backend openssl`; this is
a per-command option and does not alter global Git settings or Linux defaults.

## First reproduce the native runtime

Use the pinned upstream [GAIA2 setup guide](https://github.com/XueyangFeng/POrchestra/blob/371aef619aec6f2918690a2fbaf9bf797b3025d3/GAIA2.md)
in a separate Python environment. The upstream runtime targets Python 3.13 and
pins ARE to `7946367413129784139e785ae4c351090002a0bb`, with
`integrations/are-compat.patch`. Bootstrap deliberately does not install or patch
ARE. Review this patch: it includes execution/validation changes, so adoption of
the author's environment does not automatically establish evaluator equivalence.

Once the upstream environment/configuration and official data are available, the
native entry point is:

```bash
# From the POrchestra checkout, using its separately prepared ARE interpreter:
workspace/are-env/bin/python bench_gaia2.py \
  --config config/benchmarks/porchestra_gaia2.yaml --dry-run
```

The dry-run resolves a command without launching scenarios or requesting models.
Native `porchestra` remains separately registered. The upstream release includes
inference code; the OPOD training pipeline/checkpoints are not treated as
available or reproduced by CALC.

## Register and run CALC in the ARE process

Both CALC `src/` and the POrchestra checkout must be importable in the prepared
ARE interpreter. For example, in Linux/WSL:

```bash
export PYTHONPATH="$PWD/src:$PWD/.upstreams/POrchestra${PYTHONPATH:+:$PYTHONPATH}"
python -m calc.adapters.porchestra check
python -m calc.adapters.porchestra --mode joint run -- \
  --agent calc --provider YOUR_PROVIDER --model YOUR_MODEL \
  --dataset /path/to/frozen/gaia2 --limit 1 run
```

Replace placeholders with your pinned ARE/provider configuration and official
dataset. The second command only checks optional imports. The last command is
the **actual ARE runner**, and will request the configured generation/judge APIs
when executed; it has not been launched as part of the offline checks here.
Remaining arguments are forwarded to the installed `are-benchmark` console entry
point. Use the flags supported by the pinned ARE version, including its judge,
output, model, time and step configuration. Keep `--mode` before `run` so it is
parsed by CALC rather than forwarded to ARE.

Python callers can instead call `register_calc_are_agent(control_mode="joint")`
before constructing ARE agents. Registration maps the new `calc` name to a CALC
subclass, while retaining the upstream `porchestra` and fair-ReAct names. No
upstream files are rewritten. Registration must run in the scenario's Python
process; process-based executors need the same registration in each child.
The supplied direct entry point is suitable for same-process/thread executors.

Supported control modes are `joint` (default), `independent`, `lifecycle`,
`context`, `fixed`, and the explicitly named `projection` integration ablation.
`CALC_CONTROL_MODE` selects the default if no argument is passed. A custom
`policy(state, native_proposal) -> Decision | None` can replace the V0 scorer.
`CALC_SLICE_STEPS` controls the native polling interval (default 3 tool steps);
the control/inspection overhead belongs in the measured full-system cost.

## Where the method executes

- Native `_main_decision()` supplies task/delegation proposals. At a live worker
  boundary, CALC's default JointController actually evaluates continuation versus
  work transfer together with recent/evidence context candidates. It does not
  merely rename the native policy.
- The controller's `continue` maps to native `revise_task` on the same session.
  Its selected packet replaces the supplied context view; native runtime/tool
  execution and its dynamic-event handling are reused.
- `transfer` moves only selected WorkItems. The source remains active if other
  work remains. `merge`/`retire` preserve the pending obligations and evidence
  under the recipient before releasing the native active session. They do not
  call the native whole-scenario `stop()` method.
- Native local `finish`/`stop` is ingested before the session is released.
  `finish` records locally completed work when no explicit unresolved items remain;
  `stop` retains unfinished work. The ordinary upstream finish signal is sufficient,
  so CALC does not impose a second completion approval loop. Overall task success
  remains the environment evaluator's separate result.
- `ProjectedMemory` changes the Main input renderer while retaining native
  memory storage. Native inspection records are copied into the evidence store,
  so replacing `format()` does not silently discard those observations.
- A real `LLMEngine.chat_completion()` wrapper projects worker input **before**
  the provider is called. It archives the original request and selects bounded
  evidence plus a recent-turn tail. It preserves mandatory system/tool
  instructions, multimodal attachments and complete native tool-call groups.
  Selection budget is not a hard bound on the total provider input.
- The internal `CALC__read_evidence` tool lists archived evidence IDs and reads
  bounded text slices. Raw observations omitted from a prompt remain accessible,
  rather than merely being stored somewhere the agent cannot retrieve. For
  controlled comparisons, expose the same archive/read capability to relevant
  baseline arms; do not attribute an extra retrieval interface to scheduling.

The core supports spawn/continue/transfer/merge/retire/resume/reassign. In this
one-active native integration, spawning new work uses upstream delegation;
continuation resumes the existing native session, and partial transfer does not
kill a worker with remaining work. Rehydrating an already released ARE session
and multiple simultaneous sessions are **not implemented**. The adapter does
not claim concurrent worker speedups or a complete dynamic-world snapshot/fork.
Unsupported cross-session continuation raises an explicit error.

## Validation performed and current boundary

Offline tests cover pending-work/evidence transfer, partial transfer, local versus
official completion, incremental contribution counters, true provider-boundary
projection, archive recall, native inspection preservation, tool-call integrity,
optional-dependency errors, registration defaults and actual JointController
transfer behavior using dependency substitutes. They do not establish GAIA2
task success or native ARE compatibility in a fully installed environment.

```bash
python -m pytest -q tests/test_porchestra.py
python scripts/bootstrap_baselines.py --check
```

At implementation time the three source checkouts match their locks. ARE and
POrchestra are not installed in the test interpreter, so `check` reports them
missing with exit code 2. The optional full ARE/native model loop is **not run**;
no paid models or judges were called. Next validation is a native official
development-scenario smoke in the prepared ARE environment, followed by the
same scenario with `--agent calc` and identical generation/judge/time budgets.

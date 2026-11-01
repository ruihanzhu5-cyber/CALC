# CALC V1: Model-Guided Fork–Fold Orchestration with Continuation Capsules

## Problem anchor

- Bottom-line problem: On complex multi-step tasks, jointly decide where unfinished work executes and what information it receives, improving the success–cost frontier of multi-agent systems.
- Must-solve bottleneck: Fixed teams and recency/new-document heuristics cannot judge semantic progress, the usefulness of an independent context, or the information needed to continue after an agent is folded or resumed.
- Non-goals: Build a new benchmark; move the paper back to security; claim that a new module name establishes novelty; claim SOTA before comparable measured results.
- Constraints: Existing BrowseComp-Plus and its official scoring protocol first; DeepSeek/GLM API access and several thousand trajectories; reuse the frozen corpus and existing baseline ports; preserve V0 and its results. No test answer enters the actor or policy-training features.
- Success condition: A model-driven executable system that produces real joint lifecycle/context decisions; subsequent paired official-score experiments show a better quality/cost frontier than strong recent baselines and isolate the contribution of joint decisions.

## Grounding and choice

Verified as of 2026-11-01: Anthropic's 2026-10-22 article recommends conditional folding and progressive disclosure; POrchestra (2026-10-09) supports proactive harness revisions; CLM (2026-09-29) gives models context-file control; DynaFlow v2 (2026-10-29) supports model-written workflows; DCA (EMNLP 2026) learns Worker observations; MAS-OS (Findings EMNLP 2026) couples scheduling and memory/context modules; HSC-Bench (2026-10-27) separates evidence recovery from correct continuation. These are ingredients and competitors, not reasons to abandon the direction.

Route A: Add an LLM critic to the old four candidate combinations every three steps. This preserves fixed initial workers and pays for a critic on arbitrary checkpoints.

Route B (selected): The task-solving Main model owns work placement as ordinary tool actions. Main may investigate directly, fork a scoped branch, advance/resume it, or fold it into Main. Each placement carries selected context and a continuation contract. Workers publish compact checkpoints during their existing task-solving calls. No separate always-on manager or critic.

## Dominant contribution

**Treat placement of unfinished work and its continuation context as one model action.** A fork specifies its goal, open obligations and selected evidence; a continuation adds information to a retained local state; a fold transfers a usable checkpoint, ownership and archive references. Continuation capsules are the supporting representation. Dynamic agents, boards, summaries and tool use individually are reused ideas. Compare the coupled policy with an otherwise identical decoupled policy; names do not establish novelty.

## Executable method

1. Main starts alone with corpus search/read, local evidence recall, workspace notes and lifecycle tools. Simple tasks can finish without a Worker.
2. `fork(goal, obligations, context_ids, rationale, steps)` creates a fresh branch and executes a model-chosen short quantum. No preassigned candidate/checker roles.
3. `advance(branch_id, instruction, context_ids, steps)` schedules that branch with its checkpoint, live tail and selected new information. Main can revise scope after proactive blockage reports.
4. Worker `checkpoint(summary, findings, open_questions, next_actions, evidence_ids)` publishes a continuation capsule and yields. Findings cite source IDs and exact quotes. Quote matching checks provenance only, not entailment/truth.
5. `fold(branch_id, context_ids)` compiles the receiving view before ownership changes, imports the capsule, archives the branch and retains its raw trace. Unfinished obligations remain explicit. A later advance may reopen it from the capsule.
6. `revise_context(evidence_ids, note_ids)` selects Main's active view. Input consists of task, compact work board, selected grounded notes and a bounded live tail. The archive is always recoverable. Packing enforces the model-selected view; it does not choose the semantic plan.
7. Notes retain supporting, contradicting and uncertain relations separately. A model's assertions are never relabeled as oracle-verified facts.
8. Record action/context pairs, branch lineage, ownership, actual API usage, repeated corpus operations and post-handoff rediscovery. Execution requires no additional online judge or full counterfactual rollout.

## Integration

Reuse the API client, source-versioned evidence, BC+ retriever, gateway usage and official result/judge protocol. Opt-in `mode=calc_v1` preserves V0/baselines. A new V1 runtime starts Main first and executes model-chosen Worker quanta synchronously. Arbitrary ordering, repeated resume, dynamic goals and folding are executable; async parallel speedup is not the first claim.

The model chooses whether/what to delegate, scope, quantum, context IDs, note content, fold/resume and answer. Runtime mechanics check source identity/quotes, ownership, atomic commits, serialization and resource ceilings. These are not fixed contribution-scoring rules.

## Learning

First implementation: the API model itself is an instruction-following orchestration policy, with no trained-weight claim. Prompt it to state the expected useful result, why separate context helps, remaining unknowns and receiver needs. Avoid an extra critic call per tool step.

Training target: **measured continuation utility**, not document count. Freeze a training-task checkpoint; evaluate at least two joint action/context alternatives with the same backbone/tools and continue to official-scored answers. Include no-change controls and repeated samples to measure continuation noise. Terminal success and actual incremental cost label the preference. Training, validation and held-out task IDs are disjoint.

API-only route: fit an optional CPU pairwise ranker and/or retrieve train-only action/context exemplars. Features include available state, action, context size, unmet obligations, local-history length and observed repetition. No answer strings, judge explanations or future trajectory information. Loss: log(1+exp(-y*w^T*(phi(s,a,c)-phi(s,a',c')))). Pairs must share a checkpoint and have actually measured outcomes. The delivery can include an honest format/trainer without inventing training data. A later open-weight orchestrator can distill the same preferences.

## Why promising against the baselines

- POrchestra: proactive revision is retained; Main's own direct investigation competes with independent contexts, and branches can be reused.
- CLM: a chosen context view explicitly changes who owns and executes unfinished work, with inspectable continuation checkpoints.
- DynaFlow: move work inside an existing branch to/from Main without replacing the whole workflow; distinguish common-backbone ports from trained released models.
- DCA/MAS-OS: study placement-changing context, including Main-inline work and live context retirement. Coupled-vs-decoupled control is the decisive test, not a claim that those papers never combine scheduling/context.

## Three core validation blocks

1. Official BC+ success/cost frontier on frozen tasks/backbone: Main, V0, POrchestra, CLM, DynaFlow and nearest feasible DCA/MAS-OS comparisons. Count every policy/Worker/repair call. Mixed retries are not fresh main results.
2. Same V1 runtime: joint action/context vs lifecycle-only standardized context vs context-only fixed schedule vs independently chosen lifecycle/context. Match tools, local recall and added policy calls.
3. Continuation slice on existing trajectories: at fixed checkpoints compare capsule, generic summary and recent transcript at matched visible input size. Measure terminal correctness, rediscovery and incremental tokens. This is a diagnostic of an existing benchmark, not a new benchmark contribution.

## Risks and checks

Self-reported novelty can be wrong: ground source references and train on measured terminal outcomes. Capsules can misstate sources: retain original quotes, uncertainty and recoverable traces; test correction/contradiction cases. Main can over-delegate: direct solving/reuse compete in the same action space and their overhead is measured. Offline tests demonstrate execution, not SOTA. No new trainable backbone or GPU training is required for the first API implementation.

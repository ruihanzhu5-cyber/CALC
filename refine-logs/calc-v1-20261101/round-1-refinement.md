# Round 1 refinement — interventions, rather than fixed teams

## Problem anchor

- Bottom-line problem: On complex multi-step tasks, jointly decide where unfinished work executes and what information it receives, improving the success–cost frontier of multi-agent systems.
- Must-solve bottleneck: Fixed teams and recency/new-document heuristics cannot judge semantic progress, the usefulness of an independent context, or the information needed to continue after an agent is folded or resumed.
- Non-goals: Build a new benchmark; move the paper back to security; claim that a new module name establishes novelty; claim SOTA before comparable measured results.
- Constraints: Existing BrowseComp-Plus and its official scoring protocol first; DeepSeek/GLM API access and several thousand trajectories; reuse the frozen corpus and existing baseline ports; preserve V0 and its results. No test answer enters the actor or policy-training features.
- Success condition: A model-driven executable system that produces real joint lifecycle/context decisions; subsequent paired official-score experiments show a better quality/cost frontier than strong recent baselines and isolate the contribution of joint decisions.

## Accepted steering

Use 分派, not a fixed allocation of roles. Main and Workers may both dispatch. Agent count is endogenous: no fixed roster and no max-agent-count parameter. Creation lineage, individual dispatch/return records, and work-dependency edges are different graphs; valid agent communication may contain cycles. The first experimental comparison is only **CLM vs CALC on BrowseComp-Plus with DeepSeek Flash**. The real design focus is when and under which conditions collaboration improves correctness and efficiency.

## Anchor and simplicity checks

The original bottleneck remains joint lifecycle/context adaptation. A distributed dispatcher does not change the problem, but making its tool palette bigger would not resolve the trigger problem. We therefore sharpen the dominant contribution to **continuation-value-triggered collaborative intervention**, conditioned on the receiver and supplied context. The continuation contract remains its one supporting representation. A permanent critic, a new benchmark, embedding-service dependencies and a separately trained large orchestration model are unnecessary in the first implementation.

## Mechanism grounded in the expanded review

ATM uses measurable telemetry and warmup thresholding, but role entropy alone is not intervention value. DyTopo supplies the need/offer representation for selecting a recipient; TacoMAS distinguishes local repair from structural edits; POrchestra gives workers a proactive request interface. VoS provides the crucial learning target: what changes if we intervene here rather than continue. CarryOn/HSC-Bench motivate representing what the receiver must do next, not only summarizing what the sender observed.

### 1. Signals describe a collaboration opportunity

At real tool-result or work-state events, cheaply maintain:

- `intent_entropy`: entropy over recent task-intent labels emitted by the solving model. Keep tool-category entropy as a separate diagnostic; on BC+ two tools do not identify role mixture well.
- `progress_rate`: recent transitions of explicitly recorded obligations and newly source-backed support/refutation. These are model-reported state changes, not oracle correctness.
- `repetition_rate`: repeated normalized corpus requests and already-seen evidence IDs.
- `blocked_fraction` / `dependency_unlock`: explicit unfinished work dependencies.
- `contradiction_count`: unresolved opposing source-linked claims, distinct from disagreement among agents repeating one source.
- `context_pressure`: active input estimate relative to the actual model window, plus the proposed packet size.
- candidate `need_offer_match`, `receiver_reuse`, and `handoff_size`: relevance and information-transfer cost for the specific recipient/action.

Signals do not hand-prescribe actions. High entropy with useful progress can justify continuing. Low entropy with repetitive search and no resolved constraint can justify a new approach.

### 2. A concrete intervention competes with continuing here

Main or a Worker emits a structured proposal during its ordinary solving call:

`{event, actor, action, source, target_or_new, return_to, work_ids, new_work, continuation_intent, context_ids, baseline_if_continue, expected_result, return_condition}`.

Actions include continue here, create a branch, reuse/advance a peer, independent verification, transfer work, fold a branch and resume archived work. There is no mandatory number of agents or predefined architecture menu. The result can be a star, hierarchy, chain or converging work graph according to the proposals actually executed.

The initial bootstrap is an explicitly uncalibrated model-guided policy. It must state why the proposed intervention helps *at this event* and what ordinary continuation would do; no rule silently turns entropy into a split. All calls, rejected requests, context-transfer costs and outcomes are logged.

The calibrated variant predicts the paired change in terminal correctness and incremental cost for an action/context proposal relative to same-checkpoint continuation:

`gain(s,a,c) = E[Y(a,c)-Y(continue) | observed prefix] - lambda * E[C(a,c)-C(continue) | observed prefix]`.

Choose the highest predicted positive gain, with the continue arm at zero. The quality/cost weight and any calibration threshold are fitted on held-out validation tasks. A gate without measured training data is never labeled trained or calibrated. The target is not a probability of failure, an agent's confidence, document count, or an LLM's self-assessed novelty.

### 3. Receiving action determines the context

A contract includes `recipient`, `continuation_intent`, `obligation_ids`, `required_evidence_ids`, `required_note_ids` and `return_condition`. Stable work-scope/versioned capsules preserve source quotes, failed leads, unresolved requirements and recoverable raw traces. A fresh verifier may need constraints and original sources without the sender's favored answer; an investigator resuming a lead may need its rejected candidates. Compile and validate this view before moving ownership. Save a frozen pre-intervention snapshot and actual post-intervention lineage.

`fork` creates a new subgoal and optional work dependencies. `transfer` moves ownership of existing work; it does not duplicate it. Each dispatch records caller and `return_to`; child results return to that caller, not automatically to Main. Existing peers can accept multiple work scopes without replacing old capsules. Only Main submits the benchmark's final answer.

### 4. What different trigger events permit

| Observed event | Candidate intervention to compare with continue | Why context must change |
|---|---|---|
| Independent unresolved leads, conflicting duties, large distinct evidence sets | Fork a scoped investigator | Give the new branch only its relevant constraints/sources, with explicit completion condition |
| Missing information matches an existing peer's findings | Reuse the peer or route a capsule | Carry the missing dependency and source references, rather than spawning a duplicate |
| Opposing evidence affects a decisive answer constraint | Independent verification | Supply the disputed constraint and underlying sources; avoid forcing agreement with a prior conclusion |
| A branch repeats work or has completed its useful part | Fold/transfer | Move remaining obligations plus usable evidence; keep the raw trace recoverable |
| New evidence unlocks or invalidates an archived line | Resume/revise | Restore that work scope's latest capsule, changed assumptions and new evidence |
| Current context is making useful progress and handoff adds overhead | Continue locally | No team change; progressive local recall remains available |

This is a candidate-generation interpretation, not a hard-coded event→action policy.

## Training and first experiments

First reproduce one **zero-shot CLM common-backbone port on BC+** using public native settings and official scoring. Preserve that baseline runtime. Collect real training prefixes under frozen tasks/backbone; make continued and joint-action/context arms from the same snapshot and score their terminal answers. Include repeated continuations because single outcomes are noisy; retain actual incremental API usage and reject missing-usage labels for cost fitting. Never train from the current five development questions or evaluation answers.

The data has **two required state sources**: CLM prefixes provide direct-solver and fork opportunities; genuine multi-agent bootstrap executions provide actual peers, active/archived branches and work-scope capsules for reuse/fold/resume. Do not fabricate these states from single-agent traces. Sample both intervention requests and ordinary productive prefixes, so the learner observes negative/no-intervention examples rather than only already-failing trajectories.

The online candidate set is the current actor's actually generated feasible proposal(s), each including receiver/context/continuation intent, plus the unchanged-continue arm. It is not an oracle enumeration of all possible teams. For a paired training continuation, freeze the snapshot, model/tool protocol, judge protocol and **follow-up policy version**: only the first action/context intervention differs; both arms subsequently follow the same named bootstrap policy. Record candidate-generator and follow-up-policy commits with the sample. Repeat no-change controls to quantify API continuation noise; do not equate one paired binary difference with a proven individual causal effect.

An API-feasible calibrated trigger can be a small regularized CPU value model on these explicit features; its candidate set and actual execution point are now defined. Keep train-only continuation exemplars as a bootstrap policy artifact, not another independent claimed contribution. A later larger model can distill the same evidence. No claimed learned artifact exists until real paired outcomes have been collected.

First report CLM vs CALC official accuracy, tokens/cost and latency with all policies/workers/repairs counted. The three decisive diagnostics are: model/learned triggers vs fixed-period decisions; action-conditioned vs generic capsules in the same distributed runtime; and matched-input continuation from frozen checkpoints. A coupled-vs-independent control must hide destination/continuation intent from the independent context selector and count its natural calls; no dummy calls to create an illusion of equal cost.

## Implementation target and current boundary

Implement an opt-in V1 event/dispatch core and API solving policy behind the existing task/retriever/scorer interfaces. Preserve V0. Add a measured-pair training format and predictor with explicit untrained/bootstrap states. Tests must exercise both Main and Worker dispatch, task-driven topology, receiver-conditioned handoffs, original evidence provenance, no fixed roster, and zero invented outcome labels. No broad paid batch is authorized by this design document.

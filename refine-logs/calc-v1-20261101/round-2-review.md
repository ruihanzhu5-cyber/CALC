# Independent method review — CALC V1, round 2

Date: 2026-11-01
Reviewed full revision: round-1-refinement.md.
Grounding: docs/literature/CALC_V1_TRIGGER_REVIEW_20261101.md and primary sources checked in rounds 1/trigger review.
Reviewer: independent inherited Codex agent; no claim of the unavailable skill-named model.
Verdict: **REVISE**
Weighted overall: **8.80 / 10**
This is a near-ready method specification. Lack of experimental results is not the reason for revision.

<details>
<summary>Full raw reviewer response</summary>

## Assessment

The revision fixes the central weakness in round 1. Its dominant mechanism is now explicit: learn whether a specific change in executor and continuation context improves the terminal result and cost relative to continuing from the same state. Telemetry describes the state; model-originated proposals define executable interventions; a measured-outcome value gate chooses between a concrete intervention and continuation. This gives the API model and the local learner distinct jobs.

Distributed 分派, continuation contracts and emergent team structure remain supporting execution capabilities. They no longer compete as several disconnected contribution claims. Restricting the first experiment to CLM vs CALC on BrowseComp-Plus with DeepSeek Flash is appropriate.

The proposal is close to READY. Two operational specifications remain necessary: the training-state distribution must actually contain the multi-Agent states used by reuse/fold/resume, and paired continuation outcomes must hold the future execution policy fixed after the intervention. A third short clarification should make the candidate-set scope literal in the document. None requires a new benchmark or a large extra architecture.

## Scores

| Dimension | Score | Weight | Reason |
|---|---:|---:|---|
| Problem Fidelity | 9.5 | 15% | Correctness–efficiency remains the objective; the focus on when intervention helps addresses the original bottleneck. |
| Method Specificity | 9.0 | 25% | Event features, proposal schema, action-conditioned context, gate target and execution point are well specified. A replay contract needs one more paragraph. |
| Contribution Quality | 8.5 | 25% | A coherent mechanism connects trigger value to work placement and continuation context. Its distinguishing evidence is causally testable. |
| Frontier Leverage | 9.0 | 15% | Uses model semantics for task proposals and measured continuation outcomes for a small policy component, without an always-on LLM judge. |
| Feasibility | 8.0 | 10% | API/CPU route is feasible, but the written training recipe does not yet explicitly cover the multi-Agent state distribution. |
| Validation Focus | 8.5 | 5% | The first comparison is lean; the within-runtime trigger/context tests are the right causal controls. |
| Venue Readiness | 8.5 | 5% | A focused method paper can be built around this design, contingent on executing the specified controls and obtaining real outcomes. |
| **Weighted overall** | **8.80** | **100%** | **REVISE — near ready; complete the data/replay specification.** |

No dimension is below 7. The remaining requests are targeted method-completeness requirements, not a demand for results before implementation or an objection that ingredients appeared in earlier work.

## What was resolved

1. **Real coupling:** receiver, continuation intent, obligations and selected sources are now part of the intervention. Atomic receiving-view compilation and replay snapshots make the coupling inspectable.
2. **An actual trigger:** intent entropy, repetition, blockage and need–offer match are features rather than a hand-coded “high signal means spawn” table. The target is measured intervention-minus-continuation value.
3. **Learning integration:** the candidate proposal competes with continue at the execution point; the earlier empty ranker interface is replaced by a predictor with a defined control role.
4. **Model/learner honesty:** uncalibrated bootstrap and learned calibrated execution are explicitly distinguished. There is no implied trained artifact without measured data.
5. **Scope:** Main and Workers can 分派; the work graph and creation/return relations are distinguished; the first baseline is CLM alone rather than an expanding reproduction project.
6. **Cost integrity:** all actor, policy and repair calls count; missing-usage labels are excluded from cost fitting rather than filled with zero.

## Required revision 1 — train on the states where each intervention is legal

Priority: IMPORTANT; main remaining blocker.

The Training section starts with CLM and then says “collect real training prefixes.” Read literally, that could mean only single-Agent CLM histories. Such histories cannot teach the benefit of reusing a peer, folding a Worker, or resuming an archived context, because those states do not exist in an unchanged CLM run.

Add an explicit two-pool collection recipe:

- Pool A: frozen CLM training-task prefixes for local continuation versus creating a branch or independent verification.
- Pool B: frozen states from real executions of the uncalibrated distributed CALC bootstrap policy on the same training partition. Sample after actual child/peer 分派, before and after yields, and at genuine fold/resume opportunities.
- An arm is included only when its action is executable in that frozen state. Record legal-action coverage and sample all represented operations; do not manufacture peer state for a CLM prefix.
- Keep task IDs disjoint across training, validation and test. Every prefix/branch of a task stays in the same partition. The current five development questions remain excluded as specified.
- Train/calibrate on both successful and unsuccessful continuations. Add randomized or stratified arm selection with logged selection probability/eligibility so bootstrap preferences do not erase rejected but useful interventions.
- If the calibrated gate changes the encountered state distribution, collect a subsequent training-only rollout round under that gate or explicitly report the coverage limit. Do not use held-out results to repair it.

This is a concrete data-source requirement, not another trainable module.

## Required revision 2 — define what the paired continuation estimates

Priority: IMPORTANT.

The first action differs between arms, but the remainder of the trajectory also influences Y. The proposal should state which future policy both arms use. Otherwise different follow-up prompts, interventions or work schedules can be mistaken for the value of the initial action.

Introduce a minimal ReplaySpec:

- checkpoint fingerprint: task ID, public visible state, evidence/archive versions, work owners/dependencies, Agent contexts and branch checkpoints;
- backbone and decoding settings, corpus/tool versions and model/gateway identifiers;
- arm definition: exactly one initial proposal or no-intervention override;
- **one fixed followup_policy_id/version shared by both arms after that override**, initially the frozen bootstrap policy;
- isolated mutable state and output directories, with no newly discovered evidence leaking from one arm to the other;
- actual incremental model/tool accounting, independent official terminal scoring and repeated samples where affordable.

The estimand is then the value of that intervention **under the specified follow-up policy**. It is not an invariant causal benefit independent of all future decisions. After changing the deployed follow-up policy, validate calibration again or collect training-only updates. This limitation is normal and does not weaken the feasibility of the design.

## Short clarification 3 — literal candidate set and trigger timing

State the candidate set as:

D(s) = {continue} union {executable proposal(s) generated by the currently acting Agent at s}.

The predictor is evaluated immediately before a proposal would be committed. It can reject the proposal and keep the current continuation. With one proposal it is a learned execute/veto gate; with several proposals it can select among those proposals. It does not search every possible Agent architecture or guarantee a globally best intervention.

Clarify how tool-result events with no proposed structural action behave: update observable features and continue the current policy. If autonomous intervention proposals at those events are desired, specify that proposal-generation mechanism and count its API cost. Otherwise do not claim that the local gate can create a proposal the solving model never emitted.

This is entirely compatible with model-originated proactive events and avoids hidden controller calls.

## Source and novelty check

The revised mechanism uses VoS's central distinction between failure prediction and beneficial intervention, but its intervention tuple contains executor, work ownership and receiving context. Its contribution must be established by that continuation-level interaction and by the trigger/context controls; it should not be claimed as the first learned intervention-value idea. [VoS](https://arxiv.org/html/2610.09115)

POrchestra already supports proactive requests with scope/context revision, while DCA and MAS-OS already demonstrate that information selection and scheduling matter. The revised proposal correctly treats them as ingredients and neighbors. The proposed comparison can still be valuable: a request itself is not proof that executing it will improve the official result. [POrchestra](https://arxiv.org/html/2610.13485), [DCA](https://aclanthology.org/2026.emnlp-main.1785/), [MAS-OS](https://aclanthology.org/2026.findings-emnlp.1716/)

ATM's role-mixing telemetry and DyTopo's need–offer descriptors are useful observable families; the revision correctly avoids turning either into a universal action prescription. TacoMAS motivates separating local changes from slower structural changes. These similarities support the mechanism choices rather than disqualifying the project. [ATM](https://arxiv.org/html/2607.20488), [DyTopo](https://arxiv.org/html/2602.06039), [TacoMAS](https://arxiv.org/html/2605.09539)

## Simplification opportunities

1. Keep one proposal/continuation contract for Main and Workers. Store source, recipient, return target and required context in that same object.
2. For the first calibrated experiment, use one small value learner over a compact explicit feature set. Do not simultaneously add a second semantic critic, a separate ranker and an exemplar retriever.
3. Reuse the frozen follow-up bootstrap policy in paired collection. Defer policy-distillation stages until the first trigger can be measured.

## Modernization opportunities

The proposal is appropriately modern. The useful next improvement is outcome-grounded training-state coverage, not a larger model or another fashionable component. Make local CPU value inference the cheap event path; model calls remain for actual semantic task solving and the proposals it already produces.

## Drift warning

NONE. All latest steering fits the immutable anchor. No fixed Agent roster or architecture menu is needed. “No preset Agent count” need not mean unaccounted execution: retain benchmark execution limits and honest global call/cost records without forcing a particular team size.

## Verdict

**REVISE, 8.80/10.** Complete the multi-Agent training-pool and fixed-follow-up replay specification, and make the candidate-set scope explicit. After those changes the proposal can be re-evaluated for READY without requiring benchmark wins first. Continue implementation now; these changes sharpen data semantics and causal interpretation rather than postponing the system.

</details>


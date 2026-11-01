# Independent method review — CALC V1, round 3

Date: 2026-11-01
Reviewed: latest round-1-refinement.md, including the two newly added paragraphs under “Training and first experiments.”
Prior raw reviews remain unchanged.
Reviewer: independent inherited Codex agent.
Verdict: **READY for method implementation and initial validation**
Weighted overall: **9.09 / 10**
Scope: readiness of the method specification, not evidence of SOTA, statistical benefit or conference acceptance.

<details>
<summary>Full raw reviewer response</summary>

## Re-read verification

I re-read the revised Training section rather than treating the previous missing points as still absent. The latest text now explicitly requires:

1. CLM prefixes **and genuine multi-Agent bootstrap executions** as different training-state pools, with reuse/fold/resume drawn from actually existing peers, branches and work-scope capsules;
2. the online candidate set to be the current actor's actually generated feasible proposal(s), including receiver/context/intent, **plus unchanged continue**, rather than an oracle search over all possible teams;
3. both paired arms to share the same frozen bootstrap follow-up policy after their first differing action/context intervention, with generator/follow-up commits recorded and repeated no-change controls used to quantify continuation noise.

The text also samples ordinary productive prefixes, preserves missing-usage exclusions for cost fitting, and keeps training away from the current five development questions and held-out answers.

These changes resolve the substantive blockers in round 2. They are methodological improvements in data coverage and the meaning of the value target, so a higher score is justified independently of the request to reconsider the draft.

## Scores

| Dimension | Score | Weight | Rationale |
|---|---:|---:|---|
| Problem Fidelity | 9.50 | 15% | The original joint lifecycle/context efficiency problem is preserved, with terminal correctness explicitly retained. |
| Method Specificity | 9.25 | 25% | Event features, concrete proposals, pre-execution gate, receiving-view contract, state pools and paired-continuation semantics now form an implementable pipeline. |
| Contribution Quality | 8.75 | 25% | The contribution is focused: value-triggered movement of unfinished work conditioned on who continues and with what information. It is a falsifiable method interaction, not a renamed toolbox. |
| Frontier Leverage | 9.25 | 15% | Model semantics generate useful task/context proposals; a cheap learned component evaluates measured continuation advantage without an always-on judge. |
| Feasibility | 9.00 | 10% | The two state pools cover single- and multi-Agent interventions, while API trajectories and a CPU learner fit the stated resource route. |
| Validation Focus | 9.00 | 5% | CLM vs CALC is a disciplined first comparison, with within-runtime trigger and capsule tests isolating the mechanism. |
| Venue Readiness | 8.50 | 5% | A plausible strong paper thesis is now specified; its strength will depend on measured frontier improvements and causal ablations. |
| **Weighted overall** | **9.0875 → 9.09** | **100%** | **READY for implementation and initial validation.** |

No dimension is below 7. No unresolved method-level blocker remains.

## Why the main blockers are resolved

### Training coverage

The old draft could have trained every action on single-Agent CLM prefixes, leaving peer reuse and archived-branch actions unsupported. The explicit second pool now supplies genuine states where those actions are executable. The instruction not to fabricate these states is important. Productive-prefix sampling also gives the gate a chance to learn when continuing is better, instead of only learning “something was already wrong.”

Implementation should report the distribution and legal-action coverage of collected samples. Sparse coverage may later require more training data, but it is no longer an undefined data source.

### What the value function means

The fixed shared follow-up policy makes the label interpretable: it estimates the effect of the initial intervention under that specified continuation policy. Recording commits and isolating the branches makes the pairing reproducible. Repeated no-change controls address API sampling noise without pretending a single binary outcome identifies an individual causal effect.

If future gate deployment changes the state distribution or follow-up policy, recalibration and training-only collection may be needed. The current version has an adequate place for that later iteration; a universal policy-independent causal-value claim is unnecessary.

### Actual candidate choice

The documented set of real proposals plus continue supplies the missing selection point. A single proposal yields an execute/veto decision; multiple proposals permit selection among those proposals. It is appropriate to bound the claim to that set. The gate does not need to invent all possible architectures or replace the task-solving model.

On a tool-result event with no proposal, the cheap monitor updates state and the actor continues normally. If a later version adds an explicit proposal-generation call, its cost should remain visible. That is an implementation choice, not a missing mechanism in the current design.

## What is now particularly strong

1. **The trigger target matches the user's objective.** A signal that predicts failure need not predict beneficial intervention. The proposal supervises the relative terminal correctness and actual incremental cost of the intervention.
2. **Signals are informative without becoming hand-coded action rules.** Role-intent entropy, repetition, blockage, source conflicts and need–offer match describe the state. They do not force a split, a fixed team or a mandatory role.
3. **Context selection is operationally coupled.** The same work can require different source views for a fresh independent check, a returning investigator, or Main's synthesis. Stable obligations and action-conditioned receiving packets let that claim be tested.
4. **Main and Workers can both 分派.** Caller/return routing and work-scope capsules support meaningful multi-step team structures without making architecture diversity a reward.
5. **Bootstrap and calibrated operation are separated honestly.** The current model-guided system can be built and exercised, while a trained gate exists only after actual paired outcomes.
6. **The experiment scope is controlled.** A first CLM/BC+ comparison is sufficient to establish whether the implementation can work before expanding the baseline matrix.

## Remaining risks — empirical or implementation, not blockers

- The task-solving model may rarely propose the intervention that would help. Report proposal coverage and veto rates; a learned gate cannot recover candidates that were never generated.
- A model-reported obligation transition is not a correctness label. Preserve source provenance and use official terminal outcomes for trigger supervision.
- Small-data action-specific value estimates may be noisy. Fit and calibrate with task-grouped splits, report action coverage and no-change variability, and avoid claiming statistical guarantees from heuristic uncertainty intervals.
- Candidate construction, rejected proposals, extra memory operations and all model calls count toward the cost frontier.
- Existing work already contains proactive revisions, learned intervention value and dynamic information flow. The paper's distinguishing claim remains their measured interaction through placement-conditioned continuation. It is not an absolute first-in-literature claim for any one ingredient.
- A synchronous initial runtime can establish execution and token/correctness effects. Parallel latency gains require a separate actual backend and measurement.

None of these requires a new benchmark, an additional critic model or an immediate large-scale RL training stack.

## Simplification opportunities

NONE required for readiness. Keep the current one dominant trigger mechanism and one supporting continuation representation. The useful simplification is to resist adding another controller, an embedding service or a separate online contribution judge before the first measured comparison.

## Modernization opportunities

NONE required. The proposed use of generative semantics, outcome-grounded value learning and resumable context is appropriate. Subsequent improvements should be driven by measured candidate misses, calibration failures or handoff rediscovery, rather than by adding fashionable components.

## Drift warning

NONE. The immutable anchor is preserved. The latest focus on when an intervention helps sharpens the original joint-decision problem instead of replacing it with a safety or benchmark-construction project.

## Final verdict

**READY, 9.09/10, for implementation and initial validation.**

The revision is now specific enough to build and to generate evidence for or against its principal claim. This review does not certify that CALC outperforms CLM, that the gate is already trained, or that the paper is submission-ready. Those conclusions require the actual source-separated training, held-out official-score comparison and mechanism ablations already specified.

</details>


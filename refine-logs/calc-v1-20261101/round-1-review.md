# Independent method review — CALC V1, round 1

Date: 2026-11-01
Reviewed: PROBLEM_ANCHOR.md and round-0-initial-proposal.md.
Reviewer: independent inherited Codex agent; the skill's named model is unavailable, so no claim of that model's review is made.
Verdict: **REVISE**
Weighted overall: **7.85 / 10**
Scope: method design review, not a claim that the unmeasured system will outperform a baseline.

<details>
<summary>Full raw reviewer response</summary>

The selected route is promising and should be implemented. Main-first direct solving, resumable scoped branches and folding are a materially stronger V1 than the old fixed two-worker loop. The strongest potential paper is about **action-conditioned transfer of unfinished work**, with model-controlled placement and recoverable evidence. The proposal currently describes that ambition more precisely than it specifies the mechanism that makes it true.

| Dimension | Score | Weight | Assessment |
|---|---:|---:|---|
| Problem Fidelity | 9.0 | 15% | Directly addresses redundant execution and continuation loss while preserving the efficiency objective. |
| Method Specificity | 8.0 | 25% | Tools and integration path are concrete; obligation identity, receiver state and learning-to-inference connection need specification. |
| Contribution Quality | 6.5 | 25% | Joint serialization is not yet a demonstrated mechanism-level coupling; make the capsule depend on the recipient's next useful action. |
| Frontier Leverage | 8.5 | 15% | A task-solving model choosing its own work placement is appropriate; avoids a needless always-on critic. |
| Feasibility | 8.5 | 10% | API-first implementation is feasible; the optional training routes need one committed first target rather than alternatives. |
| Validation Focus | 8.5 | 5% | Three validation blocks are enough; design the coupled/decoupled contrast so call-count changes do not become the only difference. |
| Venue Readiness | 6.5 | 5% | Strong engineering direction, but paper identity still depends on a sharper causal mechanism and operationalized comparison. |
| **Overall** | **7.85** | **100%** | **REVISE; preserve the direction, sharpen the mechanism.** |

### Source-grounded comparison

POrchestra explicitly allows a Worker to pause, report status/request/evidence, revise scope/context/tools and continue with local execution state. Thus continuation and context revision themselves are established ingredients. CALC can distinguish itself through choosing Main-inline execution as an alternative and through recipient-specific work transfer rather than merely adding another communication verb. [POrchestra, section 3.2](https://arxiv.org/html/2610.13485)

CLM allows model-controlled context editing, multiple context files and agent creation/termination through file operations. A fixed capsule format is not automatically more capable. Its value must be a better continuation interface: preserve what the chosen next action requires while allowing raw recovery, and test that change under the same model and visible input size. [Context Language Models, section 4.1](https://arxiv.org/html/2609.37725)

DynaFlow already puts workflow generation into the task-solving Main policy and carries intermediate outputs into subsequent coordination. Its described execution restricts Main to coordination after a workflow starts. CALC's persistent local branches, return to Main's substantive work and targeted retirement create a useful, testable execution difference. Avoid saying DynaFlow only makes one static upfront plan. [DynaFlow v2, section 3.1](https://arxiv.org/html/2610.34467)

DCA controls Worker observations for a fixed-role concurrent team. MAS-OS has memory management, scheduling and task-relevant context allocation. They make generic “we combine lifecycle and memory” positioning insufficient, but they do not invalidate placement-changing continuation as a focal contribution. Compare what changes an obligation's owner, what the new owner receives and which next action becomes possible. [DCA](https://aclanthology.org/2026.emnlp-main.1785/), [MAS-OS](https://aclanthology.org/2026.findings-emnlp.1716/)

Anthropic's October 22 report supports keeping separate contexts when they buy isolation or independent parallel work and folding other work into a shared loop with progressive disclosure. Treat this as an engineering hypothesis source, not controlled evidence of the proposed adaptive policy's advantage. [Anthropic, October 22](https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop)

### CRITICAL fix: make coupling operational

Weakness: an API with action and context_ids in the same JSON object can reproduce independently chosen lifecycle and context decisions. The current summary/open-question capsule could be used unchanged for every destination, so “joint” is partly an interface description.

Concrete fix: represent a decision as d = (placement, recipient, obligation_ids, continuation_intent, evidence_ids, note_ids, local_view). An obligation has a stable ID, current status, owner, supporting/refuting references and outstanding constraints. A capsule declares the **requested next action** and its dependency references. For example, continuing a search branch needs its rejected candidates and unanswered constraint; folding into Main needs the discriminating evidence, the unresolved comparison and ownership of the remaining verification. Those views can differ even with the same transcript and input size.

Implementation point: compile this destination/intent-specific view before ownership changes. Preserve the old context if required references cannot fit. Save pre-commit state, action, selected view and post-commit state for replay. Do not build a separate online critic just to certify the capsule. The receiver's next ordinary response/tool action can report missing dependencies or fetch them through the existing archive.

This strengthens Contribution Quality by making a concrete decision/context interaction inspectable. It also supplies the intervention needed to test the main claim.

### IMPORTANT fix: choose one learning deployment

Weakness: “optional ranker and/or exemplars” does not say how an action changes once preference data exists. If the Main emits a single action, a ranker has no alternatives to rank. If a new selector is added later, the method changes after data collection.

Concrete fix: commit the immediate V1 to a prompted generative Main policy and state that its weights are frozen. Record eligible action/context examples and outcomes now. For the first trained extension choose one route: train-only exemplar retrieval into that same policy is the least invasive API route; a ranker requires an explicitly bounded candidate set and a specified selection point. Do not present an untrained ranker interface as an implemented learned controller.

Training pairs need the same actual state checkpoint and visible-prefix features, a no-intervention continuation, repeated outcome samples where affordable, and all cost-bearing continuation calls. Checkpoint grouping must include task, state version, model and tools. Model-estimated gain must never be mistaken for measured terminal gain.

### IMPORTANT fix: make the paper's causal contrast explicit

Weakness: a two-call independent controller may lose simply from its extra call, while a one-call joint controller may still reason in two independent stages. “Match added policy calls” is not enough to define either method.

Concrete fix: state exactly what context decisions may observe. In joint mode, placement and next-action intent condition evidence selection. In a same-call decoupled control, select a context view without the destination/intent and hold that view fixed while selecting placement. Keep the same archive, tools, prompts' substantive capabilities and total call allowance. Also report the natural two-call pipeline with its actual overhead, rather than disguising that overhead or adding dummy calls. At fixed handoff checkpoints, swap the action-conditioned capsule and a size-matched generic capsule while holding the continuation intent and receiver fixed. These two contrasts isolate the coupling with little additional experiment design.

### Why this can improve quality as well as cost

The plausible quality gain is not “more agents” or “newly found sources.” It is that an independent branch can test a competing hypothesis without inheriting Main's commitment, then deliver exactly the counterevidence and outstanding requirement Main needs. A folded branch can stop redundant exploration while its unresolved work remains executable; a resumed branch can keep useful search state. Preserve these cases in the prompt and replay trace. This is a strong efficiency story because it concerns the cost of useful continuation, not a shorter transcript by itself.

### Simplification opportunities

1. Use a single WorkCapsule/ContinuationDecision representation across fork, resume and fold; avoid separate memory-summary, transfer-note and controller-state modules.
2. Treat notes and evidence as two layers of one archive, retaining original sources while the model selects an active view. Do not add a separate semantic critic.
3. Keep synchronous model-selected quanta initially, as proposed. Parallel execution is a later backend feature, and should not be needed to establish the first claim.

### Modernization opportunities

1. Make the next intended action and its dependencies the input to context selection; model-generated generic summaries are too weak a target.
2. Use actual paired continuations to train the API policy's examples or one explicit selector. Collect semantically meaningful continuation labels, not new-document counts.

### Drift warning

NONE. Keep the immutable problem anchor. Requiring a new benchmark, a much larger model, a separate reward model or RL backbone training now would add scope without resolving the core coupling question.

### Final recommendation

Continue implementation. Before freezing the interface, add stable obligation identity and action-conditioned capsule compilation; freeze the one-call and natural two-call comparison; choose the first learned deployment path. The design can become a sharp method paper with these changes, but the current proposal is not yet at the READY >= 9 bar. This is a revision request about the missing mechanism, not a rejection because prior work contains some components.

</details>


# Steering review — decentralized 分派 and emergent team structure

Date: 2026-11-01
Status: interim design guidance for round 2; not a new full scored round.

## Anchor check

**No drift.** Allowing both Main and Workers to 分派 expands the policy's choice of actor and destination while preserving the original problem: select who executes unfinished work together with the context required for useful continuation. The paper should retain that one dominant contribution. Star/tree/chain/DAG outcomes are observable consequences of the policy, not four independent claimed innovations. Different questions may produce the same architecture.

## Minimum sufficient representation

Keep three distinct relations:

1. **Creation lineage:** immutable creator/parent links tell us how an Agent was introduced.
2. **Dispatch and return records:** a particular request identifies who 分派了什么给谁 and where its result must return.
3. **Work dependencies:** obligation-level depends_on links determine readiness.

Creator, current caller, context recipient and return recipient can differ. In particular, a reusable peer cannot have a permanent return destination derived from its original parent.

A dispatch record should include:

| Field | Meaning |
|---|---|
| dispatch_id | Stable ID for this invocation and its result |
| actor_id | Agent making this 分派 decision |
| target_id | New Agent or existing recipient |
| return_to | Caller by default; explicit model-selected target when supported |
| obligation_ids | Work that is created, scheduled or transferred |
| continuation_intent | What the receiver should do next |
| required_evidence_ids / required_note_ids | Dependencies selected for that intended action |
| prior_checkpoint_version | Exact continuation state used |
| status / result_capsule_id | Pending, yielded, completed or failed and the resulting capsule |

Agent state additionally retains creator and parent. Work state retains stable ID, owner, status, dependencies and unresolved constraints. Capsules should be versioned by obligation or work scope, rather than being one mutable “last summary” per Agent; otherwise an existing peer accepting unrelated work can overwrite the state of its earlier assignment.

## Minimal execution path

Use the same model-facing fork/advance/transfer/fold tools for Main and Workers. A recursive synchronous call stack is a sufficient first backend:

- Main 分派 to Worker B.
- B can do tool work, 分派 a subgoal to C, or transfer an existing obligation to a suitable peer.
- C checkpoints/yields; its result returns through that dispatch's return_to, normally B.
- B uses the result, continues, checkpoints or sends its result to Main.

Main and Workers share semantics; only the global final-answer submission endpoint needs to remain unique. A Worker's ordinary answer is a local result delivered to its caller, not a global benchmark submission.

Do not force the Agent message/transfer graph to be acyclic. A → B → A is an ordinary delegation-and-return path. A DAG constraint belongs on the graph of **unfulfilled work dependencies**. Otherwise valid resumption or peer reuse will be rejected as a “cycle.” Detect actual dependency deadlocks rather than prohibiting normal return paths.

A new child subgoal has a distinct obligation ID and can block a parent obligation through depends_on. A transfer moves the owner of an existing obligation atomically. Those operations should not be conflated; they have different implications for work duplication and completion.

## Coupling that should stay central

At each 分派, compile the destination- and intent-specific continuation view before ownership changes. A receiver that must eliminate candidate X needs its counterevidence and unresolved constraint, while a receiver checking candidate Y needs different evidence even from the same source transcript. Preserve the dependencies and explicitly record any missing/recoverable detail. No extra always-on critic is needed.

For example, Main → B → C does not imply that C's capsule is blindly forwarded to Main. C prepares the view B needs for its next action; B's later handoff to Main can select a different view for Main's decision. This makes context selection substantively depend on the actual 分派 path.

## Implementation tests that demonstrate the new capacity

1. A Worker creates a child; the child result reaches that Worker and is consumed before it returns to Main.
2. Two callers reuse one existing peer on different obligations without overwriting either continuation state.
3. A dependency chain remains executable after an intermediate Agent is folded and reopened.
4. Transfer changes one obligation's owner without silently marking it complete or duplicating execution.
5. A genuine unresolved work-dependency cycle is reported; ordinary A → B → A return traffic remains valid.
6. The same source state produces different receiving views for different continuation intents, with atomic failure if required references cannot be compiled.

These tests establish execution semantics. They do not establish statistical superiority over a baseline.

## Paper and measurement implications

Report realized creation, dispatch and work-dependency graphs separately. Derive topology from actual executed events rather than a model's self-description of its architecture. Team diversity can be measured descriptively; it should not become a reward for gratuitous complexity.

Retain the coupled-vs-decoupled control on the same decentralized runtime. Otherwise a gain could come solely from allowing Workers to 分派, rather than from the joint action/context mechanism. A useful initial contrast is decentralized runtime with destination-blind generic capsules versus the same runtime with action-conditioned capsules.

The API-only learning decision is clearer after removing the unintegrated ranker. Train-only 分派/continuation exemplars can improve the same generative policy. Keep them task-disjoint from evaluation, and use measured continuation outcomes when selecting exemplars.



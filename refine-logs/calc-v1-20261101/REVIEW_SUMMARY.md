# CALC V1 method review summary

Date: 2026-11-01. Three rounds. Full raw independent reviews are preserved in round-1/2/3-review.md. The unavailable skill-named reviewer model was not used or claimed; the inherited Codex secondary agent performed the review.

| Round | Overall | Verdict | Main issue / revision |
|---|---:|---|---|
| 1 | 7.85 | REVISE | A combined action/context JSON alone is syntactic coupling. Make the receiver's next action and stable obligations determine the capsule; define actual learning/selection and decoupled control. |
| 2 | 8.80 | REVISE | Focus improved to continuation-advantage triggering; explicitly specify genuine multi-Agent training states, the actual proposal+continue candidate set, and fixed follow-up policy in paired continuations. |
| 3 | 9.0875 | READY for implementation | Added all three specifications; no method-level blocking issue or problem drift. Real gains, calibration and candidate coverage remain empirical questions. |

User steering is incorporated: Main and Worker can both 分派; agent count and architecture are endogenous; no fixed/max-agent-number policy; focus on when/under what conditions to intervene; objective is both collaboration efficiency and terminal accuracy; first comparison only CLM+BrowseComp-Plus with DeepSeek Flash; ATM is one mechanism reference among many.

The strongest contribution is the joint action/receiver/context continuation-value target. Its support is an action-conditioned, work-scope/versioned continuation capsule. Telemetry is an input, not a manual high-entropy→spawn rule. Initial model-guided bootstrap and a genuinely trained/calibrated local gate are explicitly different stages.

Final proposal: FINAL_PROPOSAL.md. Expanded primary-source review: ../../docs/literature/CALC_V1_TRIGGER_REVIEW_20261101.md. Trigger-specific independent review: TRIGGER_MECHANISM_REVIEW.md.

Current boundary: method specification completed; V0 runtime preserved; no claim that V1 is implemented/trained, no paid benchmark launch, no SOTA or A-conference acceptance certification.

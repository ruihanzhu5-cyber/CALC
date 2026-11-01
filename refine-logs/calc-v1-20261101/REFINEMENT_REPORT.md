# Refinement report — CALC V1

The original V0 rule scorer is superseded in the proposed research route by a model-guided bootstrap and an outcome-trained continuation-advantage trigger. No runtime replacement is claimed in this document-only delivery.

Problem and bottom-line objective: see PROBLEM_ANCHOR.md. Clean final design: FINAL_PROPOSAL.md. Primary-source mechanisms: ../../docs/literature/CALC_V1_TRIGGER_REVIEW_20261101.md. Three rounds and exact scores: REVIEW_SUMMARY.md and score-history.md. Full raw reviews: round-1-review.md, round-2-review.md, round-3-review.md.

Implementation handoff: preserve existing V0/baselines; first protocol is zero-shot CLM common-backbone port vs CALC on BC+ and DeepSeek Flash. Build generic dispatcher shared by Main/Workers, state events, work-scope capsules, proposal+continue gate and official-score replay collection. Avoid an Agent-count policy limit. Bootstrap can collect genuine multi-Agent states; only actual paired terminal outcomes can train/calibrate the gate. Keep all prior results and costs separate.

Required next evidence: executable replay fidelity, real submission/official grading, independent-vs-joint context and fixed-period-vs-value trigger comparisons. No method score substitutes for these results.

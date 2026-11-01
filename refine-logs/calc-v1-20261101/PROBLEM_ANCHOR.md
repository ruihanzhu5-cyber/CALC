# Immutable problem anchor — CALC V1

- Bottom-line problem: On complex multi-step tasks, jointly decide where unfinished work executes and what information it receives, improving the success–cost frontier of multi-agent systems.
- Must-solve bottleneck: Fixed teams and recency/new-document heuristics cannot judge semantic progress, the usefulness of an independent context, or the information needed to continue after an agent is folded or resumed.
- Non-goals: Build a new benchmark; move the paper back to security; claim that a new module name establishes novelty; claim SOTA before comparable measured results.
- Constraints: Existing BrowseComp-Plus and its official scoring protocol first; DeepSeek/GLM API access and several thousand trajectories; reuse the frozen corpus and existing baseline ports; preserve V0 and its results. No test answer enters the actor or policy-training features.
- Success condition: A model-driven executable system that produces real joint lifecycle/context decisions; subsequent paired official-score experiments show a better quality/cost frontier than strong recent baselines and isolate the contribution of joint decisions.

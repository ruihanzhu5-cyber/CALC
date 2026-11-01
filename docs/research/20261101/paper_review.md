# When Sub-Agents Work in Parallel：CALC 设计证据笔记

核查日期：2026-11-01。仅阅读，不运行模型、不修改 CALC。

## 原文与身份

- 正确标题：*When Sub-Agents Work in Parallel: The Promises and Pitfalls of Dynamic Concurrency in Long-Horizon Coding Tasks*。
- Han Li、HanHaoNing Li、Ziqian Jiang、Yiling Lou；南京大学、中央财经大学、UIUC。
- arXiv:2610.10263v1，2026-10-07。核查来源为预印本，不宣称顶会接收。
- [论文全文](https://arxiv.org/html/2610.10263v1)
- [作者 artifact](https://github.com/schwerli/Concurrency-Failures-Trajectory-Artifact)

## 核心证据摘要

This is an empirical study, not a scheduling algorithm or theorem. Matched native Codex/GPT-5.4, Claude Code/Opus 5, and Kimi Code/K3 runs toggle concurrency while holding model, prompt, environment, and time budget fixed (§3). Its 354 tasks cover SWE-bench Verified, RepoZero, NL2Repo, ProgramBench, and LoopsBench; 2,124 executions result. Table 3 shows task-dependent tradeoffs: Claude task success changes from 83% to 59% on SWE-Verified, but 7.1% to 21.4% on LoopsBench. Aggregate token multipliers span 1.41–3.31 across agents; concurrency is slower in 14/15 agent–benchmark combinations. §5.1 observes more delegation on harder tasks but explicitly distinguishes difficulty from independent work; harder bottlenecks need not expose more parallelism. §5.2 connects individual asynchronous results versus batch joins to orchestration timing. Table 4 identifies ownership, join/takeover, handoff, and shared-state failures. §7 identifies complementary work, alternative attempts, and independent validation as beneficial mechanisms. §8 limits generalization to tested systems and acknowledges stochasticity without extensive repeated runs. It supports selective, progress-sensitive orchestration; it does not validate CALC’s merge/fold policy or prove harder tasks require more agents.

## 对 CALC 的独立设计推论（不是原文的方法）

1. **用可执行工作驱动展开，不能把难度直接当人数。** 一个任务可能很难，但剩余工作只有一个强依赖瓶颈。模型提出分派时应说明各接收者可以立即执行的下一步、依赖及读写边界，而不是填写抽象的“需要并行”。实验可以按难度分层；运行时不能读取 benchmark 难度标签。
2. **事件应表明决策条件变化。** 用“依赖解锁、关键结果返回、职责失败/阻塞、新冲突证据”触发拥有该职责的决策者。返回一个子结果即可继续相应工作，不必等待全体。普通工具结果不是组织调整事件。是否改变组织仍由模型判断，不能用次数阈值直接 fold。
3. **每次组织调整都需要接管合同。** merge/fold 应同时转移未完目标、验收条件、依赖、证据版本、已失败路线和下一步，接收者接受后再撤销源职责。后继依赖等待职责完成，而不只等待原 loop 终止。必要运行时约束保护接管原子性，不要求每个正常动作先通过一次状态汇报。

## 可以写进故事、必须再实验的区别

- 动机：固定并行偏好不能兼顾各种任务；运行时治理和信息交接与图的连接形式同样重要。
- 本项目待验证：同一任务内及时展开和收拢是否优于只调整通信拓扑；merge/fold 何时降低信息搬运及协调成本；局部事件是否减少不必要控制调用。
- 不宜直接断言：难度越大最优人数越多；所有长任务都受益；动态拓扑天然低效；接口修好便证明 CALC 方法优于 MANTA。

## 供主 Agent 继续核查的引用线索

原文 §8 引用 *Towards a Science of Scaling Agent Systems* (arXiv:2512.08296)、*Socio-technical congruence* (ESEM 2008)、*Proactive detection of collaboration conflicts* (ESEC/FSE 2011)。可进一步核查任务依赖与协调需求的关系；本笔记没有替这些未精读来源背书。

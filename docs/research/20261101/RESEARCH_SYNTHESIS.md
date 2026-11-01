# CALC：任务进展驱动的弹性协作——文献与接口设计依据

核查日期：2026-11-01（北京时间）。本轮只做文献/源码研究，不改 CALC，不运行付费实验。优先官方论文、作者代码及大团队技术报告；这是有范围的证据清单，不宣称穷尽所有论文。论文、工程经验、我们的推论分别标明。

## 1. 建议采用的研究故事

**任务执行会不断揭示新的独立工作、依赖、冲突和信息耦合；智能体团队应据此展开、重组和收拢独立执行循环，同时保留未完成职责和必要上下文。**

不同难度数据集上的表现差异可以是实验现象，但“难度越高，Agent 应越多”不宜成为机制假设。困难可能集中在一个串行瓶颈；较容易但包含多个独立对象的任务，也可能适合并行。需要分开考察：

- 难度：单 Agent 在固定模型、工具和资源条件下的完成能力。
- 可分解性：当前有哪些可独立推进的目标，不依赖未返回结果。
- 耦合程度：分支是否频繁交换上下文、访问或修改同一资源。
- 不确定性：是否需要独立核查，且核查能够改变后续动作。
- 任务进展：目标、依赖或执行者状态是否已经改变。

可用名称：**Task-Progress-Driven Elastic Collaboration**，中文“任务进展驱动的弹性多智能体协作”。CALC 项目名可以保留。

与自适应拓扑的关系：我们的运行过程也可以表示为时变图，不能声称数学上脱离拓扑。差别是主要优化对象：除了谁与谁通信，还明确控制**哪些职责需要独立 loop、何时接管、上下文放在哪里、迁移后谁继续执行**。自适应拓扑方法适合作为直接基线；不要把 MANTA 描述为只能固定人数或只能改边。

## 2. 最值得作为主线的大团队证据

| 优先级 | 工作、团队、年份 | 已核查内容 / 证据性质 | 对 CALC 的用途与边界 |
|---|---|---|---|
| P0 | Kim 等，**Towards a Science of Scaling Agent Systems**；Google Research / DeepMind / MIT；2025，v3 2026-04 | [v3 原文](https://arxiv.org/html/2512.08296v3)，260 配置、6 个基准，受控实证；§4–5 | 支持协作架构与任务结构匹配；不提供适用于 CALC 的在线最优人数函数。v3 的跨验证 R² 为 0.373 / ACI 0.413，不沿用旧博客的 180 配置、0.513；87% 是域内留出配置的架构选择，不能说任意新数据集预测87%。 |
| P0 | Tomašev、Franklin、Osindero，**Intelligent AI Delegation**；Google DeepMind；2026-02 | [原文](https://arxiv.org/html/2602.11865v1)，§4.3–4.5、§6；概念框架/预印本 | 分派应包含职责、约束和可验证完成；环境或内部状态变化可触发重分派；监控本身有成本。为事件与交接设计提供依据，未实证证明 CALC 的收益。无需把它的智能合约或市场机制搬进来。 |
| P0 | Diane Sarkis，**When to fold subagents into your main agent loop**；Anthropic；2026-10-22 | [报告](https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop)，工程经验；[配套代码](https://github.com/anthropics/single-agent-loop-kit) | 为上下文耦合时 merge、通过 skills/tools fold 提供方向。它讲的是评估驱动的系统迁移，不是已经实现任务内在线伸缩。这个差别正是可进一步研究的空间。 |
| P0 | Zhan 等，**Agensh: Scaling Organizational Intelligence to 1,024 Agents**；Microsoft Research；2026-09 | [原文](https://arxiv.org/html/2609.26781v1)，§2、附录B；系统实证/预印本；[代码](https://github.com/microsoft/Agensh) | 支持 Worker 自主认领、共享发现、异步协作。固定时限下更多并发在其困难编程任务上有益；不是等 Token 比较，不证明任意任务应增人。其 merge 是成果集成，不能当作我们的 loop fold。 |
| P1 | Fourney 等，**Magentic-One**；Microsoft Research AI Frontiers；2024 | [原文](https://www.microsoft.com/en-us/research/wp-content/uploads/2024/11/MagenticOne.pdf)，Task/Progress Ledger、外层重规划与内层执行；系统报告 | 借鉴区分任务事实、进度和执行选择；其固定专家阵容、每次响应后的控制调用不能直接变成我们的低开销事件策略。 |
| P1 | Cemri 等，**Why Do Multi-Agent LLM Systems Fail?**；UC Berkeley 团队；2025 | [v3 元数据和摘要](https://arxiv.org/abs/2503.13657)，MAST 的系统设计、协作错位、验证失效分类；失效分析 | 用于失败分类和接口审计，说明改提示或拓扑未必解决交接/完成语义；不是“用了多 Agent 就更差”的定律。 |
| P1 | **How we built our multi-agent research system**；Anthropic；2025-06 | [报告](https://www.anthropic.com/research/multi-agent-research-system)，并行独立调查和成本分析；工程实证 | 支持广度探索、多独立上下文的价值；与折回单 loop 报告共同形成“按协作需求选择”的两面证据。内部研究评测与我们的动态工具环境不同。 |
| P1 | **Writing effective tools for agents**；Anthropic；2025-09 | [报告](https://www.anthropic.com/research/writing-tools-for-agents)，工具边界、concise/detailed 返回、可行动错误；工程方法 | 接口要保留解决任务所需语义，并允许取详细信息。不能用短字符串预览替代完整可恢复证据，也不应该无差别常驻所有工具。 |

机构身份按原文核查。AWO 虽有 Microsoft Research 收录页面，原文作者单位是 EPFL，不能因此写成 Microsoft 团队。

## 3. 用户指定论文及直接相关方法

指定论文准确题名是 **When Sub-Agents Work in Parallel: The Promises and Pitfalls of Dynamic Concurrency in Long-Horizon Coding Tasks**，Li 等，南京大学 / 中央财经大学 / UIUC，2026-10-07 预印本。[论文](https://arxiv.org/html/2610.10263v1)

论文 Agent 与代码 Agent 分别完成核查，见本目录 `paper_review.md`、`code_review.md`。它最适合支持“并行收益取决于可独立工作与组织执行细节”，而非直接给 CALC 提供调度算法。作者 artifact 中的运行时生成工作流是研究对象，不能当作作者提供的通用调度器。

| 工作 | 核查来源与类别 | 应放在我们论文哪里 |
|---|---|---|
| **POrchestra / Proactive Agentic Orchestration**，Feng 等，RUC / CUHK-Shenzhen / BAAI，2026-10 | [原文](https://arxiv.org/html/2610.13485v1)，[代码](https://github.com/XueyangFeng/POrchestra)；执行机制与训练方法分开 | Worker 主动请求修订、携带证据并保持执行连续性最贴接口问题；公开实现主要单活跃子 Agent，不能当现成多分支 merge/fold。训练 OPOD 的结果不能归给未训练的 API 适配。 |
| **MANTA**，2026 | [原文](https://arxiv.org/html/2607.28527v1)，[代码](https://github.com/mao-code/MANTA)；动态拓扑直接基线 | 有任务条件规划、审计修复、扩展成员、上下文策略，并有检索收缩特例。我们的差异应落在任务内选择时机和职责/上下文接管的统一执行语义，不能声称它完全不收缩。 |
| **DynaFlow**，Liu 等，2026-10，v2 | [原文](https://arxiv.org/abs/2610.34467)，[代码](https://github.com/amiya-special/Dynaflow)；训练编排器生成自由代码工作流 | 支持信息流与执行进展是重要优化对象；我们选固定操作库、纯 API，不复制整套自由代码合成。Flash 适配不是其训练后的论文 SOTA。 |
| **AgentDropout**，Wang 等，ACL 2025 | [正式论文](https://aclanthology.org/2025.acl-long.1170/)，[代码](https://github.com/wangzx1219/AgentDropout)；节点/通信裁剪 | “减少 Agent 及通信”已有充分相关工作。需要进一步区分去掉讨论节点与真正迁移有状态、未完职责。当前仓库的 V2 与 ACL 版本须分开冻结。 |
| **AgentPrune / Cut the Crap**，2024 | [论文](https://arxiv.org/abs/2410.02506)，[代码](https://github.com/yanweiyue/AgentPrune)；通信图剪枝 | 为冗余通信提供对照；不能把重复访问次数直接当作可删边数，重新读取可能是必要验证。 |
| **AFlow**，Zhang 等，ICLR 2025 | [正式论文](https://openreview.net/pdf?id=z5uVAKwmjf)，[预印本](https://arxiv.org/abs/2410.10762)；代码工作流搜索 | 区分离线工作流优化与任务内伸缩；不是当前第一优先实现基线。 |
| **Optimizing Agentic Workflows using Meta-tools / AWO**，Abuzakuk 等，EPFL，2026 | [原文](https://arxiv.org/html/2601.22037v1)，含 AppWorld 与 VisualWebArena；轨迹驱动工具合并 | 可用于排查“看似协作开销其实是工具粒度不当”。若未来增加 composite tools，必须两方法一致并另做工具接口消融。 |

补充检索线索：ATM（[2607.20488](https://arxiv.org/abs/2607.20488)）、AdaptOrch（[2602.16873](https://arxiv.org/abs/2602.16873)）与主题相关，但本轮没有充分核查其完整实现/实验可靠性，不作为核心理论支柱，也不以标题相似就搬入其阈值和模块。

## 4. 真正的理论支点与它们的适用范围

**理性元推理：** Russell 与 Wefald 的 *Principles of Metareasoning*（Artificial Intelligence, 1991）把计算选择看作有成本的决策。作者[研究说明](https://people.eecs.berkeley.edu/~russell/research-bo.html)明确讨论用改善后续实际决策的期望价值选择计算步骤。它能支撑“组织调整也是计算，收益要扣除成本”，不能自动给出 LLM 自报收益可靠性保证。

**时间抽象 / Options：** Sutton、Precup、Singh 的 [Between MDPs and semi-MDPs](https://www.sciencedirect.com/science/article/pii/S0004370299000521)（Artificial Intelligence, 1999）允许策略持续多步，具有启动和终止条件。可以借它形式化持续执行的协作模式，而非每步重新选择。我们的 API 控制器无需因此训练；部分可观测任务也不能未经证明直接套其最优性结论。

据此，我们可以提出自己的研究目标（不是已证定理）：

\[
\max_\pi \mathbb{E}[S(\tau)]-\lambda\mathbb{E}[C_{\mathrm{all}}(\tau)]-\mu\mathbb{E}[T_{\mathrm{wall}}(\tau)].
\]

所有规划、状态报告、审批、迁移、重试均计入 C_all；迁移时间计入 T_wall，避免额外再加同一笔成本。成功率优先时也可采用成本最小、成功率不劣于参照的约束式目标。LLM 对潜在收益的解释只作为提议，不当作已校准价值估计。

## 5. 源码核查后应采用的接口契约

以下是结合来源与本地审计提出的 CALC 下一版设计，不是这些上游系统已经替我们实现。

### A. 观察与进度：一份事实，不做执行门禁

- 保留结构化工具数据和原始读取入口；若外部模型 API 要文本，在最后一层做明确 JSON 序列化，而非把任意对象先 str()。
- 状态更新与协作操作分开：`progress_delta` 表示已完成/未完成事实；`collaboration_proposal` 明确具体操作。业务改计划不再共用含糊的 `change` 标记。
- 普通结果回当前执行者，不因为它没写报告就阻止正常业务工具。职责所有权、在途迁移与真实工具参数校验仍由运行时执行。

### B. 事件与决策：相关变化才获得决策机会

- 通知键包括职责/执行实例/事件版本；没有新增状态或证据，不重复送达同一提议。
- 子任务完成、明确阻塞/失败、相关依赖变化、Worker 主动请求进入相关决策者的队列。
- 当前模型调用期间到达的消息排队，在安全边界交付；不对每个工具结果再开一次 Judge。
- 一个子结果到达，可以释放它对应的后继；不默认全体 join。需要完整集合才能核查的任务仍可显式 join。
- 模型在正常调用中选择继续、delegate(sequence/parallel/review_refine)、merge、fold；runtime 不以重复次数自动选择操作。

### C. 分派与收拢：以职责为单位，不只是改图

最小提议包含：当前目标和完成条件、已知依赖、可立即执行的下一步、来源/接收者、证据引用，以及继续当前方式与切换的预期差别。使用操作专属 schema，避免每次普通进度都填写一大份模板。

真正迁移时才要求完整 handoff：未完事项、进度、依赖、证据及版本、失败路线、技能与历史入口。接收者确认接管和来源停止职责在同一提交边界生效；在途模型输出带职责版本，过期工具不得再执行。整个 loop 迁移即可，不同时扩张为任意部分迁移框架。

### D. 按需上下文：必须改变真实请求

- 同一权威工作账本，避免 system 状态、消息报告、事件通知反复复制同样内容。
- 短摘要或证据索引附带原始结果入口；不能删掉下一步工具需要的真实 ID、参数或约束。
- 工具/skills 按需公开的效果要用实际 HTTP 输入快照验证，不能只因代码有 load_skill 就宣称上下文按需加载。

## 6. Anthropic kit 的实际可借鉴内容

已核查默认分支 `release`，commit **c43796287b83bec847db923f07131d1cc8de750d**，Apache-2.0。这是参考实现；README 明确列出只离线测试和未做真实模型运行的部分。

- [reference_loop/loop.py](https://github.com/anthropics/single-agent-loop-kit/blob/c43796287b83bec847db923f07131d1cc8de750d/reference_loop/loop.py)：`Tool` 含 writes/deferred；`_execute` 对非字符串结果 JSON 编码；技能与工具渐进公开；每个工具调用必须有对应结果。
- [subagent_response.schema.json](https://github.com/anthropics/single-agent-loop-kit/blob/c43796287b83bec847db923f07131d1cc8de750d/skill/templates/subagent_response.schema.json)：返回 conclusion/evidence/actions_taken/confidence/caveats，且 UI 事件独立。这是结果 schema，不够承载未完职责迁移，需我们扩展。
- [coupling_map.py](https://github.com/anthropics/single-agent-loop-kit/blob/c43796287b83bec847db923f07131d1cc8de750d/skill/scripts/coupling_map.py)：统计跨轨迹相邻调用与耦合，产生候选；不是任务内“达到阈值自动 merge”。

不照搬它的默认累计预算、额外 verifier 和全体 batch 等待。其“先并行读、再串行写”需要确认读写依赖，在共享动态环境中不能任意重排原请求。模型并发、工具调用并发、职责迁移是三个不同边界。

其他固定 commit 的 Magentic-One / ADK / Deep Agents 源码设计见 `lab_interfaces.md`。借鉴设计与直接复制源码分别记录；本轮没有把任何新上游代码复制进 CALC。

## 7. 可以形成自己贡献的三个部分

1. **协作需求状态。** 在任务进展中显式表示可独立推进的职责、依赖阻塞、上下文耦合和核查需求；Agent 数量是分派/收拢结果，不预先按数据集难度决定。
2. **事件触发的局部组织决策。** 对相关执行者提供稀疏决策机会；继续当前组织是合法选择，把决策成本本身纳入优化。
3. **带职责与上下文接管的双向伸缩。** 展开与收拢共用同一执行协议，确保减 Agent 后事情仍有人做、依赖仍能释放。merge/fold 的具体时机与收益是实验要回答的问题。

这些是研究设计主张，不是凭阅读已经确认独一无二。创新可以来自这些机制的统一与可验证收益，而不要求每个基础操作从未出现。

## 8. 最小实验如何证实故事

共同模型、工具可见性、原始结果读取、环境、任务 ID、输出限制、API 并发先对齐。先修接口再比较，不把先前 MANTA 适配问题包装为图拓扑缺陷。

对照保留：single；开始时选模式后固定；在线切换但无 merge/fold；full；外部基线 MANTA。静态组可从同一操作库选初始组织；动态组使用同一套执行器，避免无意增加工具能力。

最值得测的不是只看三套数据集难度，而是形成二维分层：**难度 × 可并行性/耦合程度**。基准标签用于离线分析，不能作为模型决策输入。训练/开发轨迹可用于选取可观测特征；测试答案与官方评分不得进入控制器。

| 研究问题 | 假设 | 观测指标 |
|---|---|---|
| 任务结构是否改变最佳组织？ | 高可分解任务更可能从展开受益；高耦合任务可能更适合共享 loop | 各层成功率/成本曲线，人数与结构分布；不是只报全局均值 |
| 同题进展中是否需要换组织？ | 新依赖、结果和冲突使初始组织过时 | 固定初始 vs 在线切换；事件→提议→实际执行时间线 |
| 收拢是否有独立价值？ | merge/fold 可减少重复上下文与等待，同时保持职责完成 | 无收拢 vs full；接管后真实工具、依赖释放、失败/恢复次数 |
| 事件化是否更省？ | 相关变化通知比高频强制报告减少控制负担 | 执行/控制/mixed 请求，输入输出 Token，墙钟，缺 usage |

可先继续 GAIA2 做动态目标/依赖诊断，WorkBench 做静态工具对照；若缺少可独立长分支，再考虑 BrowseComp-Plus 或编程基准。数据集选择依据任务结构与可复现性，不依据先看哪边失败后筛选。各环境真实分工是否发生要记录，否则无法证明动态协作贡献。

附：之前五题 CALC 全单 loop，MANTA 有表示压缩/输出截断/协议限制混杂，因而不是上述主张的确认实验。详见 [已有审计](../../runs/gaia2-adaptability5-flash-v1/POST_RUN_AUDIT.md)。

## 9. 下一次代码迭代顺序

1. 共同观察契约与往返测试：结构、必需字段、详细读取、最终模型输入快照。
2. 统一进度状态，删除报告门禁和 business/organization change 歧义。
3. 版本化事件队列、状态变化去重，继续原会话，不逐工具唤醒父节点。
4. 在现有固定操作库上验证真实接管、在途旧结果拒绝、依赖职责完成。
5. 冻结统一接口的小对照，先检查机制执行和失败原因，再扩大实验。

本轮交付的是这套有来源的设计依据；上述代码变更尚未实施，不暗示已接入。

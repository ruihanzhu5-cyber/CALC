# CALC V1：固定操作集合中的动态协作与循环收拢

状态：2026-11-01 方法框架。运行核心与 WorkBench 适配已实现并通过离线检查，真实模型效果尚未验证；实际范围见 CALC_V1_IMPLEMENTATION.md。本文件取代此前 FINAL_PROPOSAL.md 中必须学习增益预测器的路线；旧文档和审阅分数仅代表旧方案。

## 核心问题

在同一任务执行过程中，何时改变局部团队的协作方式、从固定集合中选择哪一种方式，以及哪些环节值得使用更强模型，才能提高正确率并降低协作开销？

固定的是可选择的模式及执行语义，不是整个任务的协作方式。模型不能发明新拓扑或自由改边；它可以在预定义模式间切换，并实例化任务、参与者和上下文。不同任务、不同阶段因此可以形成不同团队结构。

## 依据：10月22日工程报告及配套代码

上一版只列顺序、并行、核查，遗漏了用户指定报告的核心。这里补齐两种不同的改变：合并相互依赖的子 Agent；把独立子 Agent 的能力改为同一主循环按需使用的 skills/tools。保留子 Agent 并当作工具调用仍然存在独立上下文，不能称为折回同一 loop。

报告及 kit 的做法主要是离线评估、逐步迁移架构，不是已经提供了任务内自动切换算法。CALC 要研究的是把这些明确的执行操作用于在线决策；这是我们的扩展，不归为 Anthropic 已验证的结论。

## 固定协作形式与固定改变操作

固定候选集合的含义是：每种操作的执行语义预先实现，模型选择何时、对谁执行；不允许模型生成任意新控制图。区分当前执行形式与改变形式的动作，避免把 merge 当成一种永久拓扑。

| 当前执行形式 | 执行含义 |
|---|---|
| 同一 loop 执行 | 当前负责人自己规划、调用工具和继续推理；按需加载能力说明和资料，不为每种能力创建独立模型循环 |
| 顺序子任务 | 后续工作依赖前序结果，按任务依赖交接 |
| 并行子任务 | 不同子任务保留独立上下文，分别执行后返回调用者 |
| 独立核查—修正 | 在独立上下文中核查明确的证据/约束，返回问题，再执行修正 |

| 固定改变操作 | 改变什么 | 必须保留的执行区别 |
|---|---|---|
| keep / continue | 维持当前安排 | 不为变化而变化 |
| delegate / expand | 从当前 loop 分派独立子任务，按顺序、并行或核查模板执行 | 子 Agent 有独立上下文；可按工具接口调用 |
| merge | 将多个紧密耦合子 Agent 的未完职责归入一个执行者和一个 loop | 原来多个 loop 收敛为一个子 Agent loop；不要求并入 Main |
| fold | 将子 Agent 的剩余职责和所需能力收回调用者 loop | 关闭该工作范围的独立执行循环；调用者直接使用工具并处理结果 |

merge/fold 是逻辑职责、能力和继续上下文的变更，不融合模型权重或内部 KV cache。正常完成后返回成果也不等于 fold：fold 的关键是接收者实际接管剩余执行，或接管之后需要使用的能力。

“子 Agent 作为工具”是独立子任务的调用接口：传入结构化任务，返回证据和结论；它仍运行自己的模型 loop。不能仅把调用包装成工具就宣称消除了交接或循环开销。

任务内容、参与者数量、模型档位、上下文和切换时机随状态决定。人数不预设，调度并发限额不等于团队人数上限。Main 和 Worker 均可在自己的职责范围内分派或提议改变；Worker 的子分支可 fold 回该 Worker，无需一律回 Main。同一 loop 内并行调用多个检索工具仍是一个 Agent，与多个 Agent 的并行分支分开计量。

## 触发设计：判断独立循环是否仍值得存在

以下是提供给 API 决策的证据与备选，不是固定阈值触发器，也不是已经验证的最优规则。

| 观察到的状态 | 要比较的选择 |
|---|---|
| 出现可独立推进的缺口，或需要不受现有结论影响的核查 | 保持当前 loop，或分派独立上下文 |
| 多个子 Agent 反复读取相同资料、相互等待、反复询问彼此细节 | 维持分开执行，或 merge 成一个负责这些职责的子 Agent |
| 子 Agent 后续每一步都需要调用者掌握的信息，独立探索已无明显作用 | 保留子循环，或 fold 回调用者直接继续 |
| 共享 loop 的上下文混杂、工具选择或指令相互干扰 | 继续按需披露，或重新分派独立子任务 |
| 事实冲突影响最终答案 | 新建/复用独立核查者；核查结束后按未完职责决定返回或 fold |

决策中必须说明：原方案继续会做什么；改变后省掉哪些重复执行或交接；是否损失并行性或独立核查；接收者是否能拿到继续所需的证据。只在事件有新信息时重审，已拒绝的相同请求不在无变化状态下反复提交。

## 用户确认的过程例子

保留：线索不足时顺序调查 → 出现独立线索后并行 → 结论矛盾时针对冲突核查—修正 → 冲突消除后顺序整合。

补全可发生的局部变化：并行阶段 A、B 发现自己其实围绕同一实体反复互传资料，可 merge 成一个子 Agent；当该子 Agent 剩余工作需要 Main 持有的跨分支证据时，可 fold 回 Main，由 Main 在自己的 loop 直接读取原文并整合。另一个确有独立调查价值的分支可继续运行。不是每道题都必须经过所有操作。

## 运行闭环

1. 工具返回、分支结束、职责阻塞、关键证据冲突等事件更新共享任务状态。
2. 代码收集可观察信号：职责依赖、重复检索、证据覆盖、冲突来源、上下文压力。信号不能冒充正确性标签。
3. 当前 Agent 在正常 API 调用中提出继续或模式切换，指出具体工作范围、证据、预期收益和返回条件。
4. 涉及模式变更、关键冲突或最终答案的判断交给强模型；常规检索、读取和证据提取默认交给轻量模型。强模型判断可与 Main 的正常求解调用合并，不给每个工具步骤增加评审调用。
5. 强模型对比继续与切换，输出结构化决策；运行时仅验证模式合法性、依赖、职责归属及引用完整性，按固定模板执行。
6. 在安全检查点按操作和接收者编译继续上下文：职责、证据引用、冲突、失败路线、下一步及能力说明。先准备接收者的可执行视图，再原子变更职责并停用来源工作范围；保留原始档案和无关分支。工具在途时先收妥结果再迁移，避免重复执行。fold 后的后续工具原始结果直接回到接收者 loop，不再经原子 Agent 摘要转发。
7. 返回新证据后重新判断；最终答案仍由 Main 提交。

决策结构：`scope_id, event_refs, current_form, operation, target_form, source_agents, receiver, reason_to_change_or_stay, obligations, model_tiers, context_refs, skill_refs, return_to, exit_condition`。

没有强制的“顺序→并行→核查”流水线，也不是观察到一个阈值就必然切换。固定操作集合内可展开、合并、折回；当前方式仍有效时保持不变。

## Anthropic 代码复用映射

已读取官方 release 分支的 `reference_loop/loop.py` 和 `skill/steps/02-merge.md`、`03-fold.md`、`04-as-tool.md`。后三者是迁移操作说明，不是可直接调用的在线 merge/fold 函数。外部步骤中的交互确认要求属于参考项目流程，本次没有安装或运行该 skill。

| 已有参考 | CALC 接入方向 | 我们仍要实现 |
|---|---|---|
| `Agent.run/_run`、`_run_batch` | 复用单循环及原始工具结果回到同一历史的执行方式 | 接入已有 OpenAI-compatible 模型客户端、事件检查点和继续执行状态 |
| `load_skills`、`load_skill` | 能力目录只显示描述，正文按需加载 | 工作范围内的 skill 引用、fold 后能力可达性、证据检索 |
| `02-merge.md` | 合并职责与工具，取消两者之间的冗余交接 | 运行中 checkpoint、职责迁移、原始历史归档、冲突处理 |
| `03-fold.md` | 程序知识成为按需说明，数据能力由调用者直接调用 | fold 事务与接管后恢复执行，不能只转发一份总结 |
| `04-as-tool.md` | 保留独立上下文，结构化任务入参和结果 | 分派/返回状态、父子与多任务范围、独立 usage 记录 |

参考文件使用 Anthropic SDK 及特定工具搜索协议，需适配 DeepSeek/GLM；不得假设两家 API 支持 Anthropic `defer_loading`。BC+ 首版工具集合小，可先用本地能力目录和普通 `load_skill` 工具。

参考代码示例含累计 400000 Token 和25轮等默认约束，不把这些数值悄悄带进实验；使用明确记录的实验配置。当前 adaptive.py 是参考执行语义后独立编写的 OpenAI-compatible 实现，没有复制整套 Anthropic SDK 代码或迁移 skill。若后续直接引入其源码，保留 Apache-2.0 许可和来源。

## 纯 API 与强弱模型

首版无需训练模型、路由器或价值预测器，也不以收集训练轨迹为启动条件。提示词、结构化状态及预定义执行器完成闭环。API 自述的预期收益只是决策理由，不能当作校准后的真实增益。

用户确认使用已有 DeepSeek Pro 与 Flash。配置分别为 deepseek-v4-pro 和 deepseek-flash，先按 Pro 做关键判断、Flash 做常规执行分工，再用开发任务验证实际差距。升级时保留当前 loop 的证据和历史。当前代码支持升级；困难环节结束后降级是后续扩展，尚未实现。

## 基线与首轮验证

唯一首轮外部基线改为 MANTA；MANTA 是对照方法，不是把其系统改名作为 CALC。此前 CLM 首轮主基线安排被替代，代码和历史结果保留。

已根据本机资产核查选择 WorkBench multi_domain/v1（210题），使用固定作者 MANTA 提交的数据适配和状态评分。CSV及代码放 D 盘；无需检索服务或Qwen判题。BrowseComp-Plus保留后续，不作为本轮最先操作的数据集。

先用相同单模型比较 MANTA 与 CALC 的协作机制，再在同一数据集比较 CALC 全强模型与强弱混合版本，以区分模式切换收益和换模型收益。若做混合模型之间的主比较，需给双方相同模型池并公开各自路由设置。所有规划、审查、整理与修复调用计入成本。

首轮重点验证：相同固定模式/操作库下，运行中允许切换是否优于起始选定后保持不变；完整方法与禁用 merge/fold 比较，检验收拢循环的作用；同一切换机制下，强弱混合是否在质量与成本之间更有效。官方正确率、正常交卷率、真实 Token、模型分项请求与费用、墙钟时间分别报告。缺 usage 不当作零。

MANTA 的在线 playbook 更新属于基线方法设置，复现时记录初始状态、题目顺序和更新方式；不得静默关闭后仍称原生复现。CALC 首版提示与模式库在评测前冻结，测试判分不回流决策。

## 来源

- 主要设计依据，Anthropic 2026-10-22：https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop
- 配套官方代码：https://github.com/anthropics/single-agent-loop-kit
- 单循环参考实现：https://github.com/anthropics/single-agent-loop-kit/blob/release/reference_loop/loop.py
- 合并迁移说明：https://github.com/anthropics/single-agent-loop-kit/blob/release/skill/steps/02-merge.md
- 折回迁移说明：https://github.com/anthropics/single-agent-loop-kit/blob/release/skill/steps/03-fold.md
- 子 Agent 工具调用说明：https://github.com/anthropics/single-agent-loop-kit/blob/release/skill/steps/04-as-tool.md
- Anthropic 工作流模式：https://claude.com/resources/articles/common-workflow-patterns-for-ai-agents-and-when-to-use-them
- Anthropic 路由与编排：https://www.anthropic.com/research/building-effective-agents
- MANTA 论文：https://arxiv.org/abs/2607.28527
- MANTA 系统文档：https://mao-code.github.io/MANTA/docs/self-evolved.html
- MANTA 复现说明：https://mao-code.github.io/MANTA/docs/reproducing.html
- MANTA 数据适配说明：https://mao-code.github.io/MANTA/docs/benchmarks.html

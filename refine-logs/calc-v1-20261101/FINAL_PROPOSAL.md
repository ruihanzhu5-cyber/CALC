# CALC V1：根据继续执行增益触发多智能体协作

状态：方法设计；尚未实现/训练为新的端到端运行系统，尚无V1 benchmark成绩。文献截止2026-11-01。

## 问题锚点

- Bottom-line problem: On complex multi-step tasks, jointly decide where unfinished work executes and what information it receives, improving the success–cost frontier of multi-agent systems.
- Must-solve bottleneck: Fixed teams and recency/new-document heuristics cannot judge semantic progress, the usefulness of an independent context, or the information needed to continue after an agent is folded or resumed.
- Non-goals: Build a new benchmark; move the paper back to security; claim that a new module name establishes novelty; claim SOTA before comparable measured results.
- Constraints: Existing BrowseComp-Plus and its official scoring protocol first; DeepSeek/GLM API access and several thousand trajectories; reuse the frozen corpus and existing baseline ports; preserve V0 and its results. No test answer enters the actor or policy-training features.
- Success condition: A model-driven executable system that produces real joint lifecycle/context decisions; subsequent paired official-score experiments show a better quality/cost frontier than strong recent baselines and isolate the contribution of joint decisions.

## 研究主张

提高协作效率与最终任务正确率，需要学习：**在当前任务状态下，这个Agent采取这个协作动作、把这些未完职责和上下文交给这个接收者，是否优于在原处继续执行。**

生命周期动作、接收者、任务职责、下一动作与上下文共同构成一次候选干预。团队数量与架构是执行过程的结果；不预设角色名单、人数或Agent数量上限。Main与Worker均能提出分派、复用同伴、交接与恢复。最终benchmark答案统一由Main提交。

## 文献依据

- [ATM](https://arxiv.org/html/2607.20488)：可观测过载信号、角色熵和持续阈值触发；借鉴遥测与校准，扩展到对具体干预收益的判断。
- [DyTopo](https://arxiv.org/html/2602.06039)：需要/供给语义匹配，为选择已有接收者提供信号。
- [TacoMAS](https://arxiv.org/html/2605.09539)：局部能力修正与团队结构变化分属不同时间尺度，提醒我们考虑结构调整开销。
- [POrchestra](https://arxiv.org/html/2610.13485)：Worker主动请求及状态—请求—证据协议。
- [VoS](https://arxiv.org/html/2610.09115)：从同一前缀的真实继续结果学习干预价值，区分“可能失败”与“这里干预有用”。
- [CarryOn](https://arxiv.org/abs/2610.18784v2)与[HSC-Bench](https://arxiv.org/html/2610.36523)：保留可继续执行的进度与承诺；证据找得回来和任务接得下去是不同要求。
- [Anthropic 2026-10-22](https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop)：根据独立上下文、并行和交接成本决定分派/收回，并使用渐进披露。

详细比较与其他邻近工作见[机制调研](../../docs/literature/CALC_V1_TRIGGER_REVIEW_20261101.md)。这是一条综合后可检验的方法路线；不以“首次组合这些名字”作为贡献证据。

## 三步运行闭环

### 1. 收集真实事件与局部信号

每个工具结果、职责状态更新、同伴返回或依赖解锁后，更新局部事件记录。核心信号如下。

| 信号 | 实际来源 | 用途 |
|---|---|---|
| 动作目的熵与切换 | 求解模型已报告的任务目的/工作项标签；无标签标unknown | 识别一个上下文是否同时承担混杂工作；区别于API不提供的token预测熵 |
| 调查重复 | 规范化查询、已读docid、结果集合重合 | 识别重复调查和可能可复用的成果 |
| 职责进展与阻塞 | 稳定obligation ID、状态变化、依赖关系 | 区分有用探索、真正停滞、等待外部信息 |
| 证据冲突与缺口 | 与同一约束关联的支持/反驳原文引用 | 决定是否需要核查，以及核查对象 |
| 上下文压力 | 真实请求输入估计、整理/回查记录 | 判断继续保留此上下文的价值与代价 |
| 接收者匹配与复用 | need/offer、接收者已有引用和工作范围 | 区分新建Agent、复用同伴和收回Main |
| 交接成本 | 候选上下文大小、必需引用缺失、未完成职责 | 评估迁移工作是否得不偿失 |

语义进展是模型报告的观察量，不能当官方正确性标签。角色熵、重复率和压力只进入特征，不各自绑定一条“超过阈值就创建Agent”的规则。

### 2. 提出具体分派，再和原样继续比较

Main或Worker在正常求解调用中产生候选：

```text
dispatch = {
  event, actor, operation,
  source, target_or_new, return_to,
  obligation_ids, new_obligations,
  continuation_intent,
  required_evidence_ids, required_note_ids,
  expected_result, return_condition,
  baseline_if_continue
}
```

实际可选动作包括：本地继续、新建调查分支、复用已有同伴、将核查任务分派给新/旧Agent、转交职责、收回分支、恢复先前工作。在线候选集仅为当前actor真实提出的可执行候选加continue，不假设存在枚举所有架构的最优搜索器。

第一阶段用冻结API模型执行语义策略，明确标为bootstrap/未校准。积累真实成对继续结果后，训练两个轻量本地预测头：

```text
ΔY(s,d) = E[最终正确性 | 从s执行d] - E[最终正确性 | 从s原样继续]
ΔC(s,d) = E[后续真实成本 | 从s执行d] - E[后续真实成本 | 从s原样继续]
gain(s,d) = predicted ΔY(s,d) - λ × predicted normalized ΔC(s,d)
```

与零增益的continue比较，决定是否以及执行哪个协作干预。λ、成本归一化与触发校准只在验证题上冻结；同时展示准确率—成本曲线。权重来自真实结果监督，初始手写默认分数不冒充学习型触发。若候选构造需要额外API调用，它的开销也进入总计量。

### 3. 按接收者的下一动作编译继续上下文

为该次分派生成有工作范围和版本的Continuation Capsule：已知结论、原文证据、反例、失败路线、未完成职责、下一动作、完成/返回条件以及原始档案入口。接收者的下一动作决定应带哪些内容：独立核查与恢复调查通常需要不同的视图。

运行时先验证上下文和职责引用可编译，再提交所有权改变。`fork`创建新职责与依赖；`transfer`移动原职责，不复制任务。每次分派记录自己的return_to；Worker分派的子任务默认回到该Worker。创建关系、分派/返回关系、工作依赖分别记录，合法的双向沟通不被误判成依赖环。

同一peer接受多来源分派时，胶囊按工作范围保留，不用一个last_summary覆盖所有任务。全部原始工具证据和历史可恢复。

## 何时触发哪些动作

| 情况 | 要学习比较的方案 |
|---|---|
| 多个可独立调查的缺口，当前职责混杂且推进受阻 | 新建独立分支 vs 当前Agent继续 |
| 同伴已有恰好需要的证据、经验或局部上下文 | 复用/路由给同伴 vs 新建/自己重查 |
| 决定最终答案的约束存在来源冲突 | 独立核查 vs 继续沿用当前候选 |
| 分支成果足够、剩余工作重合或重复率高 | 连同未完职责收回/交接 vs 维持独立循环 |
| 新证据改变旧假设或解锁旧依赖 | 恢复原分支/修改职责 vs 从零重建 |
| 当前Agent仍在有效推进，迁移只增加成本 | 不触发，继续本地执行 |

该表说明候选设计空间，不是人工if-else决策表。相同表面信号在不同任务阶段可以产生不同决定。

## 数据与训练

使用同一个BrowseComp-Plus，训练/验证/评测题目ID分离，现有5道开发题不进入训练。数据来自两类真实状态：CLM前缀提供本地继续/创建/核查机会；多Agent bootstrap运行提供真实的peer、归档上下文和分支，使reuse/fold/resume有训练覆盖。

在训练题中混合采样正常推进、请求协作和看似停滞的前缀。每个快照保存模型、语料、工具、候选生成器、后续执行策略和judge版本。continue与干预两臂仅首个动作/上下文不同，之后使用同一冻结bootstrap策略；分支不读取彼此新增的结果。重复no-change对照估计API噪声。最终标签来自官方判分和真实增量usage；缺usage不能补零；gold与judge解释不进入前缀特征。

不要求立即训练大型开源模型。可先用非线性小型回归/分类器学习动作交互与上下文特征；真实数据不足时只交付bootstrap策略，不报告未训练的学习结果。

## 第一轮实验

- 基线：CLM公开零样本运行配置的共同骨干移植，保留作者原生上下文编辑/回滚/收尾参数。
- 数据：BrowseComp-Plus固定任务、语料、检索与官方评分协议。
- 模型：CLM与CALC都用DeepSeek Flash；明确区别于原论文的原模型/训练检查点结果。
- 主指标：官方正确率、真实总输入/输出Token、请求数、成本、墙钟时间；统计所有控制/Worker/整理/修复调用，失败不从分母删除。
- 方法诊断：同运行时比较增益触发与固定周期；动作条件化胶囊与通用胶囊；在相同快照、输入规模下比较继续质量与重复调查成本。

实现先服务这一组对照。其他文献提供设计参照，不扩展第一轮baseline/benchmark清单。没有实验前，不宣称超过CLM或达到SOTA。

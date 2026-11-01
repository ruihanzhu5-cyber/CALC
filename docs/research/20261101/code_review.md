# When Sub-Agents Work in Parallel：官方 artifact 与接口核查

核查日期：2026-11-01。只读检查，无模型实验、无运行配置或 CALC 源码修改。

## 1. 先分清论文 artifact 与可复用框架

准确论文为 [When Sub-Agents Work in Parallel: The Promises and Pitfalls of Dynamic Concurrency in Long-Horizon Coding Tasks](https://arxiv.org/html/2610.10263v1)。作者提供的 [artifact](https://github.com/schwerli/Concurrency-Failures-Trajectory-Artifact) 当前核查提交为 `d7e7b399958616c8e8940505c0d09934c4b97cb7`，提交标题 Initial annotated trajectory corpus。

**实际核查到的是：六个 benchmark 目录中的执行轨迹、结果、人工比较注释和某些 Agent 在任务内生成的 workflow JavaScript。没有核查到可直接接入 CALC 的新调度器、runner 或 parser 实现。** 不能把原文“release analysis scripts”的文字自动视为已读过这些代码。根目录没有 README 或 LICENSE，GitHub metadata `license=null`；递归目录 API 返回 `truncated=true`，因此不声称穷尽证明整个仓库没有这些文件。阅读与引用接口思路可以进行，直接复制源码之前仍需明确许可。

论文研究的是 Codex、Claude Code、Kimi Code 三种原生 harness；artifact 保存的动态 workflow 是研究对象的输出，不是作者提出的新方法实现。它的价值是提供失败模式、接口使用轨迹和成对证据。

## 2. 实际读到的 workflow 接口

精读源文件：[verify-compiler-lab-reconstruction-wf_bdb133ff-481.js](https://github.com/schwerli/Concurrency-Failures-Trajectory-Artifact/blob/d7e7b399958616c8e8940505c0d09934c4b97cb7/loopsbench/task_compiler/claude/parallel/agent/claude/round-01/.claude/projects/-workspace/6fd3eee8-de7e-41da-8124-4344d9a53388/workflows/scripts/verify-compiler-lab-reconstruction-wf_bdb133ff-481.js)。这是 Claude 的实际生成脚本，未执行此脚本。

| 位置 | 实际设计 | CALC 可借鉴之处 / 边界 |
|---|---|---|
| 10–24 行 | 给 lexical/parser 两类任务明确工作目录、输入文件、编码与共同约束；明确不得写文件 | 分派按实际证据和操作边界，不只给抽象角色名。这里只读限制是提示词，不能从脚本证明 runtime 权限强制执行。 |
| 28–84 行 | 五个具体任务，每个有 label、任务范围、验证方式和应返回内容 | 一个分支应承担可交付职责，并有能供下游消费的输出契约。 |
| 86–87 行 | `parallel(tasks.map(...agent(...)))`：并行分析，等待返回 | 运行时给模型清楚的 fan-out/join 语义；并非自动判断子目标独立性的模型。 |
| 89–101 行 | 分析完成之后，按分析报告建立另一批独立 Critique，要求重新推导并反驳 | 顺序依赖连接并行组，review 输入显式绑定前驱产物；独立验证是具体动作。该脚本是批次 barrier，不是先完成先消费。 |
| 103–106 行 | 返回带 task 标签的 analyses、critiques | 结果显式归属任务，不依靠扁平自然语言汇总恢复对应关系。 |

该脚本没有发现 CALC 所需的在线 merge/fold、迁移所有权、被拒后恢复原会话等能力。这里的“整合结果”不能等同于“迁移未完成职责并关闭来源 loop”。此外 `analyses.filter(Boolean).map((a,i)...)` 再用 `tasks[i]` 存在空报告时索引错位的潜在风险，未看到该案例实际触发，不能把它当已发生失败。借鉴接口时宜保留 task ID 与结果的绑定。

## 3. 官方注释提供的反例

[ClickHouse paired annotation](https://github.com/schwerli/Concurrency-Failures-Trajectory-Artifact/blob/d7e7b399958616c8e8940505c0d09934c4b97cb7/loopsbench/task_ClickHouse_seg07/claude/annotation.md) 明确区分“两个版本都未通过”与“并行组织导致局部覆盖/关闭更差”。并行运行大量展开一需求一 child，留下未回收 workflow 与不完整成果；顺序对照覆盖更多，但仍没有完成任务。这适合我们的审计：记录谁发起、谁执行、谁收到、谁验收，以及结果是否在主任务结束前被实际使用。不能只统计 spawn 数，也不能把过程缺陷直接写成最终失败的唯一因果原因。

## 4. 对照 CALC 当前真实代码

本地实现：`D:/CALC-experiments/code/CALC-task-progress/src/calc/`。

| 当前接口 | 代码证据 | 问题与有依据的改动方向 |
|---|---|---|
| GAIA2 observation → collection trigger | `benchmarks/gaia2.py:152–164` 返回 `str(result)`；`progress.py:70–80` 对字符串仅 `json.loads`，失败后无结构事实 | 结构契约在 adapter 层丢失，之后再调提示词无法修复。设计 typed result + 可恢复 raw view，并让两个方法看到语义等价的事实。不要凭结构猜独立性。 |
| progress assessment 与 business tool batch | `adaptive.py:658–675` checkpoint 未报告就拒绝整批调用 | 普通业务执行受到记账协议阻拦。progress 事实更新与组织操作必须分离；只有真正涉及职责变更的操作才需要所有权/版本原子检查。 |
| 模糊的 change | `adaptive.py:290–291,331–338` 接受 change 并记录 assessment，但明确 `topology_changed=False` | 应分别记录 business-plan-change、collaboration proposal、effective operation，不能用同一个 change 计数宣称组织自适应。 |
| 全量上下文与按需能力叠加 | `adaptive.py:235–254` 当前团队/事件写入 system，保留所有 actor.messages，调用每次附全部工具 | 接口应给具体工作所需的工具/证据入口；采用按需工具就需验证实际请求确实不再携带全表。不能把存在 load_skill 当成已经实现上下文节省。 |

## 5. 一个更直接的执行者主动触发参考：POrchestra

此部分是补充代码参考，不是上述并行论文的作者代码。已核对作者远端 [POrchestra commit 371aef619aec6f2918690a2fbaf9bf797b3025d3](https://github.com/XueyangFeng/POrchestra/tree/371aef619aec6f2918690a2fbaf9bf797b3025d3)，对应本地 `D:/CALC-experiments/upstreams/POrchestra`，git tracked status clean。

- [`DelegateTaskTool._run_session_until_control`, 440–520 行](https://github.com/XueyangFeng/POrchestra/blob/371aef619aec6f2918690a2fbaf9bf797b3025d3/porchestra/tools/delegate.py#L440)：Worker 在正常 step 中产出普通环境 action 就留在自身循环；遇到 finish/revise/stop 才组装控制结果返回 Main。这个边界比“普通工具返回也唤醒父节点”清晰。
- [`revise_active`, 201–318 行](https://github.com/XueyangFeng/POrchestra/blob/371aef619aec6f2918690a2fbaf9bf797b3025d3/porchestra/tools/delegate.py#L201)：keep 更新现有 session 的任务/上下文/工具，调用 apply_revision，之后继续 `_run_session_until_control`；replace 则创建新 executor。**same-session continuity 对应 keep，不要把 replace 也说成保留完整会话。**
- `subagent.py` 的 SAE 约束把 state facts 与 request/action 分开；请求包含作用对象与原因。可用于解决 CALC “报告计划变了但没有可执行组织动作”的歧义。
- 当前核心持有一个 `self._session`，不是多活跃分支调度器，不提供现成 merge/fold。它还有显式 budget 与 final_handoff 边界，不应不加区分复制进 CALC。
- 仓库 `THIRD_PARTY.md` 列 AOrchestra Apache-2.0、ARE MIT，且明确需另行核实新增代码归属；此次未复制源码或变更运行时。

## 6. 建议形成的最小接口链（我们的设计推论，非原文现成算法）

1. 环境产出结构化 observation/资源版本，不把普通结果自动升级成协作事件。
2. 当前执行者在正常求解调用内决定继续本地工作，或提出具体调整：scope、evidence、sources、receiver、next action、completion condition。
3. 父节点消费有新证据的 proposal 或职责完成/阻塞事件；保持当前方式是合法决策。
4. 执行层检查操作权限、版本与在途工具边界，保证职责唯一所有权；模型负责语义选择。
5. 接收者拿到未完工作与读取原始历史的入口，实际继续执行；完成才释放依赖，不能在迁移瞬间虚报完成。
6. 审计区分 proposal / accepted / effective / result-consumed / work-completed，并单列控制成本。把这一条链测通后再付费跑题。

该思路提供可实现的对照：固定团队、仅动态展开、完整展开+收拢、单 loop；图拓扑是协作执行的一个维度，不能替代职责归属、同步时机和上下文可用性。

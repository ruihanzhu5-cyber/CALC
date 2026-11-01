# CALC 接口与触发机制：大团队官方实现核查

核查日期：2026-11-01。只读研究；未修改 CALC、未运行付费模型。检查过 D:/AGENTS.md、D:/CALC-experiments/AGENTS.md、research/AGENTS.md，未发现额外指令。下列主张来自固定提交源码或官方论文/文档，工程文档不当作理论定理。

## 结论

最贴近 CALC 当前问题的现成设计是：**Magentic-One 的明确进展字段、Deep Agents 的任务级状态通知及去重、Agensh 的持久事件队列和安全注入边界、ADK 的结构化状态增量与显式控制转移。** 不建议整体移植任一框架。特别是 Magentic-One 的每轮额外管理模型、Agensh 的固定闲置提醒与强制发帖提醒，不应直接变成 CALC 的每步控制开销。

这几套实现没有直接给出 CALC 所需的“任务进展驱动 expand/merge/fold + 未完职责接管”完整方案；它们提供可靠的接口原语和边界，使方法创新不被消息协议污染。

## 1. 固定来源

| 系统 | 固定提交 | 本地核查文件 |
|---|---|---|
| Microsoft AutoGen / Magentic-One | `d07c667a3239ea4ab7af62a53b0f4ff205a1f23d`，2026-10-28 | `interface-sources/magentic_one.py` |
| Google ADK | `95d8610ea3445ce9c6d0cf70aed1a0071ddc1e2f`，2026-11-01 | `adk_event_actions.py`、`adk_transfer.py`、`adk_parallel.py` |
| LangChain Deep Agents | `220aff708682ad0883469a00531e5c4d958b47ec`，2026-11-01 | `deepagents_subagents.py`、`deepagents_async.py` |
| Microsoft Agensh | `d6063b9086d548909f4ff1439d3b4f81d11ef4a6`，2026-10-31 | `agensh_dispatcher.ts`、`agensh_state.ts`、`agensh_mcp_notice_shim.cjs`、SQL、README |

以上文件都只下载到研究目录，不是加入 CALC 的依赖。已读取并保存固定提交许可证：AutoGen 的 `LICENSE-CODE` 为 MIT（根 `LICENSE` 则是文档 CC BY 4.0，二者不要混淆）；Deep Agents 和 Agensh 为 MIT；ADK 为 Apache-2.0。本轮没有移植代码。后续复制具体文件仍需保留文件及许可证要求的来源与归属。

## 2. Microsoft Magentic-One：哪些值得借，哪些不值得照搬

[固定源码](https://github.com/microsoft/autogen/blob/d07c667a3239ea4ab7af62a53b0f4ff205a1f23d/python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_magentic_one/_magentic_one_orchestrator.py)。对应原论文 [Magentic-One](https://www.microsoft.com/en-us/research/wp-content/uploads/2024/11/MagenticOne.pdf)。

- `handle_agent_response`（193 行）在收到完整 Agent response 后进入 `_orchestrate_step`（300 行）。不是在每一个内部 tool result 后启动父节点。
- `LedgerEntry` 区分任务是否满足、是否有进展、是否陷入循环、下一执行者和具体指令；“计划改变”与“选谁执行”是不同字段。
- `_thread_to_context`（514 行）排除 `ToolCallRequestEvent` 和 `ToolCallExecutionEvent`；父节点获得对外回应/摘要，而不是把所有内部事件原样注入。
- 代码仍每个协调轮次调用管理模型；累计 stall 达阈值时更新事实和计划，并重置团队上下文。这不是廉价事件触发控制，也不是 merge/fold。

适配建议：借字段语义和 Agent-response 边界；不照搬每轮管理模型、固定 stall 阈值和重置会话。CALC 应让正常执行者调用携带进展更新，只有存在相关新信息才给组织决策机会。

## 3. LangChain Deep Agents：最直接的父节点唤醒参照

[同步子任务固定源码](https://github.com/langchain-ai/deepagents/blob/220aff708682ad0883469a00531e5c4d958b47ec/libs/deepagents/deepagents/middleware/subagents.py)，[异步固定源码](https://github.com/langchain-ai/deepagents/blob/220aff708682ad0883469a00531e5c4d958b47ec/libs/deepagents/deepagents/middleware/async_subagents.py)。

同步接口 `task(description, subagent_type)`：子任务独立执行，返回一个 ToolMessage；结构化结果用 JSON 序列化。`isolated` 只注入任务描述，`fork` 继承有效历史，剔除不应续跑的父执行状态。子任务消息历史不整体回灌父节点（747–835 行）。

异步接口分成 start/check/update/cancel/list；任务 ID 持久化，更新复用同一 thread，并显式区分 interrupt 与 enqueue。关键实现：

- `_check_event`（1500 行）：只将 success/error/timeout/cancelled/waiting 形成可通知结果。
- `_apull`（1676 行）：`status` 与 `run_id` 均不变就不报告；已有检查或通知消费过的结果不反复注入。
- `aafter_model`（1664 行）：只有收到新状态更新才再次进入模型，不因“仍 running”不断调用。
- `_awake_parent`（658 行）：父节点空闲才唤醒；运行中由下一模型边界接收，防止并发启动父会话。
- `_record_notification`（1710 行）：旧 run 被新 run 替代时，旧通知不能冒充新任务已完成。

对 CALC 最直接的价值：**业务工具照常执行，组织通知走独立、带版本的任务状态通道。** 源码的网络错误容错不建议照搬；这里只借接口契约。官方 [异步文档](https://docs.langchain.com/oss/python/deepagents/async-subagents) 标注这些机制为 beta，且服务端/异步运行路径才支持完整自动通知。

## 4. Google ADK：状态更新不等于组织变更

[EventActions 固定源码](https://github.com/google/adk-python/blob/95d8610ea3445ce9c6d0cf70aed1a0071ddc1e2f/src/google/adk/events/event_actions.py)、[transfer 工具](https://github.com/google/adk-python/blob/95d8610ea3445ce9c6d0cf70aed1a0071ddc1e2f/src/google/adk/tools/transfer_to_agent_tool.py)、[并行运行](https://github.com/google/adk-python/blob/95d8610ea3445ce9c6d0cf70aed1a0071ddc1e2f/src/google/adk/agents/parallel_agent.py)。

- `state_delta`、`artifact_delta`、`transfer_to_agent`、`escalate`、`end_of_agent` 分开表达，状态变化不自动等于控制转移。
- `TransferToAgentTool` 将当前可达 agent_names 放入 JSON Schema enum，减少不存在的接收者；工具明确写入 transfer action。
- 并行分支隔离会话历史，但共享 session state；同 key 写入存在最后写入覆盖，不可把“共享状态”当作并发安全。
- `ParallelAgent` 当前代码在直接子节点 escalate 后停止剩余分支，保留各分支事件顺序；这不是职责迁移。该类已被标弃用转向 Workflow，不建议新增依赖旧类。

适配建议：CALC 业务状态 `task_delta` 与组织动作 `organization_action` 应独立；接收者由运行时提供合法候选；环境写操作继续串行提交或明确事务规则，不靠消息图保证写安全。

## 5. Microsoft Agensh：事件输送和主动认领的最新直接依据

[论文](https://arxiv.org/html/2609.26781v1) §2.1、Appendix B.1/B.2；[固定 dispatcher](https://github.com/microsoft/Agensh/blob/d6063b9086d548909f4ff1439d3b4f81d11ef4a6/mini-router/src/dispatcher.ts)、[state](https://github.com/microsoft/Agensh/blob/d6063b9086d548909f4ff1439d3b4f81d11ef4a6/mini-router/src/state.ts)、[MCP 包装器](https://github.com/microsoft/Agensh/blob/d6063b9086d548909f4ff1439d3b4f81d11ef4a6/mini-router/mcp_notice_shim.cjs)。

论文支持的机制：Worker 自主获取上下文、认领范围、执行、验证、发布成果。事件有 ID，写入持久队列，按 turn 合并。活跃 turn 内的重要直接消息和共享发现附加在基础设施工具返回边界；不是任意抢占正在执行的工具。CLAIM 是工作范围公告，需要冲突沟通，并非原子责任锁。论文的 merge 是 Git 成果合入，不是将 Agent loop 的职责 fold 回父节点。

源码核查：

- `state.ts:54,120–126` 为 `(dedup_key, agent)` 唯一键，并以事件ID入库，吸收重复直播/补拉事件。
- `dispatcher.ts:47–88` 串行化同会话调度，退役已由 MCP shim 显示的通知；`128–149` 先标 sending，完成 turn 后标 sent。
- `dispatcher.ts:171` 明确“成功交付后的记账失败不能把该 turn 放回重试”，避免重复实际工作。
- `mcp_notice_shim.cjs:125,199–214` 仅包装存在 MCP content 的工具响应，输出后确认已显示；本身不要求先完成一次新的 LLM 审批才允许原工具动作。
- 也存在“没有发共享发现则追加提醒”的机制。该机制会引入额外调用，不应原样用于我们的效率方法。

## 6. 建议 CALC 下一版固定的五条接口契约

以下是基于上述实现的 CALC 设计建议，不是原论文已有结论：

1. **观察与控制分层**：`ToolObservation` 保留 typed payload、来源/版本、证据ID和 raw 读取入口；`TaskDelta` 更新目标/依赖；`OrganizationAction` 只有 keep/delegate/merge/fold/review 等明确操作。取消“change”同时表示改业务计划和改协作的歧义。对应 ADK actions + Deep Agents structured response。
2. **普通输出本地消费，任务事件增量通知**：工具返回仍交当前执行者；相关完成/失败/阻塞/新依赖/明确协作请求才进入父 inbox。通知以 `(work_id, state_version, event_type)` 去重，已消费游标保留。对应 Deep Agents `_apull` 与 Agensh 队列。
3. **进展更新不成为合法业务工具的前置手续**：模型可在正常决策携带状态更新；缺一份例行 report 不取消整批独立合法工具。只对组织迁移所有权、参数有效性及依赖条件做执行约束。来源是对上游边界的综合适配，不声称上游已证明此设计最优。
4. **调度只在安全边界交接**：模型请求可以并发，环境写入串行；事件在模型/工具边界合并。merge/fold 提交前等待已提交工具完成，再变更职责 owner/version，拒绝旧版本后续工具；接收者拿到未完目标、依赖、证据、失败路线、下一步和历史入口。Agensh 的交付去重提供部分参照，完整职责接管是 CALC 自身需实现与测试的部分。
5. **续跑与完成可区分**：持久 work_id，run_id/owner_epoch 区分新一轮和旧返回。被拒绝的协作提议不结束原 loop；迁移不等于完成；只有接收者真实完成迁移职责才解除后继依赖。以 Deep Agents 的旧 run 通知和同 thread 更新为参照，保留 CALC `complete_transferred_work` 的独有职责语义。

## 7. 对当前 CALC 的直接定位

实际检查 `adaptive.py:650–674`：pending checkpoint 且没报告会产生 progress_protocol_error，并阻止动作批次。这一门禁是 CALC 自己的接口决定，不是 Magentic-One 或上述框架要求。`gaia2.py:164` 直接 `str(result)` 与 `progress.py:70` 的 collection 解析衔接问题也属于观察协议问题，不应解释成“模型不想协作”。应先做零付费的接口快照测试，再研究触发策略效果。

下一版实现前最小验证：typed observation 字段完整；重复状态无父调用；普通工具连续执行不要求额外报告；相关依赖事件恰好产生一次决策机会；旧 run 返回不覆盖新 owner；转移前已提交写入不重复；真实职责完成才解锁依赖。

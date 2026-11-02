# 显式职责调度 V4

2026-11-02。分支 `feat/explicit-progress-scheduler`，起点 `c46e0919a9d72c3d3e3e9029f135541d6bedcebc`。保留旧版、配置和实验，不覆盖历史结果。

## 本轮实现

`AdaptiveRuntime(scheduling="explicit")` 在首次任务理解、首次环境观察、新业务集合、完成/失败、阻塞、依赖、跨执行者重复资源等新事件边界进入明确 DECIDE。普通工具结果继续当前 loop；同批事件合并，事件版本未变化不重复调度。首次观察只提供比较机会，不决定操作。

DECIDE 只提供 `decide_collaboration`，没有业务工具。模型必须以一个原生工具调用返回 keep/defer/candidate、证据引用、具体下一步和理由；候选另列相同未完职责 ID。snapshot/event 标识由发起请求的运行时绑定和验证，不要求模型回传哈希或事件 ID；keep 的原职责也由真实状态保留。不存在默认 keep。模型可以读取本来就能看到的任务和历史后提出分工，不要求预先调用 report_progress。

keep 结束该事件批，原会话继续。defer 绑定活跃直接子职责，完成/失败等状态变化可唤醒；普通工具引起的子版本增长不唤醒父节点。等待审批的子职责不能作为 defer 对象。

candidate 复用已有协作操作参数。版本、当前工作、证据和保持方案由快照编译，而不是让模型重复编造。代码在完全分离的状态副本上调用同一个真实迁移执行器，得到接收者的下一次输入、交接消息、工具 schema 和工作安排。**预演只改状态，不调用环境或模型，不复制任务环境。**

候选后再进行一次 `commit_collaboration`，模型看到成本面板可提交或保持。子节点提交的调整仍经父节点批准，批准/拒绝使用同一调度入口及原 session；Main/Worker 保留递归分派。

组织决策在共享环境 barrier 串行处理；普通独立模型请求仍按原 concurrency 并发，工具提交保持串行。迁移前检查工作、证据、状态和 owner_epoch。新状态使候选过期时记录 invalidated，不执行旧操作；下一决策处理新状态。格式错误/截断则显式失败，不修补 JSON、不自动继续或付费重试。

旧 `scheduling="voluntary"` 路径保留，用于历史复现和调度节点消融。新示例 WorkBench/AppWorld 配置启用 explicit；没有新增累计 Token、总请求数或 Agent 数量默认上限。

## 谁决定什么

- LLM：工作是否独立、是否需要隔离核查、保持/等待/重组、分支数、分支目标、是否值得交接、最终 commit。
- 代码：事件和版本去重、决策阶段、同工作 ID 覆盖、权限和操作掩码、实际输入与交接编译、版本检查和真实职责迁移。
- `complete_transferred_work` 保持职责级完成语义，接收者实际完成后释放后继。

本轮覆盖按现有完整 loop 职责进行；不宣称任意部分职责迁移。共同 ID 和完成条件属于结构约束，语义完整性仍需模型判断。

## 实际计量与估计范围

每个真实调用记录 started/finished/failed 和 request_id；最终 model_call 保留 provider response_id、完整 usage、purpose。控制 purpose 是 collaboration_decision 或 collaboration_commit；执行、进度混合调用保留原属性。没有单独摘要器或逐工具 Judge。

成本面板精确报告已编译 payload 的 UTF-8 字节长度，附实际历史输出 Token 与时长统计。它**不是剩余总 Token 预测器**：没有匹配 tokenizer、后续调用数、未执行输出和外部耗时依据时，相应未来量为 null，不填估计分数。模型根据面板和职责比较；没有“分数正即 fold”硬规则。前期公式文档的全程预测目标尚未全部数值化。

用于决策的 snapshot 与成本面板保存在 scheduling_candidate 事件。所有 DECIDE、确认、父审批及上下文交接引起的调用都进入真实总账。

## 来源

本轮为 CALC 独立适配实现，没有复制上游源文件：

- [Magentic-One `_orchestrate_step`, d07c667](https://github.com/microsoft/autogen/blob/d07c667a3239ea4ab7af62a53b0f4ff205a1f23d/python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_magentic_one/_magentic_one_orchestrator.py#L300)，MIT：借显式 progress-ledger 决策路径，不移植十次 JSON 重试、固定团队或停滞硬阈值。
- [DeepAgents `_apull`, 2b33a4c](https://github.com/langchain-ai/deepagents/blob/2b33a4c0cf60bc4927f27eae8b86f84e7a897b99/libs/deepagents/deepagents/middleware/async_subagents.py#L1676)，MIT：借任务代次、状态通知去重和边界投递。
- [POrchestra `revise_active`, 371aef6](https://github.com/XueyangFeng/POrchestra/blob/371aef619aec6f2918690a2fbaf9bf797b3025d3/porchestra/tools/delegate.py#L201)：借原 session 修订语义；未找到覆盖其新增代码的整体 LICENSE，未直接复制。
- Anthropic 按需能力、MANTA 证据视图的已有适配保留，详见 WORK_SCOPED_DISPATCH_V3.md。

DeepSeek 文档指出 thinking 模式不支持 required/named tool_choice。因此保留原模型思考配置，只在决策阶段提供一个原生函数，运行时强校验恰好一个合法调用；没有为了强制函数调用偷偷关闭 thinking，也没有默认开 beta strict。[官方接口](https://api-docs.deepseek.com/api/create-chat-completion/)

## 验证与运行

环境仍为 D 盘的 CALC-Research WSL。无付费测试：

```bash
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/opt/calc/tmp \
PYTHONPATH=/mnt/d/CALC-experiments/code/CALC-task-progress/src \
/opt/calc/envs/gaia2/bin/python -m pytest \
  /mnt/d/CALC-experiments/code/CALC-task-progress/tests -q -p no:cacheprovider
```

WorkBench 预检不加 execute；AppWorld 先 lock-data，预检不加 execute。实际执行使用同一配置加 `--execute`：

```bash
/opt/calc/envs/gaia2/bin/python -B scripts/run_adaptive_workbench.py --config /mnt/d/ABSOLUTE_RUN/workbench.config.json --execute
/opt/calc/envs/appworld/bin/python -B scripts/run_adaptive_appworld.py --config /mnt/d/ABSOLUTE_RUN/appworld.config.json --execute
```

本轮授权只运行历史 WorkBench multi_domain_0 和 AppWorld train 82e2fac_1，均 Flash4096、原 concurrency 和环境参数。新目录/官方实验命名隔离，不覆盖旧答案或判分。逐题比较官方成功、正常完成、输入输出 Token、控制与执行请求、runtime 墙钟及切换。单次开发案例对比不作为平均性能或 SOTA 结论。

首次 a1a45cc WorkBench 尝试因模型输出缺失冗余 snapshot_id 而严格拒绝，未交卷；其轨迹和消费保留，不能当正常题目结果或省 Token 收益。后续协议修订删除模型的身份回传义务，运行时继续对真实请求快照检查版本；没有补字段、接纳旧坏响应或自动把错误改为 keep。本轮运行两题的授权范围内只修复并补跑 WorkBench，保留已正常完成的 AppWorld，不扩展任务集合；两题应分别注明实际代码版本和条件恢复性质。

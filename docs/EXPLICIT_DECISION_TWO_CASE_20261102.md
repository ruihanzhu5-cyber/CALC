# 显式调度：WorkBench / AppWorld 两题开发对照

日期：2026-11-02。结果目录 `D:/CALC-experiments/runs/calc-v4-explicit-two-case-flash-20261102-1550`。只运行 CALC，没有 MANTA，没有扩展任务集合。

## 实现和版本

- 开发分支 `feat/explicit-progress-scheduler`，起点 `c46e0919a9d72c3d3e3e9029f135541d6bedcebc`。
- `a1a45cca7e9120b66b9b1e75e13216916750b7bc`：事件触发的 DECIDE、明确 keep/defer/candidate、同职责覆盖、真实迁移的隔离状态预演、候选编译和提交确认、独立控制计量。
- `7f1f32b093f0a1fa34670153da1724c7f89ee3f5`：snapshot/event 身份由运行时绑定，不要求模型回传；保留严格格式和状态版本验证。
- 必要状态机及回归测试最终 **350 passed**；Ruff 与 git diff --check 通过。官方环境零付费预检通过。

全部解题模型为 DeepSeek Flash，单次输出 4096，原 concurrency=3 和原工具/环境参数；未新增累计 Token、请求数或 Agent 数限制。环境、Python、数据、临时文件、缓存、源码及结果使用 D 盘或 D-backed CALC-Research WSL。

## 同题结果

旧版取自 `calc-v3-threebench1-flash-20261102-1440` 的冻结源码和原始结果。

| 数据集 / 题目 | 版本 | 官方通过 | 正常交卷 | 输入 Token | 输出 Token | 总 Token | 请求 | 明确调度 | 切换 | Runtime 秒 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| WorkBench multi_domain_0 | V3 | 是 | 是 | 50,942 | 4,089 | 55,031 | 9 | 0 | 0 | 23.60 |
| WorkBench multi_domain_0 | V4 修复后 | 是 | 是 | 57,686 | 2,578 | 60,264 | 12 | 3 | 0 | 24.87 |
| AppWorld train 82e2fac_1 | V3 | 是 | 是 | 258,025 | 10,307 | 268,332 | 16 | 0 | 0 | 84.03 |
| AppWorld train 82e2fac_1 | V4 首次正常结果 | 是 | 是 | 253,955 | 9,185 | 263,140 | 20 | 4 | 0 | 69.20 |

WorkBench 完成尝试 Token 增加 9.5%，runtime 增加 1.27 秒；AppWorld Token 减少 1.9%，runtime 减少 14.83 秒。两题完成尝试合计 **323,404 Token**，旧版 **323,363**，基本持平（增加 41）。两题均为单 loop，没有候选生成、提交确认、merge/fold 或模型切换。

这是已观察开发题的条件恢复诊断。AppWorld 为 a1a45cc，WorkBench 为 7f1f32b；不称同提交公平批次，更不称 SOTA。任务不同执行路径、工具错误与服务延迟也会影响成本，不能把 AppWorld 的小幅下降归因于某个模块。

## 请求和控制成本

| 任务 | 纯业务执行 Token | 业务/进度混合 Token | DECIDE Token | DECIDE 请求 |
|---|---:|---:|---:|---:|
| WorkBench 修复后 | 40,538 | 7,099 | 12,627 | 3 |
| AppWorld | 235,743 | 0 | 27,397 | 4 |

新增 7 次 DECIDE 共 **40,024 Token**，均在总量中。混合请求不伪拆执行/控制 Token；没有额外 Judge、摘要器或候选确认请求。评分均为任务结束后的官方状态评测，官方 judge 模型调用为 0。

本轮还保留 WorkBench 初次协议失败：**19,250 Token、5 请求**，未正常交卷、官方判未通过。模型明确输出 keep，但缺冗余 snapshot_id，严格校验拒绝，没有继续执行业务。随后删除模型的身份回传义务，在运行时绑定真实请求快照；不补旧响应字段、不静默变成 keep。只补跑该 WorkBench，AppWorld 未重复执行。

本轮全部实际尝试共 **342,654 已知 Token、37 请求**，包含该中断。全部返回 usage，无未知或仍在途请求。初次失败的低 Token 不是节省。

## 轨迹结论

WorkBench 的 3 次决策分别出现在任务开始、CRM 首次观察、日历集合出现后。模型判断为联系人前置条件、负责人、空档和创建会议构成依赖链；最后阶段只剩一个写操作，三次明确选择 keep。最终使用真实工具完成官方要求。该理由是模型判断，不是全体查询在理论上完全不可并行的证明。

AppWorld 的 4 次决策分别处理任务开始、一次错误工具发现、成功发现应用目录、播放列表集合出现。模型明确计划处理分页并比较歌曲点赞数，认为保持共享登录和同一个上下文更省。最终官方通过。约 50 个歌曲 ID 是否仍值得分工是未执行的反事实，本次不能断言分派一定无价值。

两题最终均无调度/协议错误和截断。WorkBench 无业务工具错误；AppWorld 有 2 次本地工具错误且恢复，旧版有 1 次。因此 API 发现差异也是成本解释因素。

## 当前能确认的变化

1. 以前只能观察到“事件存在、没有 collaborate”；现在能观察到每批事件后的明确组织选择、理由和具体下一步。
2. 不需要先调用可选 report_progress，普通任务观察也能进入 DECIDE。
3. 严格协议检验暴露了真实接口缺陷，并通过减少模型复制机器状态的义务修复，未靠 JSON 兜底处理。
4. 当前两题没有验证在线展开或收拢收益；相关预演、拒绝续跑、真实接管和依赖释放由状态测试覆盖。
5. 显式调度成本已经可测，简单任务可能被控制开销抵消。后续优化应保留可检验选择，针对重复上下文和不必要决策边界减少成本，而不是强制制造协作。

## 结果和来源

- 根目录 `RESULT_COMPARISON.md`：包含首次失败的完整结果表。
- `request_costs.csv`：逐请求真实 Token、purpose、response_id、耗时和 trace 行。
- `trace_findings.json`：明确选择、候选、切换和错误证据。
- `batch_manifest.json` 与 `workbench-wire-fix1/batch_manifest.json`：源码 archive、配置和任务固定记录。
- `storage_audit.json`：D 盘存储核查；Windows/WSL 系统文件仍由操作系统管理。
- 设计来源和实际实现边界见 `EXPLICIT_PROGRESS_SCHEDULER.md`。

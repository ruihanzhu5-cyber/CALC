# CALC 任务进展协作版：AppWorld 单题运行记录

日期：2026-11-01。只运行用户授权的一道 train 题，没有启动其余题目或四组批量对照。

## 固定配置

- 分支：`feat/task-progress-collaboration`。
- 开发起点：`28e99aeda597c0b4a6303254fec2b7e9513fa081`（当时本地/远端 feat/calc-v0 相同）。
- 本次执行提交：`ad23a24f41ca0b2e1036deca3e605153c7da2eec`。
- 状态机提交：`106aa1c`；AppWorld 接入提交：`ad23a24`。
- 运行后文档提交另将提示中的 scope 字段名澄清为与 schema 一致的 current_scope；
  本题结果仍严格对应 ad23a24，没有重新调用模型。
- AppWorld 官方提交：`42b5bcf3cd334fee33f0c37c02070a9f5807add5`，数据 0.2.0。
- 题号：`82e2fac_1`，按 train 列表顺序选取，未按答案或隐藏难度筛选。
- 题目：找出用户 Spotify 歌单中获赞最多歌曲的标题。
- 模式 full，所有路由 DeepSeek Flash，单次 max_tokens=4096，模型请求并发上限3。
- 无额外总请求/累计 Token/Agent 数量默认上限；max_waves=null。
- 环境：D 盘承载的 CALC-Research WSL，Python 3.12.16。

## 真实结果

| 指标 | 结果 |
|---|---:|
| 官方任务成功 | 1/1 |
| 官方断言 | 2/2 通过，无 failures |
| 运行正常结束 | 1/1，status=answered |
| supervisor.complete_task 成功返回次数 | 1 |
| 模型请求 | 15 |
| 执行调用 / 含协作控制的调用 | 15 / 0 |
| 输入 Token | 157,948 |
| 输出 Token | 3,212 |
| 总 Token | 161,160 |
| 缓存输入 Token（输入子集） | 7,168 |
| reasoning Token（输出子集） | 1,404 |
| 缺失 usage 请求 | 0 |
| 实际工具返回 | 19 |
| 工具调用拒绝 | 1 |
| finish_reason=length | 0 |
| 协作请求 / 结构切换 | 0 / 0 |
| 实际 loop 数 | 1 |
| 求解运行时墙钟 | 40.554 秒 |
| 单题端到端墙钟（初始化、求解、保存、评分、关闭） | 62.744 秒 |

最终答案为 `A Love That Never Was`。官方断言验证答案及无意外状态修改；运行结束后才调用评分器。
表中端到端耗时不含进程启动前的数据哈希校验、环境安装或零付费预检；Token 不把缓存和 reasoning 子集重复相加。

有一次模型请求了不在该任务公开 API 目录的接口，适配器明确返回 ValueError。
模型随后通过官方文档找到可用接口并继续，没有程序自动替代调用、兜底答案或付费重跑。
真实流程包括查文档、读取账户/歌单、查询歌曲、核对歌曲详情、调用 supervisor.complete_task。
具体业务参数、账户记录与完整轨迹保留本机，不复制到公共仓库。

## 这次能说明什么

最终 WSL 完整回归 138 项通过，Ruff 通过。旧 V0 官方判题提示字符串有一个已有的
转义 SyntaxWarning，不影响此次测试或 AppWorld；未为消除无关警告扩大改动。

新版 CALC 已能在官方 AppWorld 环境用真实 Flash 请求完成任务，并得到官方评分。
系统允许动态协作，但该题选择全程单 loop；这符合“不为展示动态性强制分派”的设计。
本次没有发生 delegate、merge、fold，因而不能证明这些操作降低了成本，也不能证明优于 MANTA。
merge/fold 的接管与依赖释放目前由状态机测试、WorkBench 真实工具的脚本预检验证；
实际模型在需要分工的任务上是否合理触发，仍需后续固定任务对照。

下一批使用相同模型、API 工具与资源条件，比较 single、initial_static、no_merge_fold、full。
先在明确的 train/dev 开发集合检查触发质量，再固定更多不同任务家族验证质量与总成本。
不能将本题上的 1/1 扩写为 benchmark 总体成功率。

## 结果与复现入口

- 配置：`configs/adaptive.appworld.case1.json`。
- 运行说明与完整命令：`docs/APPWORLD_RUNBOOK.md`。
- 数据锁：`D:\CALC-experiments\configs\appworld-case1-v2.lock.json`（94 个资产文件）。
- 运行根目录：`D:\CALC-experiments\runs\appworld-task-progress-case1-v1`。
- 正式结果：`full\execute\summary.json`。
- 单题结果、官方评测、逐事件轨迹：`full\execute\82e2fac_1\{result.json,evaluation.json,trace.jsonl}`。
- 实际代码/配置/AppWorld 解包源码哈希：`full\execute\manifest.json`。
- 官方原生输出：`D:\CALC-experiments\data\appworld\experiments\outputs\calc-appworld-task-progress-case1-v1-full-run\tasks\82e2fac_1`。
- 预检：`full\preflight`，模型请求0，文档查询后官方评分为 false（预期，非模型成绩）。
- D 盘备份：`D:\CALC-task-progress-backup`，文件 SHA256 校验清单一起保存。

早期 Windows 原生初始化、依赖兼容检查失败均为零模型调用，记录保留在
`appworld-task-progress-dev3-v1` 与 `appworld-task-progress-dev3-v2`，不混入本题得分或付费请求。

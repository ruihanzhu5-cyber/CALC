# CALC V1 首版代码与 WorkBench 接入

日期：2026-11-01。当前交付是可执行代码、离线验证和基线核查；真实模型实验尚未启动，不包含准确率提升结论。

## 已实现

- `src/calc/adaptive.py`：纯 API、固定操作的多循环运行时。Main/Worker 均可分派；sequence 保留前后依赖，parallel 可并发请求，review_refine 具有独立核查者和后续修正者。Worker 子任务返回该 Worker。
- `merge`：多个兄弟 loop 的未完职责进入一个现有兄弟 loop；`fold`：子 loop 的工作和能力进入父 loop，后续工具在父 loop 执行。原历史归档，可通过 read_history 分页恢复；原始工具结果通过 read_evidence 恢复。
- `complete_transferred_work`：接收者完成一项接管职责后解锁其后继，无需等待整个 Main 完成；不是正确性判分。
- 模型调用并发，工具执行与拓扑迁移在 wave barrier 串行提交。模型并发上限不限制团队人数。单loop的工具批次当前仍串行，不声称已实现工具并发。
- 新子工具结果/回答/失败等事件唤醒父节点，Main可以主动merge/fold。低档模型提出改变后由高档模型审核；Main高档模型自己的决定直接执行。控制调用纳入usage。
- 模型分工：`deepseek-v4-pro`与`deepseek-flash`，同家族即可。接口ID已对照 DeepSeek 官方文档；并未发送真实请求验证账户权限。支持升级，不支持自动降级。
- API无隐藏重试。每个执行/审批请求记录真实返回usage；缺usage单独计数，不能当作已知零。没有默认累计Token或请求数预算，没有Agent人数上限。

当前限制：迁移整个来源loop的未完职责，不支持任意部分职责迁移；触发仍是API语义判断，没有训练器；父节点检查点开销需要真实实验检验；不保证API模型一定能合理使用这些操作。

## 作者原版 MANTA 基线

固定提交：`3da40879d690a25459cc401292e5c6f0cc366d84`。

独立目录：`D:\CALC-experiments\upstreams\MANTA-native`，detached HEAD；已在线核实是作者 `mao-code/MANTA` 提交。没有覆盖 C 盘研究分支，也没有把本地 retirement 修改带进去。作者原有事务保护保留。

历史核查见 MANTA_LOCAL_AUDIT_20261101.md。旧 WorkBench 30题×3次的66/90成功仅为历史诊断；有模型/在线经验更新配置差别，且旧计量可能含估算，不拼入新实验。

首次实际对照先采用共同 Flash 骨干，再比较 CALC Pro+Flash。MANTA保留原生规划、审查、写协议、修复次数和经验更新设置；更改模型与API端点需要记录为共同骨干复现，不能冒称论文原模型成绩。模板/提示/任务清单在正式评测前冻结。

## 数据和评估

数据副本：`D:\CALC-experiments\data\workbench`。multi_domain/v1 共210题，12个必需CSV均已校验SHA256。

双方共用固定 MANTA 的 WorkBench 适配器与状态变化评分语义，执行只改变本地 pandas 沙箱，不发送真实邮件。评分不需要另一个模型。此处复用的是 MANTA 对 WorkBench 的适配实现，不把它说成未经核对的独立官方pip评分器。

`scripts/run_adaptive_workbench.py` 只向actor传入任务文字、日期/时间约束和工具schema；gold与模板字段留在评分侧。每题新建沙箱。工具真实执行的动作交给评分器，不能只保留有利分支的操作；completion与state success分开报告。

## 运行入口

复用已有Python环境（数据与新代码在D盘）：

```powershell
$python = 'C:\Users\larei\Documents\ChatGPT\manta\.venv\Scripts\python.exe'
Set-Location D:\CALC-experiments\code\CALC
& $python -B scripts\run_adaptive_workbench.py --config configs\adaptive.workbench.example.json
& $python -B scripts\check_adaptive_workbench.py
```

第一条是默认零请求预检；第二条用脚本响应驱动真实沙箱执行，检验fold后Main继续调用工具及原生评分。它刻意不完成原题，期望评分为false，不能作为模型成绩。

真实API入口是在同一命令末尾加 `--execute`。密钥由 `DEEPSEEK_API_KEY` 环境变量提供，不写配置文件。输出目录必须全新，不覆盖旧结果、不自动重跑。初始样例仅 multi_domain_0 一题。单次输出4096与固定作者源码默认一致；`max_waves=null`，没有累计Token/100请求预算。需要改限制时须在配置显式记录并与对照说明。

真实输出包含 manifest（源码/数据hash、模型参数、skills）、每题trace、result、evaluation和summary。新运行前应另存固定配置，不直接把历史输出当新结果。

## 本次验证证据

- 新协作运行时10项测试通过，覆盖并行、顺序、Worker再分派、merge/fold、原始历史恢复、Main主动fold、职责解锁、截断/缺usage/传输失败。
- 完整CALC离线回归：120项通过。早先两次环境临时目录失败已在D盘独立测试目录解决，非算法失败。
- 固定作者checkout + D盘数据预检通过：210题、12资产hash、空执行判错、模型请求0。
- 真实WorkBench沙箱贯通：6次脚本决策、3次真实本地工具调用、子loop折回后Main继续执行；runtime完成，benchmark判错符合预期；外部API请求0。
- 独立审查发现并修复顺序fold死锁、父节点无法主动切换两项阻塞；第二轮无同等级阻塞。完整审查历史见 CALC_V1_CODE_REVIEW_20261101.md。

后续首先验证真实工具协议、正常交卷和usage，再扩展到冻结开发清单；本轮未启动付费批次。

## 参考

- https://github.com/anthropics/single-agent-loop-kit/blob/release/reference_loop/loop.py
- https://github.com/mao-code/MANTA/commit/3da40879d690a25459cc401292e5c6f0cc366d84
- https://api-docs.deepseek.com/quick_start/pricing/

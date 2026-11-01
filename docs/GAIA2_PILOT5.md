# GAIA2 五题开发对照

两方法各一次、固定五题，不是论文主表复现或 SOTA 结论。模型均为 DeepSeek Flash。
任务来自官方 Adaptability validation，按 SHA256(`calc-gaia2-pilot5:` + scenario_id) 排序取前五，
未依据参考答案、难度或模型结果筛选。ID 和资产 SHA 在 D:/CALC-experiments/data/gaia2/pilot5.lock.json。

- scenario_universe_29_aa11lh
- scenario_universe_22_h34zyy
- scenario_universe_21_nc6nqf
- scenario_universe_29_096dyu
- scenario_universe_23_ekcbfh

## 来源与配置

ARE 官方代码 a9fd2edccb4bc7e22fbf45c8482a5fef30a2a5a4；GAIA2 数据版本
78ea3bdbdeec2bdcd6afa5420915d8a22f23ed99；官方文件系统版本
132e26376f5e963bb59f64bcccdd02188cb08dee。独立环境 `/opt/calc/envs/gaia2` 位于 D 盘 WSL。

MANTA 原代码 3da40879d690a25459cc401292e5c6f0cc366d84 未修改。
调用原 MASRunner/self_evolved，按论文表 5 设置初始最多5、总计最多10、1次修复、
最多2个外层轮次、hybrid 审计、元决策温度0、skill批次12。
本批只有5题，无人为触发skill反思。单次输出使用作者原生4096。
GAIA2不在原文实验内，没有作者GAIA2专用工具迭代设置；本适配明确采用
MASRunner 原生每个工具循环8次默认值。原生 transactional_star 写操作保护不改，
可能将初始团队收缩；实际拓扑与回退必须按轨迹报告。
原论文骨干是Gemma，改用Flash是同模型开发对照，不宣称原论文分数复现。
原始 skill 只读引用，不混入此前 WorkBench 运行产生的更新。

CALC 使用 AdaptiveRuntime/full，递归分派、merge/fold，3路模型并发，输出4096，
无额外累计Token、总模型请求或Agent数量上限。普通工具结果本地处理，
公开环境通知在波次边界进入各活跃loop并产生进度决策机会；用户后续轮次保留原历史。
仍有波次同步边界，不能宣称抢占式/瞬时响应。业务工具提交串行。

两方法均使用同一个适配器，在各自独立重置的任务环境运行；同题内所有Agent共享环境。
MANTA每次模型请求读取公开通知快照；不改其审计、拓扑提示或修复逻辑。
后续环境轮次再次调用原runner，传入公开新消息；这属于新增GAIA2适配，不是作者原生GAIA2实现。
LLM请求采用官方measured时间思想，暂停环境后按真实调用耗时推进；CALC并发请求按重叠时间段推进。
采用ARE默认非Time场景1800秒模拟时限，无额外实验累计Token/请求预算。

官方GraphPerEventJudge负责事件检查、语义检查及轮次推进，Flash仅作为其模型传输后端。
不修改官方评分规则。oracle仅用于官方预处理及判分，不输入actor。
因官方多轮环境会通过判分推进下一轮，judge可能在执行期间调用；judge请求与actor请求分开计量。
最终scenario.validate输出success/exception/rationale，不自行转换未知为通过。
发送最终文本时，如该轮没有工具发送用户消息，适配器按ARE接口提交一次文本；不生成或改写答案。

## 命令

在WSL中，DEEPSEEK_API_KEY由环境注入，不写配置或日志：

```bash
cd /mnt/d/CALC-experiments/code/CALC-task-progress
export PYTHONPATH=$PWD/src TMPDIR=/opt/calc/tmp HF_HOME=/opt/calc/cache/huggingface
export XDG_CACHE_HOME=/opt/calc/cache PYTHONDONTWRITEBYTECODE=1
# 零模型调用，官方oracle初始化/工具/入口检查，不产生benchmark成绩。
/opt/calc/envs/gaia2/bin/python scripts/run_gaia2_batch.py --config configs/adaptive.gaia2.pilot5.json
# 用户授权的两方法各五题，两方法并行、各方法内顺序，每题独立进程。
/opt/calc/envs/gaia2/bin/python scripts/run_gaia2_batch.py --config configs/adaptive.gaia2.pilot5.json --execute
```

结果根目录 `D:/CALC-experiments/runs/gaia2-adaptability5-flash-v1`。
每题记录manifest、真实请求usage、公开工具轨迹、官方完整轨迹、最终评分；
错误保留failure.json、未知usage单列；不覆盖、不自动重跑。
队列出现执行故障时停止该方法的剩余任务，正常判错则继续。
10项覆盖前不能称批次完成。官方完整轨迹含评测信息，仅用于离线审计，不回灌模型。

## 本地验证记录

2026-11-01：五个锁定场景分别通过官方环境初始化、公开工具调用与原生 MANTA 配置导入；
全部预检为零模型调用。完整测试 161 passed，新增代码 Ruff 通过。
依赖版本见 `configs/gaia2.environment.freeze.txt`。
后台入口为 `scripts/run_gaia2_durable.ps1`，通过 Windows 计划任务独立运行 WSL；
执行队列或启动回执已存在时拒绝重启，防止重复付费。

## 首次执行的传输兼容修正

MANTA 首题在原 `MAS/llm.py` 重复工具调用提前终止路径中留下尚未执行的 tool_call_id，
原 `_force_final_response` 请求被 DeepSeek 以 HTTP 400 拒绝。该次结果为基础设施失败，
不能作为 MANTA 任务能力失败的证据；原轨迹、165154 个已报告 Token 和1次未知 usage 保留。
新增 `manta_transport.py` 仅在原生强制终答请求中给未配对 ID 补充真实的 `not_executed` 状态，
不执行剩余工具、不提供虚构结果、不改变作者的拓扑或早停规则；每次协议补齐单独写事件。
非该路径的协议错误仍直接报错，不额外调用模型。163 项回归及 Ruff 通过。
四个尚未尝试的 MANTA 任务使用显式子队列 `manta_remaining_queue.json` 继续，
首题不在该子队列内；原队列的四个 queued 条目应结合子队列解读，不可重复启动。

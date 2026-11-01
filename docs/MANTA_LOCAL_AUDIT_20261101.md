# MANTA 本机复现资产与首轮数据集核查

核查日期：2026-11-01（Asia/Shanghai）。只读核查历史文件、Git 元数据及代码；未读取密钥，未启动付费模型或旧队列。运行了一次零模型调用的 WorkBench 数据加载与评分正负例检查。

## 结论

MANTA 可以作为首轮唯一外部基线。优先选择 **WorkBench / multi_domain / v1**：本机数据与 Python 环境现成，工具执行是本地表格沙箱，状态评分无需外部判题模型；跨域任务具有独立读取、依赖执行、证据交接和最终写操作，适合检验 CALC 的分派、merge、fold。

MANTA 需要从作者提交建立独立 checkout。用户现有研究分支和 D 盘 reference 快照均不能直接贴成“原版 MANTA”。旧日志用于调试与规模估计，不能与未来 CALC 分数拼成公平对比。

## 已找到的代码与环境

| 资产 | 本机位置 | 核查结果 |
|---|---|---|
| 长期研究工作区 | `C:\Users\larei\Documents\ChatGPT\manta` | HEAD `8057f15c773528e31739fd98bc7bd1133ac09d9e`；当前分支 `research/appworld-b0-v02-paid-clean`，有多条 retirement / handoff / AppWorld 研究分支 |
| 作者远程引用 | 同工作区 `origin/main` | `3da40879d690a25459cc401292e5c6f0cc366d84`；remote.origin 为 `https://github.com/mao-code/MANTA.git`，已在线确认作者提交存在 |
| D 盘参考快照 | `D:\baseline_references\MANTA` | HEAD `75a3f5780f3178289289ed1461b6f7d6cfd5d042`，remote.origin 是用户 fork；不是独立核验的作者原生工作区 |
| 现成 Python | `C:\Users\larei\Documents\ChatGPT\manta\.venv\Scripts\python.exe` | 成功导入 WorkBench、加载任务、执行本地评分；首次导入较慢 |
| 数据缓存 | `C:\Users\larei\Documents\ChatGPT\manta\.cache\workbench` | 12 个必需 CSV 存在：6个工具状态/地址文件，6个 v1 任务文件 |
| 历史实验 | `D:\MANTA_DATA\experiments` | 包含 DeepSeek 的 WorkBench、BrowseComp、MATH-500 分片及汇总目录 |

当前 C 盘工作树与作者 `origin/main` 比较，`MAS/llm.py`、`benchmark/workbench/__init__.py` 都有修改，且新增 `MAS/self_evolved/retirement.py`。保留原目录，仅复用环境和数据；新的公平基线应固定作者代码及必要的 API 适配 diff。

特别注意：`transaction.py` 和 `transaction_committed` **也存在于作者上游**，不能仅凭此判断用户改造。作者提交 3da4087 说明 `transactional_star` 仍是默认写协议，新增 `commit_once` 为可选；本轮不能默默删除这类基线机制。

## 历史结果：按原始分片去重

每行只统计指定独立 worker 目录的 `*/run_*.result.json`；不再加上复制到正式目录的同一份结果。

| 原始分片组 | 数据 | 独立任务数 | run 记录 | completion=true | success=true |
|---|---|---:|---:|---:|---:|
| `manta_dsflash_workbench6_20261005_2145_w0` … `w5` | WorkBench | 30 | 90 | 90 | 66 / 90（73.33%） |
| `manta_dsflash_math6_20261005_2100_w0` … `w5` | MATH-500 | 30 | 90 | 90 | 87 / 90（96.67%） |
| `manta_dsflash_parallel3_20261005_2120_w0` … `w5`，只取 browsecomp 子目录 | BrowseComp 适配 | 28 | 83 | 83 | 68；原目标90次尚缺7次，不作为完整得分 |

WorkBench 90次中78次 `final_reason=self_evolved:transaction_committed`，12次 `consensus_reached`。模型名称在历史汇总为 `deepseek-flash`。每次任务3个run，不能把90次称为90道独立题。

成本限制：旧 trace `token_in + token_out` 字段和分别是 WorkBench 33,841,034、MATH-500 2,265,084、BrowseComp 35,707,506。**这些是旧 trace 计量，不能称已核实真实账单**：旧 `MAS/llm.py` 在 usage 缺失时可能估计 Token，一次 act 事件可聚合多个 API 请求。WorkBench 963个有Token事件不等于963次API请求。历史 `cost_total=0` 不表示实际免费。未从原始逐请求响应完成完整请求/费用核算。

`DEEPSEEK_FLASH_REPRODUCTION.md` 明确记录：并行分片把 `skill_update_batch_size=0`，关闭跨题在线 skill 反思。因此这些是 DeepSeek 骨干上的并行方法变体，不是论文原模型、顺序在线自演化协议的精确复现。历史台账还说明运行时 dirty tree 未完整封存，不能把今天的 HEAD 回填为每次运行版本。

## 为什么先选 WorkBench

| 候选 | 操作成本与现状 | 首轮判断 |
|---|---|---|
| WorkBench multi_domain v1 | 本地 CSV；本地工具；无需检索服务、Docker 或 Qwen 判题；已有完整30×3历史 | 首选；固定同一数据和状态评分器，关注重复读取与职责交接 |
| BrowseComp-Plus | 需要检索语料/服务，前期已有长轨迹与服务故障；历史MANTA目标仍缺部分run | 保留为后续复杂检索验证，不作为最快的第一闭环 |
| MATH-500 | 任务加载简单，工具依赖少；历史87/90成功 | 易启动但当前骨干接近顶格，协作/上下文交接信号弱，不优先 |

WorkBench 不是声称一定最能证明改进：其状态写入依赖要求也可能让过多并行无益，恰好可以检验 CALC 是否能合并和收拢不必要的独立循环。应同时记录正确率与错误副作用，而非只看自然语言完成声明。

## 数据和零调用评分核查

`multi_domain/v1` 实际加载210题，首个ID为 `multi_domain_0`，首题提供10个工具。

任务CSV：`C:\Users\larei\Documents\ChatGPT\manta\.cache\workbench\data\processed\tasks_and_outcomes\v1\multi_domain_tasks_and_outcomes.csv`

SHA256：`C4DC69491D81D12CEA9D6E18181DBEB82B351487B8922B3C17A6128CECCAC83A`

在评分侧用第0题官方动作列表回放得到 `success=True`；空动作加“Done”得到 `success=False`；模型调用为0。该检查验证评分入口能区分执行和口头交卷，不是模型实验成绩。当前验证使用现成研究环境，新的基线 checkout 仍需重复同样离线检查。

## CALC 可接入接口

固定作者 checkout 后，复用 `benchmark.workbench` 的数据和工具适配，不使用其 agent 调度实现作为 CALC 方法。

```python
from benchmark.workbench import WorkBenchBenchmark, WorkBenchSandbox

benchmark = WorkBenchBenchmark({
    "data_dir": "<frozen-workbench-cache>",
    "domain": "multi_domain",
    "tasks_version": "v1",
    "tool_selection": "domains",
})
tasks = benchmark.load_tasks()
sandbox = WorkBenchSandbox(benchmark.data_dir)
tools = benchmark._build_tools(sandbox, tasks[0].metadata["domains"])
# 每项含 name / description / parameters / handler；作者新版本还标注副作用。
# CALC 调用 handler 并保留真实调用，最终使用同一 adapter.evaluate。
```

- `_ensure_data_exists` 会下载缺失文件，预检必须先检查资产，不能把空缓存误当离线。
- `WorkBenchBenchmark.run` 原生提示包含固定时间 **2023-11-30 00:00:00**、办公时段 **09:00–18:00**；CALC 应保持相同任务约束。
- `metadata.answer` 是 gold 动作，只供评分；`base_template/chosen_template` 也不进入 actor。模型只接收题目和共同工具描述。
- `evaluate(task, final_answer, run_metadata={"function_calls": calls, "error": ""})` 返回 score/success/details，按新沙箱回放动作后的状态比较。作者原版 commit-once 配置下还需按其约定使用已提交动作，不能计入仅提议未执行的写操作。
- 本地 WorkBench 是 MANTA 对上游任务和状态语义的适配，不能宣称直接调用了上游原封不动的评分模块；双方共享同一冻结适配器，保留协议差异说明。
- 并行读与串行写应在真实沙箱层明确；多个 Agent 重复写可能改变结果，不能为了让分数好看在评分侧删除真实执行的错误写操作。

## 基线可用性与待办

可用：作者代码公开、有可固定提交、本机有资产和运行经验，方法直接研究动态协作。

新对照开跑前必须固定：作者源码及 API 适配diff、原生写协议/终止/agent数量设置、初始playbook和是否跨题更新、实际任务ID、模型版本/输出设置、完整真实usage记录。CALC不强制人数，不等于改写MANTA作者自身的人数限制。旧结果不纳入新公平主表。

首轮建议先1题每方法各1次核对轨迹/评分，再扩到同一预先固定开发集。使用历史30题调试时明确是已见开发题；正式评估选择其余预先冻结ID并保留不同任务模板分布。不能看新得分后挑题。

## 主要证据

- 本地 `C:\Users\larei\Documents\ChatGPT\manta\EXPERIMENT_LEDGER.md`
- 本地 `C:\Users\larei\Documents\ChatGPT\manta\DEEPSEEK_FLASH_REPRODUCTION.md`
- 本地 `D:\MANTA_DATA\experiments\manta_dsflash_workbench6_20261005_2145_w0\workbench\self_evolved\multi_domain_0\run_0.result.json` 及其余90次原始记录
- [MANTA 作者提交 3da4087](https://github.com/mao-code/MANTA/commit/3da40879d690a25459cc401292e5c6f0cc366d84)
- [WorkBench 官方仓库](https://github.com/olly-styles/WorkBench)

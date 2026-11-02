# V7：按未完工作修订协作操作

分支：`feat/progress-operator-revision`。起点：`3b59558fadf23ce4fbaa2038168a9fb5966c833b`，已通过 fetch 确认原开发分支远端仍指向该提交。本轮没有从 main 重新搭骨架。旧实验和配置保留。

## 这轮修的实际问题

V6 的两道 AppWorld 真实任务都正常提交并判对，但没有展开协作。轨迹显示：编译器生成的是按数据源分支的候选，后续选择接口只允许接受这些候选或 keep；模型无法在这个决策机会中改成更适合当前未完工作的分工。此外 keep 附带正确 covered_work_ids 仍会被条件 Schema 拒绝。不能把这两点直接归因为“题目太简单”。

V7 改进现有调度器和接管运行时，没有增加新框架、额外 Judge、训练步骤、图结构或默认预算。

## 核心 Python 在哪里

- `src/calc/progress.py`：WorkReport，保存当前职责、进度、完成条件、未解决问题、失败路线和下一步。
- `src/calc/triggers.py`：compile_candidate，识别可以重新考虑协作的状态，编译可执行示例。
- `src/calc/scheduling.py`：scoped_revision_tool、continuation_panel，提供合法修订接口和后续工作对照。
- `src/calc/adaptive.py`：_accept_decision → change → _apply_change，校验并落实操作；_accept 检查所有权版本。
- `docs/excerpts/progress_operator_core.py`：从上述真实实现自动提取的阅读快照，带原始路径、行号和 SHA256。它保留方法的 self 参数与外部依赖，不是另一份运行时或独立入口。

重新提取：`python scripts/export_collaboration_core.py`。

## 思想如何逐步落实

### 1. 用工作状态表达“还剩什么”，不直接优化一张图

每个 loop 的 WorkReport 保存：current_scope、progress、completion_condition、unresolved、failed_routes、next_step。另有 subgoals 及依赖、状态。这些信息与当前所有者、版本、证据和历史引用一起进入决策快照。

工作描述由模型报告；程序保证结构、引用和版本正确，不把语言描述冒充已验证的任务完成或真实贡献分数。

### 2. 程序打开决策机会，不自动决定分工

保留已有完成、失败、阻塞、依赖变化、重复访问等事件。普通工具结果继续留在执行者，不会为每个结果都运行一次 Judge。

新增报告驱动的候选：当前版本报告中，至少两个 open 子目标的已声明前置依赖都为 done 时，可以生成并行/顺序候选；已完成、blocked、依赖未满足和旧版本报告不进入这个候选。两个目标是多分支候选的结构条件，不是性能阈值，也不证明语义独立。

保留公开只读资源元数据路径。因此新机制不以模型必须先 report_progress 为前提，也不以 benchmark 名称或答案为条件。

收拢机会扩展到有重叠/输出压力事实的普通 Worker，不再要求它必须贴有 read_only 标签。仅编译候选；实际权限、嵌套职责和依赖约束仍由原接管运行时校验。

### 3. LLM 可以在原调度机会中重写分工

候选比较阶段现在暴露两个工具，要求一次响应只调用一个：

- commit_collaboration：接受一个建议，或者 keep。
- revise_collaboration：给出 reason、next_work、proposal，用既有固定操作库重写工作安排。

模型可以改变分支目标、数量、协作方式，或提出允许的 merge/fold。它无需伪造快照、事件版本或证据 ID；这些由运行时绑定。普通求解调用不会暴露这个专用控制工具。

修订经过 Schema、能力目录、实验操作掩码、版本和实际转移 preview 校验后，走现有 change。Main 不需要再做一轮同主体确认；Worker 的请求仍须父节点审批，父节点拒绝后 Worker 可继续原会话。不能把“无需再次确认”误解为绕过父节点权限。

原始自拟 candidate 的两阶段路径保留；这次减少的是候选比较阶段重新设计分工时的额外审批，不宣称所有控制调用都合成一次。

### 4. 比较剩余工作，而不只盯着下一次输入

成本面板新增 continuation：每个实际所有者的未完职责、完成条件、问题、依赖、下一步及迁移职责。等待父节点与可运行 Worker 分开显示；待执行输入总量与 ready 输入总量分别列出。

对“展开后等待汇总”的候选，额外显示条件表达式：

```text
假设每个分支还有同样的 k 次求解，当前输入长度不再增长，最后汇总一次：
keep 输入字节调用量      = k × 分支数 × 当前父输入大小 + 当前父输入大小
candidate 输入字节调用量 = k × 各分支输入大小之和 + 交接后父输入大小
```

k 没有默认赋值。该表达式只是敏感性对照，明确忽略未来上下文增长、输出 Token 和控制调用，单位也不是 Token、费用或墙钟；不作为自动阈值，不伪称已校准的价值估计。实际缺失 usage 继续保留未知。

模型仍需判断上下文隔离、独立推进、等待和交接风险是否值得。我们没有实现一个已校准的“独立价值分数”。本轮也没有获得新的省 Token 结论。

### 5. 展开和收拢都必须产生真实执行后果

展开继续复用 _apply_change：新 Worker 获得任务、完成条件、能力范围、证据与冻结历史入口；sequence/review_refine 绑定前驱依赖。

merge/fold 继续只迁移整个 loop 的未完职责，不支持任意部分迁移。接管胶囊保留未解决问题、失败路线、下一步、技能、证据和历史。来源标记 merged/folded 并改变所有权 epoch；后续旧模型响应被 _accept 丢弃，不能再提交工具。

接收者真实执行后续工具，使用 complete_transferred_work 完成来源职责，才释放依赖来源的后继。收拢与原任务完成是两个不同状态。

模型请求仍可并发；组织变化在返回屏障提交，共享环境业务工具仍按现有顺序提交，不为每个分支复制任务环境。

## 借鉴来源与独立实现边界

| 来源 | 借鉴的设计 | 本轮边界 |
|---|---|---|
| [EAT](https://github.com/caoshiyi/EAT/blob/0a90500b5f87c26d2fb11013b95591dcf81ed0f8/agent_team/SUPERVISOR.md)，Apache-2.0 | 执行与明确组织重评估阶段分开，围绕进展修改组织 | 复用现有 CALC 显式阶段，补上候选修订，不复制整套主管 shell 或在线官方评分 |
| [EvoRouter](https://github.com/CenYangtze/EvoRouter/blob/eb3a615b437ba7b584238473020bfa03c70950c1/MAR/MasRouter/llm_coordinator_router.py)，Apache-2.0 | 固定模式与具体配置明确表示，结合后续工作看成本 | 不复制训练系统，不声称纯 Flash 得到其训练收益 |
| [POrchestra](https://github.com/XueyangFeng/POrchestra/blob/371aef619aec6f2918690a2fbaf9bf797b3025d3/porchestra/tools/delegate.py)，整体许可未确认 | revise_active 的同会话连续性，普通工具局部执行 | 独立实现接口思路，保留会话/历史；不复制该源码 |
| [Codex](https://github.com/openai/codex/blob/25af12f7e61572b0bc18ddb1008be543b91519b0/codex-rs/core/src/tools/handlers/multi_agents_v2/wait.rs) | 事件到达与执行结果管理 | 沿用已有事件/通知及执行屏障，没有引入 Codex 依赖 |

新增代码为 CALC 独立实现，没有把调研项目整体拼入运行时。

## 验证与运行

本轮使用 `CALC-Research` WSL，虚拟盘 `D:\WSL\CALC-Research\ext4.vhdx`，环境 `/opt/calc/envs/appworld`，源码、pytest 产物及缓存写在 D 盘或该 D 盘虚拟盘中。

```bash
cd /mnt/d/CALC-experiments/code/CALC-task-progress
export TMPDIR=/opt/calc/tmp
export PYTHONPYCACHEPREFIX=/opt/calc/cache/pycache
export PYTHONPATH="$PWD/src"
/opt/calc/envs/appworld/bin/python -m pytest -q

# 官方 AppWorld 接口集成：脚本决策、真实共享环境、零模型付费、没有官方任务评分
CALC_APPWORLD_LIVE_CONFIG="$PWD/configs/adaptive.appworld.example.json" \
  /opt/calc/envs/appworld/bin/python -m pytest tests/test_appworld_live_collaboration.py -q \
  --basetemp=/mnt/d/CALC-experiments/test-temp/progress-operator-live
```

新增状态机验证覆盖：正确 keep 范围、自拟修订改变目标/人数/方式后真实执行、无效修订原子拒绝、过期修订、merge/fold 后历史与工具接管、旧响应丢弃、职责完成释放后继、Worker 父节点权限、实验掩码、无未来使用量时保留未知、基于当前报告的工作前沿去重。

最终验证：常规全套 **410 passed、2 skipped**，两项 skip 为显式 opt-in 的官方环境检查；该官方 AppWorld 集成另行启用运行 **2 passed**。Ruff 与 `git diff --check` 通过。官方依赖有弃用警告，未修改上游环境代码。官方检查未调用模型、未读取任务评测分数。

初次全套测试的 CLI 子进程缺少 PYTHONPATH；明确导出源码路径后通过，未改 CLI 代码。通用 calc 环境缺 jsonschema，因此验证改用已有 AppWorld 环境，没有为此修改方法或增加依赖。

本轮不启动新的付费 case。下一批仍用相同 Flash、工具、任务与显式资源配置，分别记录任务评分、正常完成、控制/执行调用、真实输入输出 Token、修订与实际切换；必须把接口贯通与方法收益分开报告。

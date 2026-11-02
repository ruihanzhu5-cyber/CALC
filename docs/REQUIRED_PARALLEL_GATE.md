# Required-parallel：把协作要求落实为运行时边界

## 查到的具体上游机制

本轮首先核对公开源码，不通过修改某道题的提示词制造现象。

- [DynaFlow 7451639 / workflow.py](https://github.com/amiya-special/Dynaflow/blob/7451639d197ef844b4157cf40eadac68e9eba8ca/src/dynaflow/workflow.py)：Forced profile 在没有真实 workflow 时拒绝交卷；有 workflow 尝试后，还要求已完成、有效的 receipt 与正常云端 Agent 执行记录。Main 的工具边界也由 host 执行。借鉴其“调用过、真正执行、有效交付”分开的验收机制；本实现适配为 CALC 自身的 loop、工具证据和所有权，不引入其自由代码生成/Docker框架。
- [EvoRouter eb3a615 / llm_coordinator_router.py](https://github.com/CenYangtze/EvoRouter/blob/eb3a615b437ba7b584238473020bfa03c70950c1/MAR/MasRouter/llm_coordinator_router.py)：不同模式的最低轮次在程序里规范化。说明操作的执行语义可以由程序限定，不必完全留给模型；没有移植其默认轮数上限或训练系统。
- [DeepSeek 官方接口](https://api-docs.deepseek.com/api/create-chat-completion/)：当前文档规定，思考模式不支持 required 和指定函数的 tool_choice，会返回 400。因此保留原模型模式与 auto 传输，依靠 CALC 本地 Schema、执行权限和终态验收，不擅自关闭思考或切换 Beta。

DynaFlow MIT、EvoRouter Apache-2.0；本轮源码为 CALC 独立适配实现，来源如上。

## 显式实验条件

新增 runtime 配置：

```json
"collaboration_requirement": "required_parallel"
```

默认仍为 `none`。required_parallel 需要已有显式调度、编译触发、至少 2 个并发模型槽，以及 full/no_merge_fold 操作配置。这里的“至少两路”是并行实验的逻辑条件，不固定团队人数，也不增加人数、请求或 Token 默认上限。

这是 **required-collaboration 实验条件**，不能在报告中写成默认自主调度自然触发；更不能用它的强制分工频率证明自主策略有优势。

## 程序真正约束的地方

1. 前期 Main 可以查文档、认证并观察任务。编译器遇到多源/工作前沿候选后，记录 collaboration_gate_activated。
2. 该事件中 keep 不再是合法选项；顺序候选不可代替要求的并行。模型可以选已有 parallel，也可以用 revise_collaboration 重新划分目标、人数和具体职责。已完成的分支应删去，不为计数重复执行。
3. 在该读取前沿上，Worker 必须显式 read_only。Main 保留写入、整合与最终提交；工具仍在同一任务环境串行提交，模型请求继续并发。
4. 门未满足时，Main 不能在拒绝调度之后继续包办任务业务调用。能力发现/准备仍可以进行；错误调用明确返回失败，不创建假 Worker、不自动生成替代答案。
5. 原生官方交卷 API 在调用环境之前受检；Main 的纯文本最终回答同样受检。没有交付就不能当作正常完成。

## 什么才算交付

同一次 Main parallel 分派至少有两个 Worker：

- 实际执行并正常返回过业务工具，产生由自己生成的归档证据；
- 完成或明确完成迁移后的职责，有非空结果；
- 业务证据已进入 Main；该分派的其他职责也已经完成。

这构成 collaboration_receipts。只创建 Agent、只查文档、只获取登录信息、只复述 Main 已有证据或口头说“完成”都不能单独满足条件。

AppWorld adapter 根据官方公共接口命名空间，将 api_docs、login、supervisor.show_account_passwords 标为 capability，其余正常返回的业务 API 标为 task。该分类不读取任务 ID、答案或官方评分。其他 adapter 没有提供 category 时，其注册业务工具按 task 处理；不声称这些分类具有统一的语义贡献判定能力。

Receipt 证明执行与交付事实，不证明结果有用或任务正确。任务正确性仍在执行结束后由官方评测判断。日志另需核查真实模型请求重叠，不能仅凭 pattern=parallel 宣称实际并行。

## 上下文共享

分派时把父节点已有 capability 证据加入 Worker 的读取权限，并提供 shared_context_index（证据 ID、操作名及参数），不自动复制其全部内容。Worker 用 read_evidence 取得需要的文档或准备信息；冻结的 read_history 入口继续保留。

这能减少重新查询文档的必要性，但不保证总 Token 一定下降。已有结果整理、Worker 调用、父节点整合、所有控制调用都进入实际计量。

能力发现/登录证据不进入任务工作前沿；它们的重复访问仍记录，但不会触发任务 overlap 或 merge/fold 候选。共同使用一份说明书不能直接证明两个职责冗余。

## 验证与运行

示例配置：`configs/adaptive.appworld.required-parallel.example.json`。保留原 Flash 模型、API 设置和显式资源配置。

```bash
cd /mnt/d/CALC-experiments/code/CALC-task-progress
export PYTHONPATH="$PWD/src"
export TMPDIR=/opt/calc/tmp
export PYTHONPYCACHEPREFIX=/opt/calc/cache/pycache
/opt/calc/envs/appworld/bin/python -m pytest -q

# 官方环境接口集成，脚本决策，零付费；不评分任务
CALC_APPWORLD_LIVE_CONFIG="$PWD/configs/adaptive.appworld.example.json" \
  /opt/calc/envs/appworld/bin/python -m pytest tests/test_appworld_live_collaboration.py -q

# 默认零模型调用预检。付费时使用单独冻结的 run 配置，加 --execute。
/opt/calc/envs/appworld/bin/python scripts/run_adaptive_appworld.py \
  --config configs/adaptive.appworld.required-parallel.example.json
```

状态机测试覆盖默认不强制、不兼容配置拒绝、keep/sequence 掩码、真实执行边界、无副作用交卷拦截、文档不能冒充任务交付、并发 Worker 到父节点写入的先后关系，以及共享文档按索引读取。

本轮验证：常规全套 **421 passed / 4 skipped**；4 项官方环境 opt-in 检查另行启用运行 **4 passed**，包含可选/受约束配置及原提议/修订两条入口。检查使用官方本地环境和脚本决策，零付费模型调用，不评分任务。Ruff 和差异检查通过。

本轮 paid case 仅用于检查受约束协作是否真实执行；与默认 V7 的比较必须显式说明配置不同，不作为公平自主调度收益或 SOTA 结论。

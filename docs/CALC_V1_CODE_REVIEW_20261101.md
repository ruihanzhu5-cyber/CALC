# CALC V1 代码审查（第一轮）

2026-11-01。审查对象：`src/calc/adaptive.py`、`scripts/run_adaptive_workbench.py`、`configs/adaptive.workbench.example.json`、`tests/test_adaptive.py`；对照 `docs/CALC_V1_FIXED_PATTERN_API.md`。只读审查实现，另运行一个零模型调用的依赖迁移复现。未调用付费 API。

结论：**REVISE BEFORE PAID RUN**。已实现有意义的纯 API 运行骨架，fold 后由接收者真实调用工具继续执行，不只是汇总后删除节点。但存在依赖死锁和父节点无法主动观察/改变子团队两个方法级问题。

## 已符合的部分

- 固定 delegate / merge / fold 等操作；sequence、parallel、review_refine 模板；Worker 可以再分派，子任务回到相应父 Worker。
- Main 默认强模型、Worker 默认轻量模型，弱模型提出变更需要强模型审批；控制调用进入真实 usage 计量。
- concurrency 限制同时模型请求，不限制 Agent 数量；`max_waves` 默认空，无隐藏累计 Token 或请求上限。
- 模型请求并发，工具执行和拓扑变更在返回屏障后串行提交，避免正在调用模型的 loop 被中途销毁。
- merge/fold 保留原历史、证据、能力引用；已有 fold 测试验证后续工具调用发生在 Main。
- WorkBench 固定作者提交及资产 hash；gold answer 和模板没有传给 runtime；使用真实执行动作进入同一状态评分器，并分开 completion 与 success。
- transport 失败显式记录尝试和未知 usage，无隐式重试；输出截断不会当正常答案。

## BLOCKING 1：fold 顺序前驱会制造父子依赖死锁

位置：`adaptive.py` 迁移逻辑，初始审查版本约253–284行；调度约365–388行。

复现状态：Main 分派顺序子任务 A→B；A尚未完成，将A fold回Main。当前迁移将B.dependencies从A重写成Main，但Main存在未完成B，不能提交完成；B又只有Main.status=done才能运行。结果形成执行死锁。

零调用复现输出：

```text
main: ready, dependencies=[]
agent_1: folded
agent_2: ready, dependencies=['main'], parent='main'
parent cannot answer while child is live: True
child can run: False
```

建议先实现可验证的小修复：提交迁移前检查重写后的依赖图及祖先/后代等待关系，拒绝这种变更，保证原状态不变。若要支持该类fold，需要工作职责级完成信号，不能用整个Main是否完成代替被接管前驱职责是否完成。

必须新增测试：A→B中fold A到Main被原子拒绝；A与B一起fold到Main能够继续；合法兄弟merge后依赖重定向能正常释放；拒绝路径不调用控制模型、不改变history/goal/status。

## BLOCKING 2：Main 委派后被完全阻塞，不能按过程主动 merge/fold

位置：`delegate` 将actor.status置waiting；`_unblock`只在不存在live_children时唤醒父loop。

现状：Main 分派后直到全部子任务结束都不再请求模型。子任务进行中的重复检索、相互依赖等事件不会给Main带来决策机会。只有某个Worker主动请求merge/fold才会触发变更。因此代码虽允许手动 `change(main, ...)`，真实运行路径中的Main却不能做该项核心决策。

建议：在有新证据/阻塞/子结果等事件的检查点，允许父loop作继续等待或局部变更的决策；标记已消费事件版本，避免无新信息反复唤醒。父loop可正常完成被fold进来的职责，但不能错误提交尚未完成的全局任务。

必须新增测试：Main分派两个持续运行的Worker；Worker产生新信息但未请求协作；Main在它们结束之前获得一次调度机会，主动merge或fold；无新信息时不会无限唤醒父节点/多收费。

## NON-BLOCKING / 明确实现边界

1. **失败通知不统一。** transport异常会向父loop发送“未完工作”消息，但无文本/截断等`no_complete_answer`失败没有相同消息。虽然团队状态包含failed，建议统一携带原因和未完职责，且保留失败原历史以便接管。
2. **scope目前等于整个loop。** merge/fold转移整个goal，没有独立obligation ID或部分工作范围；这是可接受的首版边界，但不能声称完整实现多来源、细粒度scope迁移。
3. **拒绝去重仅在prompt中。** 文档提出按事件版本避免重复决策，代码尚无事件指纹或版本；需结合父节点唤醒机制补上，否则可无限支付相同审批。
4. **模型升级没有降级。** `escalate`永久把该loop置strong；文档“困难环节结束回轻量模型”尚未实现。可首版明确只支持升级，或加显式可审计降级动作。
5. **运行来源manifest不完整。** 已记录作者MANTA和资产hash，但CALC源码版本/dirty diff或hash、完整模型参数（例如temperature）和skills内容未进入manifest。首个真实对照前应补齐，不能仅记录模型名称/base_url。
6. **工具都是串行执行。** 模型调用可并发，但单loop工具批次暂不并行。文档可说参考Anthropic工具循环，不宜声称已复用其并行工具批次实现。
7. **异常落盘。** 任务级意外异常现在会终止batch，可能只有trace没有result/summary终态。建议把状态异常落盘且保留所有已发出的模型计量；不要自动重跑。

## 离线回归建议

现有8项测试覆盖了基础并发、顺序依赖、Worker分派、简单merge、fold实际执行、无效迁移原子性、截断和usage缺失，但未覆盖上面两个阻塞路径。

增补后运行全套既有CALC测试；WorkBench预检使用固定作者checkout和现成本地数据，确认模型调用为0。真实API实验之前再固定具体DeepSeek/GLM型号与输出参数，样例中的SET占位符保持拒绝执行是正确行为。

本报告是第一轮静态及定向离线审查；主Agent修复后应复查，不把旧的通过数当修复后结论。

## 第二轮复查：两项阻塞已解决

复查最新 `adaptive.py` 与 `test_adaptive.py`。结论：**核心运行时可进入受控的小规模真实API验证；本轮未运行任何真实API**。第一轮两个阻塞不再保留为未解决事项；模型参数、manifest及真实数据贯通由主Agent继续完成。

实际验证：

1. `python -B -m pytest tests/test_adaptive.py -q -p no:cacheprovider`：**10 passed**。
2. 额外零模型脚本覆盖连续 **merge→fold**：A→B→C中先将A合并到B，再将B折回Main；A与B的`transferred_to`均更新为Main；无权的C不能完成A的scope；Main分别完成A和B的scope后，C保留原B依赖ID并获得“checked ID=123”结果；原A/B历史引用仍能从Main恢复。全部断言通过。
3. 原顺序fold问题已通过职责级`resolved`解除：被接管职责完成不再要求Main全局任务结束。
4. Main主动fold的新增测试通过：Worker只产生工具结果、没有请求协作，Main仍在后续checkpoint获取决策机会并执行fold。唤醒发生在当前wave响应和变更全部处理之后，不改变正在进行请求的输入历史。

仍需准确表述的边界：

- checkpoint当前对新的子工具结果等事件触发，尚不是实验验证过的高效语义触发器；强模型控制开销需要真实结果计量。
- 整个loop的职责迁移已可执行，任意细粒度obligation迁移尚未实现。
- Main和Worker可选固定操作，但没有训练型策略或校准收益模型，符合纯API路线。
- 本轮通过只证明这些调度/迁移路径的离线行为，不证明模型实际会合理使用操作，也不证明优于MANTA。

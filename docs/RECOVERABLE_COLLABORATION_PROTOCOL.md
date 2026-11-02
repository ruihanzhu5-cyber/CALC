# 无效协作提议的明确拒绝与会话保留

起点25366299c142a4e99435b992604bb364cdfa9468，仍在feat/compiled-collaboration-triggers迭代。不新增运行时模块，不添加题目ID、答案、API名称特例或新默认资源上限。

## 先查证的成熟实现

- [LangGraph ToolNode，ee3c043](https://github.com/langchain-ai/langgraph/blob/ee3c043bddcc514012885167dd5916b15d6e4731/libs/prebuilt/langgraph/prebuilt/tool_node.py)，MIT：默认错误处理识别ToolInvocationError，生成带tool_call_id、status=error的ToolMessage；非此类程序异常继续抛出。借鉴“参数错误是模型可见结果，程序异常不能伪装成参数错误”的边界，不引入LangGraph依赖或图结构。
- [Anthropic loop-kit，c437962](https://github.com/anthropics/single-agent-loop-kit/blob/c43796287b83bec847db923f07131d1cc8de750d/reference_loop/loop.py)，Apache-2.0：_execute/_result为未知工具、执行错误返回匹配真实tool_use_id的错误结果。借鉴真实调用配对和保留会话，不复制其固定预算或宽泛异常捕获。
- [PydanticAI工具错误文档](https://pydantic.dev/docs/ai/tools-toolsets/tools-advanced/)：区分ValidationError、ModelRetry、ToolFailed和传播的程序异常，向模型反馈校验细节。CALC采用失败结果交回原执行者，不增加自动重试器，也不移植其默认重试次数。

本轮为独立实现，未复制上述项目源码。固定LangGraph文件和许可保存在D盘research/task_progress_20261102/source-survey/langgraph-error-handling。

## 实际改动

1. scheduling.py增加DecisionRejected和无参数值泄漏的字段级错误信息；现有动态能力目录/枚举继续使用。
2. AdaptiveRuntime验收先做JSON/Schema/版本/职责/可执行性检查。模型错误明确拒绝，组织关系和未完职责不变；消费本次已观察事件，避免无新信息反复强制调度。不会生成虚假的keep。
3. 错误返回原执行会话；下一次仍是正常求解调用，模型可执行工具、继续原任务或主动提出新提议。不自动补JSON、不静默替换工具名、不隐藏修复调用。
4. protocol.py复用同一个错误消息配对函数处理业务与控制调用。合法信封中的每个真实call ID都有结果；整批无动作。信封缺ID/重复ID等无法合法重放的情况，只存原始trace并返回用户消息，不捏造ID。
5. 状态过期保留原有重新观察路径；API传输异常、内部RuntimeError等仍明确失败，不转成模型参数错误。scheduling_rejections与fatal scheduling_errors分别计数。
6. read_only说明明确包括禁止未知效果、初始化和认证；只有前置准备已完成且传入所需上下文时才适用。未指定则继承父权限，不能扩大只读父权限。该说明不包含任何benchmark或任务特例。

当前仍使用原DeepSeek v1非strict端点，依靠受约束工具定义、运行时验证和明确错误结果；不擅自切Beta或假称服务端保证JSON Schema。模型请求并发和共享环境串行工具提交不变。

## 验证层次

本修订常规全套397 passed、1个官方环境opt-in检查默认skip；该检查在AppWorld环境单独运行1 passed。Ruff及git diff --check通过。官方上游有依赖弃用警告，未修改其固定源码。

- 状态机回归：无效提议后继续执行、无自动keep/调度重试、同事件去重、可修改后再提交、错误候选不部分建队、真实call ID配对、内部异常仍失败。
- 真实响应结构回放：两份历史模型提议保留字段与能力标签，删除任务自然语言和个人内容；有原轨迹SHA。验证这些输入可被明确拒绝而不中断原求解，不把它们改成合法提议。
- 官方AppWorld环境集成：用脚本决策验证拒绝→原loop继续→delegate→两个Worker真实调用官方文档API→返回Main；同一个EvaluationSession/world。该测试不调用模型、不评测任务、不输出模拟成功率。集成脚本明确保持可选收拢候选以专测该条链；此选择只在测试中，不进入方法。
- 随后两道付费case：82e2fac_1、6104387_1，Flash，同一冻结源，官方train环境及评测；没有WorkBench/MANTA重跑。任务评分与机制是否执行分别报告，不能为了展示切换强制分派。

运行中每一次执行/规划/确认/修复反馈引起的正常模型调用均计量。单次输出默认服务端，case Token/请求上限仍显式可选，未增加默认数字。历史失败成本保留，新实验独立目录与源码归档。

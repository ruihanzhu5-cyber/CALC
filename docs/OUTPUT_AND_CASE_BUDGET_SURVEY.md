# 单次输出与 case 预算：源码核查

核查日期 2026-11-02。不能从这几个项目得出“多数工作只设 case 总 Token”的统计结论；单次输出、循环轮次、累计 Token、费用上限在公开实现中并存。

| 项目和固定版本 | 单次输出 | 整任务约束与实际执行语义 |
|---|---|---|
| [Anthropic loop-kit c437962 loop.py](https://github.com/anthropics/single-agent-loop-kit/blob/c43796287b83bec847db923f07131d1cc8de750d/reference_loop/loop.py) | 16000 | 默认 max_turns=25，累计 max_tokens=400000，包含子 Agent；调用后累计，因此可超出。截断/拒绝/上下文耗尽不执行不完整工具，而是终止，不自动分派 |
| [MANTA 3da40879 llm.py](https://github.com/mao-code/MANTA/blob/3da40879d690a25459cc401292e5c6f0cc366d84/MAS/llm.py) | 默认 4096，可由 OPENROUTER_MAX_TOKENS 改写 | 原生工具迭代和 turn/repair 限制不是 case 累计 Token；我们不擅改基线 native 参数 |
| [POrchestra 371aef6 async_llm.py](https://github.com/XueyangFeng/POrchestra/blob/371aef619aec6f2918690a2fbaf9bf797b3025d3/base/engine/async_llm.py) | max_completion_tokens 可选，默认 None；请求只在非 None 时设置 | DelegateTaskTool 有全局/子 Agent 步数约束，不等于累计 Token。路径按固定版本核查，不能外推所有调用方都不传整数 |
| [Magentic-One d07c667 group chat](https://github.com/microsoft/autogen/blob/d07c667a3239ea4ab7af62a53b0f4ff205a1f23d/python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_magentic_one/_magentic_one_group_chat.py) | orchestrator 没有统一写死 4096，取决于 model client | max_turns 默认 20，max_stalls 默认 3；停滞触发重新规划，不是输出截断直接加 Agent |
| [AppWorld 42b5bcf3 官方 o4-mini 配置](https://github.com/StonyBrookNLP/appworld/blob/42b5bcf3cd334fee33f0c37c02070a9f5807add5/experiments/configs/simplified_react_code_agent/openai/o4-mini-2025-04-16-high-reasoning/test_normal.jsonnet) | 示例不显式传单次 max；kwargs 非 None 才传递 | 示例有 max_steps=50、每题费用 10；声明 max_output_tokens_per_task=100000，但该版本 UsageTracker.exceeded(task_id) 没有使用这个 per-task output 字段，不应宣称 100k 已实际执行 |

AppWorld 的最后一点依据是 [usage_tracker.py](https://github.com/StonyBrookNLP/appworld/blob/42b5bcf3cd334fee33f0c37c02070a9f5807add5/experiments/code/common/usage_tracker.py)：配置项存在与执行路径实际检查不是一回事。

[DeepSeek 官方 API 文档](https://api-docs.deepseek.com/api/create-chat-completion/)说明单次生成上限涉及 reasoning 和最终输出；不发送上限也受服务端默认和上下文窗口限制。旧长题最后一次返回 output=4096、reasoning=4096、正文为空，实际未执行该次动作。这一现象既不能当团队冗余，也不能当必须协作的证明。

CALC 的选择是：单次输出默认 None；case 级可选共享 Token/请求预算，覆盖执行和控制，无任意默认数字。它们限制不同对象，不能互相替代。Token 只在 usage 返回后计量，允许在途超出并如实报告；缺 usage 不视为 0；运行外的官方评测单列。

# 原生基线预算核查

核查日期：2026-10-31。代码为本项目固定的作者公开版本；不把论文值、构造函数默认值、公开配置混作同一设置。

## 原作者设置

| 方法 | 论文 | 固定版本公开代码 | 本次采用 |
|---|---|---|---|
| POrchestra | GAIA/GAIA2总300步骤、至多10子Agent、每个默认30步；SWE-Bench总500步、每个50步 | GAIA runner的Main最多`10*4+1=41`次决策；DelegateTaskTool默认总500子Agent步骤、每次30步；没有我们的一百万累计Token上限 | 按公开GAIA runner：41次Main决策、500总子Agent步骤、30步会话、10次attempt；不加独立检索次数上限；不在网关改写输出长度 |
| CLM | BC+当前上下文预算23,560，单次输出4096，100任务turn；编辑turn不计，超限回滚最多6次 | `bcp.yaml`：context28672、reserve2048、max_steps500（注释说明100/500/2000均用过）、max_tokens4096、6次回滚、最后3turn提醒提交；原生LM cap默认`2*steps+24=1024` | 按公开bcp.yaml，保留原生压缩/回滚/收尾；恢复原生1024 LM cap，取消额外100请求限制 |
| DynaFlow | 主Agent上下文131072、单次输出81920；子Agent单次输出65536 | `configs/dynamic.json`主参数max_tokens65536、temperature1、top_p0.95、seed42、question_deadline_seconds=null；host传budgetTotal=null。引擎可选budget只累加成功子Agent输出Token，不累计每轮输入 | 按公开Dynamic配置65536；无附加question deadline/累计Token/请求数硬停；保留原生workflow并发与1000 agent生命周期上限 |

POrchestra和DynaFlow没有作者提供的BC+正式配置，仍是固定代码在公共BC+工具上的移植；本次恢复的是其原生运行约束。
DeepSeek Flash仍为当前共同可用的API骨干，因此不是原论文模型或训练检查点结果的逐项复现。
Main/CALC属于本项目代码，没有“原作者默认”；其参数单独标注，不能冒称作者配置。

来源：

- [POrchestra论文 E.3](https://arxiv.org/html/2610.13485#A5.SS3)：总执行步骤按benchmark统一。
- [公开GAIA runner](https://github.com/XueyangFeng/POrchestra/blob/371aef619aec6f2918690a2fbaf9bf797b3025d3/porchestra/runners/gaia_runner.py)与[delegate默认值](https://github.com/XueyangFeng/POrchestra/blob/371aef619aec6f2918690a2fbaf9bf797b3025d3/porchestra/tools/delegate.py)。
- [CLM论文 Appendix E](https://arxiv.org/html/2609.37725#A5)与[固定版本bcp.yaml](https://github.com/facebookresearch/context-language-models/blob/483198229ab7b90c0eed4651306ab3b3505aaf50/clm/clm_harness/configs/bcp.yaml)。
- [CLM原生预算、回滚和final turn](https://github.com/facebookresearch/context-language-models/blob/483198229ab7b90c0eed4651306ab3b3505aaf50/clm/clm_harness/utils/budget.py)。
- [DynaFlow论文 Appendix D](https://arxiv.org/html/2610.34467#A4)、[Dynamic配置](https://github.com/amiya-special/Dynaflow/blob/7451639d197ef844b4157cf40eadac68e9eba8ca/configs/dynamic.json)、[输出Token预算实现](https://github.com/amiya-special/Dynaflow/blob/7451639d197ef844b4157cf40eadac68e9eba8ca/workflow_runtime/src/engine/budget.ts)、[host传入空预算](https://github.com/amiya-special/Dynaflow/blob/7451639d197ef844b4157cf40eadac68e9eba8ca/workflow_runtime/host.mjs)。

## 我们此前额外加入的限制

每方法每题累计输入+输出100万、最多100次真实请求、网关强制单次输出16384、网关单题请求串行，均是本项目开发试跑约束。
其中100万累计口径与CLM当前上下文、DynaFlow可选输出累计口径不同。此次重跑取消外层硬停和解码改写，网关仅计量与全局并发调度。
不回写已完成旧批次，不把修改后的重跑结果包装成同一协议的一次公平比较。

## 并发

[DeepSeek官方并发文档](https://api-docs.deepseek.com/quick_start/rate_limit/)于核查时列deepseek-flash账户并发2500。
本地WSL有20逻辑CPU、约11.6GB可用内存；本次19任务跨方法同时调度、模型网关32路，保留原生同题workflow并发。
本机API元数据查询确认deepseek-flash上下文1048576、max_output_tokens393216；查询本身不产生做题请求。

## 19路本地检索验收修复

启动前19路完整题面检索/读文档压力检查均超过60秒客户端等待，健康接口仍200。旧服务将Lucene读取与整篇tokenization放在同一全局锁内，且重复请求反复编码相同静态文档。已缩短锁范围，将JVM读取和tokenizer锁分开，并加入256项精确结果LRU及同键请求合并。索引、排序、tokenizer与截断代码保持原语义，缓存返回完整相同JSON而非摘要。离线19线程同键测试确认搜索/原文各只执行一次且输出逐项相等。
这是公共工具服务的吞吐修复，各方法共享。缓存会影响工具延迟，当前仅用于交卷诊断；正式延迟实验需要冻结冷/热缓存协议。

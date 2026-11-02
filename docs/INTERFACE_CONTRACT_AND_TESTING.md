# 通用接口、Benchmark 适配与 Mock 的边界

版本说明：本文记录2536629及之前的缺陷与诊断。后续已实现参数错误反馈和原会话保留，见[RECOVERABLE_COLLABORATION_PROTOCOL.md](RECOVERABLE_COLLABORATION_PROTOCOL.md)；下文“当前错误会终止loop”等为该历史版本状态。

## 本轮事实

2ed9ff9 原三题：WorkBench 正常通过；两道 AppWorld 在初始调度把 checkpoint 填入 evidence_ids，未执行业务工具。90f9a35 取消模型回传证据，用户授权额外补跑两道 AppWorld。

补跑82e2fac_1执行了14次模型请求，101776输入+4946输出=106722 Token，39.68秒，最后主动提出3分支parallel；提议的skills并未注册，预演先报unknown capability。该提议还使用spotify.show_playlist等内部API名作为tools，这些不是AppWorld adapter注册的appworld_api名称，并且自行填写source_family。不能误把skills白名单报错说成已执行到了工具查找错误；它们是同一个候选里的多处不一致。

补跑6104387_1在首次调度提出3分支parallel，2957输入+1683输出=4640 Token，10.34秒，因嵌套proposal缺proposed_next被拒绝。初始阶段没有工具证据，且也填写了未注册工具标签。

两题均官方false、非正常交卷。五次实际任务（原三+补跑二）合计227581 Token、32请求，零缺usage、零在途、零截断。保留的WorkBench只计一次。没有实际团队创建或merge/fold；自动多来源候选trigger_fired仍为0。因此只能支持“显式调度产生了模型分工提议”，不能宣称新的自动编译触发或协作节省已获真实验证。

完整原始记录：`D:\CALC-experiments\runs\calc-v5-appworld-wire-fix1-flash-20261102`。该目录RECOVERY_COMPARISON.md、request_costs.csv、trace_findings.json保存全部尝试与V4对照。没有再次付费重跑。

## 为什么不是按题写补丁

运行时只接收注册能力、公开工具属性、执行观测和职责状态。工具名称枚举从每题环境的注册表生成，不含Spotify专用名称；另一个环境注册什么，就用什么。Task ID只由runner负责加载和记录，不进入这些接口修正规则。不同benchmark仍需实现adapter，不能因此宣称零适配支持所有benchmark。

Core研究逻辑（事件/候选/选择/迁移）保持同一份实现；adapter负责工具定义/调用、公共读写元数据、共享环境及评分生命周期。AppWorld与WorkBench已提供读写属性，GAIA2未知效果不猜测，也不启用自动多来源读取编译。这是实际支持边界。

## 修复后的合同

- 调度模型看到真实business_capabilities、registered_skills，不以底层操作label冒充工具名。
- 工具与技能参数按当前可用名称生成schema枚举；没有技能时不填或填空数组。运行时再次严格校验。
- reason/next_work只在外层声明一次，内部迁移结构由正常编译绑定；不是接收缺字段的旧包后临时猜值。
- checkpoint、snapshot、source_family和证据绑定由运行时负责。模型没有给未知名称创建能力的权限。
- 非法提议仍不被静默修复、改写成keep或自动付费重试。当前错误会终止loop，这个故障处置策略仍偏脆；明确拒绝提议但保留求解状态的错误协议尚未在本修订中实现。

相关实现：scheduling.scoped_decision_tool/normalize_candidate；triggers.control_messages；AdaptiveRuntime请求与验收使用同一份动态schema。386 tests passed，Ruff passed；该接口修订尚无新的付费case结果。

## 大型项目与论文的参考

1. [SWE-agent论文](https://arxiv.org/abs/2405.15793)研究Agent-Computer Interface如何影响任务性能。接口是Agent使用环境的一部分，不是与推理结果无关的包装；不能据此把我们修字段包装成等量创新。
2. [Anthropic Writing effective tools](https://www.anthropic.com/research/writing-tools-for-agents)强调明确命名空间、对Agent友好的工具响应、真实任务评测、轨迹审查和留出任务验证。对CALC的启示是按通用合同修接口，而非根据某题答案增加工具捷径。
3. [Inspect Agent协议](https://inspect.aisi.org.uk/agents.html)提供比solver更窄的可组合Agent接口；任务、solver、scorer分别建模。CALC的核心/adapter/host-only evaluator分层遵循同类边界，非照搬整个框架。
4. [DeepSeek工具文档](https://api-docs.deepseek.com/guides/tool_calls/)明确strict需要beta端点和所有function设strict=true，仅支持一定schema子集，object字段有额外要求。我们当前v1请求没有启用strict；因此schema声明不是服务端结构化生成保证。没有直接切beta或声称现有allOf条件schema已兼容strict。即使strict启用，任务语义、当前权限/版本与依赖仍需运行时验证。

## 为什么Mock没抓住

tests/test_explicit_scheduling.py的Client使用手写keep/candidate回包。编写测试的人天然知道字段、工具名和技能名，最初总返回evidence_ids=[]，因此没有覆盖真实模型把checkpoint当证据、把API名当工具或漏嵌套必填字段的生成行为。

测试证明了合法输入下状态机路径和非法输入被拒绝；没有证明模型容易生成合法输入，也没有证明拒绝后任务能继续。把“非法输入能拦住”的绿灯当成“真实任务可完成”是验证范围解释过度。当前增加了这些合同边界的回归，仍不能用386这个数代替真实端到端可靠性。

需要分层报告：纯状态机测试；真实adapter+脚本响应的集成测试；真实模型响应/失败轨迹回放；固定模型和配置下的真实端到端任务。真实模型的契约通过率应包括格式、名称解析、候选可执行性、迁移执行和最终交卷，不能只报JSON解析率。

## 与论文实验的关系

接口是方法可执行性和公平对照的前提。CALC的研究主线仍为按任务进展选择协作并收拢冗余循环，而不是修复工具名本身。共享adapter的改善应同步提供给对照；单Agent、静态方式、禁merge/fold、完整方法使用共同模型、工具、接口与资源配置。先锁定接口，再比较策略；若接口/输出上限同时变更，必须承认混杂，不能都归因于调度。

开发case用于发现类别化缺陷；保留未观察train/dev任务和跨bench任务验证泛化。不要依据基线做错/ours做对筛测试子集。贡献是否足够取决于可说明的机制与可靠证据，不取决于代码行数或堆多少模块。

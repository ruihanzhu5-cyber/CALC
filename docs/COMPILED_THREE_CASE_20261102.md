# CALC V5 三个真实开发 case

运行代码 `2ed9ff93c127df53691bf54ad6da1ac3a0540b68`，分支 feat/compiled-collaboration-triggers，起点 3870fab。全部 deepseek-flash。执行前 380 项测试及 Ruff 通过，官方数据锁/环境预检通过，无付费预检。代码、数据、缓存、临时目录、输出在 D 或 D-backed CALC-Research WSL。

结果目录：`D:\CALC-experiments\runs\calc-v5-compiled-threecase-flash-20261102-1740`。源码 ZIP SHA256 `cf1903f89a29a1e78f7e71876f3b2e114c419af1b0b6043524b0d62505e1fb44`。两个 bench 并发，AppWorld 两题顺序。没有 MANTA 或额外 case。

| Case | 官方通过 | 正常完成 | 输入 Token | 输出 Token | 总 Token | 请求 | 硬候选触发 / 切换 | runtime 秒 | 分类 |
|---|---|---|---:|---:|---:|---:|---|---:|---|
| WorkBench multi_domain_0 | 是 | 是 | 101342 | 8540 | 109882 | 15 | 0 / 0 | 52.52 | 正常单 loop |
| AppWorld 82e2fac_1 | 否 | 否 | 2541 | 354 | 2895 | 1 | 0 / 0 | 2.73 | 首条调度引用错误，业务工具未执行 |
| AppWorld 6104387_1 | 否 | 否 | 2986 | 456 | 3442 | 1 | 0 / 0 | 3.36 | 同上 |

真实合计 116219 Token、17 次 API 请求，全部有 usage，零在途，无截断。官方打分在任务结束后本地执行，无额外 LLM judge 请求。两条接口失败保留分母，不当作“省 Token”或方法能力失败证据。没有自动付费重跑。

## 暴露的问题与修复

两个 AppWorld 初始 DECIDE JSON 语法合法，但都回传 `evidence_ids=["main:cp1"]`；该字符串是事件 checkpoint，不是环境工具的证据。严格校验报 `decision evidence unavailable to this owner`，进而停止 Main。这是接口把运行时已知的事实重复交给模型填写导致的混淆，不是任务复杂性、输出上限、环境崩溃或触发条件判断结果。

后续修复取消决定响应的 evidence_ids 字段和回传义务，candidate 证据由 assert_current 验证后的快照绑定。旧错误响应仍被 additionalProperties=false 拒绝，不自动纠正 ID，不兜底 keep，不增加付费修复调用。保留独立执行阶段的 report_progress/collaborate 证据引用接口。新增回归检查这个协议边界与带真实证据的候选编译，全套 382 项测试和 Ruff 通过。修复后未自动启动任何付费补跑，因此不能把本表标成修复后真实结果。

## WorkBench 比较

上一版成功终态：60264 Token、12 次请求、24.87 秒；本次 109882 Token、15 次、52.52 秒，未取得节省。专门调度调用的 Token 从 12627 降到 8762，但执行路径从 7 次成功工具增至 16 次：新增 6 次 calendar.get_event_information_by_id，search_events 从 2 到 5。不能仅凭控制输入紧凑就宣称总费用降低；额外读取是否必要需按参数/证据另审，不能只按 API 名称断言重复。

V5 取消客户端 4096、V4 使用4096；输出策略、执行路径和单次随机实现均为混杂因素。这是开发诊断，不是因果对照或 SOTA 结果。

## 关于协作是否暴露

本次没有实际切换。WorkBench 无多个受支持只读集合来源的硬候选事件，仍可正常单 loop。AppWorld 在读取任何集合之前就被接口错误停止，不能拿它证明长题不需要协作，也不能据此判断新的多来源编译路径在真实长题上有效或无效。

逐请求成本见运行目录 request_costs.csv；决策、触发、错误行号见 trace_findings.json；analysis/ 下包含各题原始计量。Runtime 秒只计求解，环境初始化/官方评测另计。Keepalive 任务已移除，systemd 单元 inactive/MainPID=0。

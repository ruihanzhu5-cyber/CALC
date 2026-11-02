# 历史工程故障与本轮处理

2026-11-02。来源为已保存失败日志与源码审计，不以模型猜测解释所有失败；历史目录原样保留。

| 故障 | 实际证据 | 当前状态 |
|---|---|---|
| 工具调用无对应tool result导致DeepSeek400 | GAIA2 pilot5首题native早停留下未执行call，GAIA2_PILOT5.md/旧failure | 上轮MANTA transport已补明确native_tool_call_cancelled，不冒充成功；作者源不改。本轮CALC严格wire拒绝与完整配对，坏结构不回传 |
| 参数JSON重复键/非有限值/结构或类型错误 | 既有接入失败促成协议专项回归；本轮真实测试发现坏function留在会话后继续污染下一请求 | 本轮严格解析+标准schema校验；畸形envelope只留trace，非法动作不执行，不猜测修复 |
| AppWorld双重JSON编码 | appworld_api.arguments_json及world.execute桥接 | 本轮直接arguments object，更新现役runner/tests，明确拒绝旧字符串协议 |
| 进度报告缺失阻止整个合法业务批次 | GAIA2_PILOT5_AUDIT_20261101.md记录10次progress_protocol_error | 上轮去门禁；本轮schema验证仍保持可选报告错误隔离，且新plan_changed不在生成时消费 |
| 数据返回可见性与解析不一致 | GAIA2真实events结果漏结构观察；MANTA raw完整但actor_input只剩total | 本轮CALC结构检测不依赖固定字段，数据保真不靠摘要覆盖；MANTA原版压缩作为其迁移诊断原样保留 |
| 交接信息只在proposal日志、不在worker输入 | SYSTEM_REVIEW_20261102.md零API探针 | 本轮真实assignment包、冻结历史快照、证据和能力权限传递 |
| AppWorld执行失败文本被记普通证据 | 官方environment.execute返回Execution failed. Traceback；runtime只捕获异常 | 本轮adapter按官方执行语义抛明确失败，进入failed_routes/tool_error，不造成功记录 |
| Main最终提交仅提示约定 | worker同工具目录，原invoke不识别actor | 本轮公共is_final_submission回调、runtime校验Main及所有未完职责；无评分输入 |
| Windows状态文件WinError5使监控host退出，actor继续 | WorkBench20 v2 supervisor_status.json写入失败，实际actor PID仍在 | 已结束旧批次保留；读实际进程再决定，不能按host退出直接重启付费actor。本轮不改后台托管逻辑 |
| 控制台宿主中断导致一批实验退出 | gaia2-adaptability3-flash-v2/monitor_interruption.json | 1a167cf已改pythonw+WSL systemd Restart=no，恢复用显式计划和retained SHA，本轮沿用 |
| C盘空间/跨平台路径与shell转义 | 早期WSL/缓存问题及本轮WSL参数含比较符需正确传递 | D盘独立发行版/缓存/tmp；安装以明确版本字符串传入，避免shell把包版本比较符当重定向。不切换到C盘缓存默认实验路径 |
| usage丢失/计量重复风险 | 中断actor_input无返回；runtime model_call与actor_request重复记录 | 最终成本只计真实actor/judge响应，孤立请求usage未知/下界，中断单列；新源码manifest覆盖新增模块和依赖 |

未声称本轮修复全部历史故障。后台托管、原生MANTA裁剪、复杂资源级重复写入仍分别记录，不能用无限重试或静默回退掩盖。

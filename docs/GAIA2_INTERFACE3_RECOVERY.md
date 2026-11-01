# GAIA2 三题批次恢复记录

原批次 `gaia2-adaptability3-flash-v2` 在北京时间 2026-11-01 23:08:42 前后停止；Windows 宿主退出码 `0xC000013A`，旧 WSL actor 已消失。无法仅凭该码确定中断发起者。用户在收到中断报告后明确要求“继续”。

方法与接口冻结于 `bad1ee8`，本次不修改 `src/calc`、GAIA2 actor runner 或模型参数。修改仅为实验托管：

- `run_gaia2_batch.py --plan` 支持显式 method→task 映射；没有按正确率自动挑选重跑。
- `run_gaia2_windowless.py` 用 pythonw 无控制台宿主启动 WSL，降低控制台信号耦合。
- `run_gaia2_service.py` 通过 systemd Type=exec 托管全部 Linux 子进程，Restart=no，独立日志；Windows host 保持 WSL 会话。
- 进程凭据从用户环境传递，经 root-only `/run` 临时环境文件交给服务，服务启动后删除该文件。日志、参数、回执不写凭据值。
- 不设置开机自动恢复或失败自动重启。系统/WSL 关闭仍可能中断；本设计不承诺断电续跑。

恢复目录 `D:/CALC-experiments/runs/gaia2-adaptability3-flash-v2-recovery1`：

| 方法 | 题目 | 行为 |
|---|---|---|
| CALC | scenario_universe_29_aa11lh | 保留已完成、已评分产物，逐文件 SHA 核验；不重跑不重判 |
| CALC | scenario_universe_22_h34zyy | 用户授权的一次中断补跑 |
| CALC | scenario_universe_21_nc6nqf | 首次运行 |
| MANTA | scenario_universe_29_aa11lh | 用户授权的一次中断补跑 |
| MANTA | scenario_universe_22_h34zyy | 首次运行 |
| MANTA | scenario_universe_21_nc6nqf | 首次运行 |

原两项中断已知总计 1,482,910 Token，另有至少一条 actor 输入未获得返回，实际成本为下界；可能未返回的 judge 用量也不能算零。恢复后结果按一份 retained 加五份新终态合并；旧中断尝试成本另列。此为开发恢复诊断，不是全新独立一轮实验。

验证：恢复映射、非法覆盖、工具公共边界等 18 项相关测试通过；无模型的 Windows pythonw → WSL systemd → 5秒进程探针退出码 0。旧方法源码与冻结 manifest 匹配。

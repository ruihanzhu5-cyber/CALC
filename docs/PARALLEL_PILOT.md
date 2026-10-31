# 开发实验并发执行

2026-10-31：支持独立任务并发；本次实现与验收没有重新启动付费 actor 或 judge。

## 运行方式

下一轮建议先用 3 路。队列的 `--concurrency 3` 允许同一方法的三道题同时执行；
该方法整组结束后，再运行下一个方法。网关的 `--concurrency 3` 允许最多三个独立题目的模型请求同时在途。
只改其中一处不能解决原来的双重串行问题。默认值仍为 1，必须在新运行中显式选择并发。

Windows 启动网关时可设置（启动网关本身不会调用模型）：

```powershell
$env:CALC_MODEL_CONCURRENCY = '3'
$env:CALC_TOKEN_LIMIT = '1000000'
& D:\CALC-experiments\code\CALC\scripts\invoke_wsl_experiment.ps1 -StartGateway
```

网关已经运行时，启动脚本不会替换现有服务。先检查 `/health` 返回的
`max_in_flight_model_requests`；队列会拒绝并发额度小于任务并发数的网关。

任务命令增加 `--concurrency 3`。下面仅展示 Main/CALC 的命令格式；
**`--execute` 会调用付费 API，本次未执行该命令**：

```powershell
& D:\CALC-experiments\code\CALC\scripts\invoke_wsl_experiment.ps1 `
  /opt/calc/envs/calc/bin/python /mnt/d/CALC-experiments/code/CALC/scripts/run_first20.py `
  --methods main joint --limit 5 --token-limit 1000000 `
  --run-tag dev5-parallel-v1 --concurrency 3 --execute
```

要包含 DynaFlow，仍须事先为新 run tag 准备其独立的 `dynaflow-prepared/shards.json`，
保持每题配置、目录与计量命名空间一致。原 `dev5-flash-1m-v0` 已由用户停止，不能直接续跑或覆盖。
并发选项本身没有修改输出长度、上下文和每题累计预算；正式重跑前另行确定这些配置。

## 调度与计量

- 一个任务对应独立子进程、日志和结果目录。队列主进程统一写 `queue.json`，避免并发覆盖。
- 同一道题在网关中保持最多一个请求在途；不同题目共享全局并发槽。
- 请求数、Token 和未知用量状态仍按 `run-id/task-id` 计量。每题预算不会因为开并发而增加。
- 已提交请求的记录先落盘；客户端断开后仍尝试收完上游用量。未知用量不会被当作零成本放行。
- Linux 队列收到 SIGINT/SIGTERM 时终止活动任务的进程组并记录 `interrupted`；某个进程出错时也停止同批活动任务，不自动付费重试。
- 本次只并发独立题目，没有改变方法内部 Agent 的协作顺序。不同并发度下的批次总耗时不能直接作为算法加速结论；延迟比较须统一负载并单列网关排队时间。

## 检索服务验收

停止旧批次前，POrchestra 轨迹中 47 次工具调用均记录 `ReadTimeout`，单次约 120 秒。
本次独立探测时 `/health` 与 `/retrieve` 也超时，确认旧检索服务不可用；阻塞的底层原因尚未确定。
按现有固定索引、tokenizer、top10×512 摘要和 8192-token 原文设置重启后，三路并发
“health → search → document”均成功，约 3.95、4.23、4.54 秒。该探测未调用模型。

队列现在会在启动 actor 前真实执行一次搜索和读文档。仅有健康接口响应不足以通过预检；
工具接口超时会在产生模型费用前暴露。

## 本地验证

网关测试用本地 MockTransport 验证跨题并发、全局上限、同题请求上限、预算与持久化用量。
队列测试运行真实的本地短子进程，验证同时执行、状态落盘和中断清理；不使用模型 API。

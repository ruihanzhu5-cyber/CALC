# DeepSeek Flash + BC+ 首轮20题运行环境

更新：2026-10-31。当前范围是开发试跑：一种模型、一个数据集。正式750题、GLM、GAIA2尚不启动。

## 存储位置

| 内容 | 位置 |
|---|---|
| 活跃Git代码 | D:\CALC-experiments\code\CALC |
| 独立WSL发行版 | CALC-Research，VHD位于D:\WSL\CALC-Research |
| Linux解释器和依赖 | /opt/calc/{python,envs,cache}，实际占D盘WSL虚拟磁盘 |
| 固定查询、索引、manifest | D:\CALC-experiments\bench\browsecomp-plus |
| 上游源码备份 | D:\CALC-experiments\upstreams |
| 模型逐请求账本 | D:\CALC-experiments\runs\model-calls |
| 首20题队列与Main/CALC结果 | D:\CALC-experiments\runs\first20-flash-v2 |
| DynaFlow原生结果 | runs\dynaflow-flash-first20-prepared\<qid>\run |
| 原有代码备份 | D:\CALC |

原有Ubuntu发行版保留；未启动或修改原Docker Desktop。新发行版使用自己的Docker Engine、Java21、Compose v2。
大量Linux依赖小文件放在WSL原生ext4内，避免Windows挂载目录的小文件性能开销。数据与结果保留Windows可见的D盘路径。

## 已完成的环境检查

- Windows Python3.12.13、WSL Python3.12.16；CALC测试83项通过。
- 新WSL内Java21、Docker29.1.3、Compose2.40.3。
- DeepSeek两轮真实工具往返通过；认证信息不落盘、不打印。
- BC+官方830题固定80dev/750heldout，first20取固定dev的前20；输入仅query_id/query。
- 官方BM25索引15文件2,170,624,147bytes已校验；真实Java/Lucene检索和document读取通过。
- 公共检索服务8765：top10，每条512 Qwen3 tokenizer tokens；reader8192；真实404通过。
- POrchestra作者Main/Delegate/ReAct保持原生实现，单会话delegate/revise/finish离线fixture通过。
- CLM作者ContextEnv真实Docker编辑、search/reader和Harbor任务接入通过，未用摘要器替换作者算法。
- DynaFlow作者JS工作流/Docker/RPC离线通过；20个答盲分题已prepare并验证。
- 公共模型网关8767已部署；Dyna工具桥8766已部署。它们的health与ready含义分别记录。

## 本轮模型与预算

实际请求使用deepseek-flash。原环境的deepseek-v4-flash是官方仍接受的旧别名；官方2026-10-31文档说明两者当前由DeepSeek-V4.1-Flash-1017提供服务。
这是文档中的服务版本；请求和响应model字段、时间戳均记录，不能把可变别名冒称不可变snapshot。
来源：https://api-docs.deepseek.com/quick_start/pricing/

- 统一thinking enabled / reasoning_effort high；不把无效的temperature=0当确定性保证。
- Main、workers和在线辅助统一通过本地网关；实际请求并发1，每题最多100个模型请求。
- 160k是已观测input+output停止阈值，最后请求可能越线；实际费用使用provider原始usage。
- CALC公共Main保留一次完整assistant/tool消息组。32768是byte heuristic输入装包预算，不是精确provider token硬上限。
- 单轮多篇文档超装包预算时，显式保留source/evidence ID与恢复指引；原文保留在archive，可分页read_evidence。不静默改写来源。
- CALC workers packet8192，Main状态预算28672；每3轮worker工具交互做联合选择，worker默认最多6轮。
- 交接包进入Main实际输入，累计交接只保留一个当前视图，历史包仍在lifecycle事件中保存。

## 原生版本

POrchestra 371aef619aec6f2918690a2fbaf9bf797b3025d3；CLM 483198229ab7b90c0eed4651306ab3b3505aaf50；DynaFlow 7451639d197ef844b4157cf40eadac68e9eba8ca。
BC+源码、查询、索引和tokenizer revision及数据hash见configs/first20-data.lock.json。
node:24.14.0-bookworm-slim镜像digest为sha256:d8e448a56fc63242f70026718378bd4b00f8c82e78d20eefb199224a4d8e33d8。

## 运行方式

在Windows PowerShell进入本仓库。API Key沿用当前进程中的DEEPSEEK_API_KEY，不写入配置或Git。

```powershell
# 启动本地模型网关；它是唯一接收真实provider key的服务。
.\scripts\invoke_wsl_experiment.ps1 -StartGateway

# 查看计划，不调用模型。
.\scripts\invoke_wsl_experiment.ps1 /opt/calc/envs/calc/bin/python /mnt/d/CALC-experiments/code/CALC/scripts/run_first20.py --limit 1

# 每种方法先跑1题，顺序Main、POrchestra、CLM、DynaFlow、CALC。
.\scripts\invoke_wsl_experiment.ps1 /opt/calc/envs/calc/bin/python /mnt/d/CALC-experiments/code/CALC/scripts/run_first20.py --limit 1 --execute

# 首题各方法接通后扩到20，已完成任务复用。
.\scripts\invoke_wsl_experiment.ps1 /opt/calc/envs/calc/bin/python /mnt/d/CALC-experiments/code/CALC/scripts/run_first20.py --execute
```

如果首题检查仍在运行，可在另一个后台进程使用同一命令加--after-sanity。它等待五个首题进程正常结束后扩到20，并复用已完成结果；若检查进程失败则停止扩展。

本地鉴权token由启动器从用户已有凭据派生，只经进程环境传递。baseline进程拿不到真实provider key。
队列文件queue.json记录每个process状态；process_completed不代表答对。官方正确性评分仍标evaluation=not_run。
代码中的模型账本还记录诊断请求、重试、取消/断连、cache与reasoning子集；不把这些子集重复相加。

## 已保留的调试记录

首题Main177的首个诊断版本因证据视图/历史/最新工具轮次重复，5请求190676 tokens后触发预算；记录在first20-flash-v0。
修复重复后的v1在单轮读取多篇原文时触发输入装包错误，5请求94091 tokens；记录在first20-flash-v1。
两次均未得到最终答案，没有计算正确率，也不混入v2结果。v2增加可恢复的超长工具结果投影，并修复两个worker累计交接的重复注入。
这些都是开发集调试成本，费用保留在模型账本。正式评测尚未开始。

## 首题结束后的预算校准

五系统在query177的首题均触发160k停止阈值，未交付最终答案；20题扩展等待进程已经停止，没有批跑。
当前只重跑CLM同一开发题，使用新calibration-clm-v1命名空间和100万token/100请求调试上限，结果在runs/budget-calibration-v1。
该上限用于观察基线完整执行量，尚未选作正式统一预算。网关允许配置上限，批量启动器会检查所有方法的预算与网关一致。
官方judge仍未运行。当前状态见D:\CALC-experiments\runs\RUN_STATUS.json。

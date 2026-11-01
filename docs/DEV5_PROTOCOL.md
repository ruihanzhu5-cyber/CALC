# 首批5道开发题：DeepSeek Flash + BC+

日期：2026-10-31。run_tag：dev5-flash-1m-v0。
这是开发试跑，不是论文正式评测。

- 题目固定为已冻结first20开发清单前5：177、717、263、501、513；不按答案或方法结果挑题。
- 方法：StrongMain、POrchestra-Inference、CLM-ZeroShot、DynaFlow-Base-Dynamic、CALC-Joint，共25次完整任务运行。
- 同一DeepSeek Flash接口；相同官方BM25索引、top10×512搜索摘要、8192-token原文读取。
- 每任务最多100次实际模型请求，累计可见input+output达到100万后停止新请求，最后请求可越线。
- 该上限是根据首题160k不足、CLM在816638 tokens后产出答案的开发观察选出的调试档；不作为最优预算结论。
- Main/worker/辅助及DynaFlow诊断请求全部通过公共网关计量；云端cache/reasoning是对应用量的子集。
- 保留各作者方法的执行语义和原生步数设置，记录完整配置；此开发批次不用于声称所有原生资源约束已与论文完全一致。
- 全新任务目录和计量命名空间，不复用原来160k下的失败或CLM单题校准成绩。

Actor队列：runs/dev5-flash-1m-v0/queue.json。
执行顺序为Main5、POrchestra5、CLM5、DynaFlow5、CALC5；各方法按同样5题顺序运行。
源码脚本scripts/run_first20.py支持--limit5 --token-limit1000000 --run-tagdev5-flash-1m-v0（实际命令参数与值之间须有空格）。

每个方法5题进程结束后，scripts/watch_pilot_judging.ps1调用scripts/export_pilot.py导出规范BC+结果，再调用Qwen判题。
判题只发送公开BC+题面、公开标准答案和本实验生成的答案。数据集public/ungated/MIT的来源证明见bench/browsecomp-plus/scoring-only/reference_provenance.json。
标准答案不交给做题Agent；Qwen Key只由Windows判题进程读取DPAPI加密存储，不进入代码、Git、WSL actor或运行manifest。

评分使用pin版官方GRADER_TEMPLATE与parser，模型为SiliconFlow Qwen/Qwen3-32B，关闭thinking，采样参数与官方默认一致。
该实现为官方答案判分逻辑的API适配；云API与本地vLLM的差异单独记录，不声称逐位相同。
未提交最终答案的任务按官方规则计失败；judge故障标记未完成，修好后补判，不伪造正确率。
检索日志不完整时显式标记retrieval_metrics_incomplete，不用猜测docid补齐。

本机连接验收：模型权限检查成功、正/反样例判定2/2符合预期；CLM单题校准query177已由Qwen判错。
这些不属于本dev5批次结果，不能用来替换或扩充该批25个任务的分母。

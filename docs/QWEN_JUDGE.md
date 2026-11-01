# Qwen3-32B 判题 API 接入

当前状态：已接通SiliconFlow Qwen/Qwen3-32B，模型列表鉴权通过，真实正/反判分样例均符合预期。
CLM第177题的宽预算校准输出已真实评分，判定错误。这是单题开发诊断，不是方法整体正确率结论。
缺少judge不影响agent复现；有最终答案后再离线判题，标准答案仅进入评分侧。

## 复用内容

从BC+固定commit 046949032b0328319cc9a02663a759ec601d9402的evaluate_run.py原样提取GRADER_TEMPLATE、create_judge_prompt及parse_judge_response。
原始MIT许可证及来源哈希在third_party/BrowseComp-Plus中。没有复制任务答案。
适配器只改变推理调用方式，提供答案正确性评分；官方的检索指标与校准误差全套统计仍由相应官方工具计算。
云API的模型服务实现需单独记录，不声称与本地vLLM逐位相同。

## 用户需要配置的资源

开通一个能调用准确Qwen3-32B型号的平台账号。平台可用模型以其控制台为准。

- SiliconFlow兼容地址：https://api.siliconflow.cn/v1，模型名Qwen/Qwen3-32B。
- 百炼：采用该账号地域/工作空间控制台给出的兼容地址，模型名qwen3-32b。

复制configs/qwen_judge.example.json为自己的配置，填写base_url/model，不在JSON中填写API Key。
PowerShell中仅给判题进程设置BCP_JUDGE_API_KEY。API Key不发到聊天、不放入Git。

```powershell
$env:BCP_JUDGE_API_KEY = Read-Host 'Qwen judge API Key' -MaskInput

# 只检查配置，不发起请求。
& 'D:\CALC-experiments\envs\calc-win\Scripts\python.exe' -m calc.evaluation.qwen_api --config configs/qwen_judge.example.json
```

默认配置尚未填写地址，所以检查应返回configuration_ready=false/model_calls=0。

## 真实判题

判题无需GPU、WSL或Docker，可直接在Windows Python环境运行。运行前先填写自己的API配置；输入目录必须是BC+官方结果schema，POrchestra/CLM/DynaFlow原生结果先导出。

```powershell
& 'D:\CALC-experiments\envs\calc-win\Scripts\python.exe' -m calc.evaluation.qwen_api `
  --config configs/qwen_judge.example.json `
  --input-dir 'D:\CALC-experiments\runs\EXPORTED_OFFICIAL_RESULTS' `
  --ground-truth 'D:\CALC-experiments\bench\browsecomp-plus\scoring-only\reference830.judge-only.jsonl' `
  --output-dir 'D:\CALC-experiments\evals\NEW_EVALUATION_DIRECTORY' `
  --execute
```

固定官方默认参数：temperature0.7、top_p0.8、top_k20、max_tokens4096、enable_thinking=false。
API若不支持参数，需要显式适配和记录，不能静默删参数后声称完全复刻。

输出每题原始判词、解析结果、真实usage和输入hash，并单独汇总答案正确率。
Agent未完成按官方规则算失败，不调用judge。judge网络/格式错误保留错误并使汇总未完成，不拿裁判故障冒充Agent错误率。
离线单元测试使用HTTP替身；额外的真实API连接验证见D:\CALC-experiments\evals\qwen-protocol-smoke\protocol_check.json。

## 本机安全启动器

凭据保存在仓库外D:\CALC-experiments\secrets\siliconflow-qwen.dpapi，使用Windows DPAPI用户加密及受限目录ACL。
scripts/invoke_qwen_judge.ps1仅在判题子进程中解密到环境变量，结束后恢复环境，不将密钥传给做题Agent。
服务地址和模型配置在configs/qwen_judge.siliconflow.json；该文件不含Key。

```powershell
.\scripts\invoke_qwen_judge.ps1 -JudgeArguments @('--config','configs/qwen_judge.siliconflow.json','--probe')
```

# CALC V0 验证记录

日期：2026-10-31。解释器：Windows Python 3.13.5，项目内editable安装。

## 本轮已完成

| 检查 | 结果 |
|---|---|
| `python -m pytest -q -p no:cacheprovider` | **73 passed** |
| `python -m ruff check src tests scripts/bootstrap_baselines.py` | All checks passed |
| `python -m compileall -q src` | 通过 |
| `python -m calc --help` / 安装后的 `calc` 入口 | 可用 |
| `calc demo` | 选择Transfer＋Evidence；未完工作交Main，worker归档且原始历史保留 |
| baseline bootstrap `--check` | POrchestra、CLM、BrowseComp-Plus三个SHA均匹配 |
| `calc doctor` / POrchestra adapter `check` | 核心依赖可用，ARE/原生POrchestra可选运行环境尚未安装 |

## 行为覆盖

- 职责部分迁移、全部回收、Main旧职责保留、恢复与重新分配。
- 上下文预算失败不改变职责状态；原始记录留存；完整事实与纯引用分开记账；JSON转义的工具事实正确识别。
- Joint、Independent及单模块模式使用相同候选基础；上下文完整性变化能改变联合选择。
- 真实OpenAI-compatible HTTP请求格式、assistant/tool配对、官方BC+ `/retrieve` 协议、共同本地证据分页回查。
- Fixed与Lifecycle共用checkpoint输入处理；Main也使用共同投影。
- 正常结束、预算、截断、错误、中断的结果与已发生usage记录；缓存输入/推理输出不重复加入total。
- 可选POrchestra类在模型调用边界投影，默认Joint真实执行，局部完成与官方任务评分分开。

HTTP测试使用本地MockTransport，POrchestra可选依赖测试使用接口替身。这些测试验证系统和协议，不是正式benchmark结果。

## 下一批运行

准备BC+固定索引与官方检索服务、配置实际模型API后，从冻结开发任务开始测真实质量与费用；在独立ARE环境完成POrchestra与CALC的原生开发场景。正式结果进入独立runs目录，之后调用官方评分器。

GitHub Actions配置Windows/Linux及Python3.11/3.12矩阵；其结果以GitHub实际运行状态为准。

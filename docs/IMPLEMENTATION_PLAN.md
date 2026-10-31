# CALC V0 实施方案

日期：2026-10-31。工作顺序：最新基线与代码接口 → 自己的方法闭环 → 真实任务接入 → 实验迭代。

## 本轮交付

1. 独立Python包，任务/职责/证据状态、联合动作、上下文编译、生命周期执行器。
2. 可直接运行的联合控制器：先用可解释评分，保留学习型ranker接口。创建、继续、转交、归档、恢复均有实际状态变化。
3. BrowseComp-Plus入口：OpenAI兼容模型API、固定检索服务接口、工具循环、官方结果JSON输出；模型/检索/评分均不以mock冒充正式复现。
4. POrchestra/GAIA2接入：固定上游提交，保留原生基线，在独立CALC类中接入联合状态、投影与动作；轻依赖核心与ARE可选依赖分离。
5. Main-only、固定/分离控制与Joint共用基础设施的实验接口；完整usage与事件日志。
6. 无API调用的可运行示例与关键行为测试；安装、复现及下一批真实实验说明。
7. GitHub私有仓库、开发分支/可审查提交；D:\CALC代码备份，包含代码文档与配置，不复制依赖/数据/运行日志。

## 方法框架

- Task–Evidence State：工作单元与执行agent分离，记录owner、进展、待办、证据出处与版本。
- Joint Controller：共同选择(action, recipient, work_items, context_packet/budget)。
- Context Transfer Runtime：编译下一次真实模型输入、移交证据与未完工作、归档和恢复分支。

首版重点Continue与Transfer-to-Main，保持完整生命周期接口；优先接通真实行为，不先做大型RL。主张与实验结果分开。

## 验收

- 已交接的未完工作可由接收者继续，原agent停止后续调度，证据可回查。
- 编译改变实际调用的消息视图，原始历史留存。
- Joint、Lifecycle-only、Context-only、Independent可切换；相同预算/模型/工具由运行配置明确记录。
- 测试覆盖跨owner迁移、终止与恢复、上下文预算与待办保留、真实HTTP接口协议、官方结果格式。
- deterministic demo只证明系统行为，不记作benchmark性能；真实benchmark只有官方评分后才记结果。

## 上游基线

- POrchestra：https://github.com/XueyangFeng/POrchestra，pin `371aef619aec6f2918690a2fbaf9bf797b3025d3`。
- CLM：https://github.com/facebookresearch/context-language-models。固定提交由bootstrap解析记录，不捏造pin。
- BrowseComp-Plus：https://github.com/texttron/BrowseComp-Plus。
- GAIA2/ARE：https://github.com/facebookresearch/meta-agents-research-environments。

POrchestra推理版本和OPOD训练版本分别记录。上游代码保存在忽略的.upstreams，默认不复制为自有代码。第一次paid benchmark批次在环境与真实费用测量后安排。

## 实施批次

| 批次 | 代码与验证 | 交付 |
|---|---|---|
| A | 状态/联合控制/真实上下文/生命周期 | 可安装核心、demo与关键测试 |
| B | BCP模型/检索/runner | 真实API入口、结果与usage日志 |
| C | POrchestra可选adapter | 原生与CALC入口、pin与环境文档 |
| D | 集成验证、文档、GitHub与D盘同步 | 分支、commit、验证报告、复现命令 |

下一阶段沿同一框架迭代贡献估计、上下文包和控制频率，再采集训练checkpoint与拟合ranker。

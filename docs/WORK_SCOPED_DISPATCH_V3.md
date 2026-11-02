# CALC 职责分派与渐进工具接口 V3

日期：2026-11-02。分支 `feat/work-scoped-dispatch`，起点 `1a167cf9c271e7b1688e128a4397c0f7a7855f89`（方法主体 bad1ee8）。保留原开发分支和已有实验。本轮交付代码，不启动付费解题。

## 实际改变

1. delegate 的公共 handoff、分支 handoff、完成条件、父进度/失败路线、所选证据、历史读取入口真正进入 Worker 输入。分支可指定 `tools` 和 `evidence_ids`，只允许父节点已具备的能力/证据。所有分支在创建前验证，坏分支不会留下半支队伍。
2. `retained_work` 让 Main/Worker 在委托后保留自己的未完职责，状态继续 ready。未指定时保留等待语义。保留职责不允许绕过未完子任务提前最终提交。
3. `tool_loading=deferred` 时初始模型请求不带全量业务工具参数。`discover_tools(query)` 返回当前职责范围内的名称/短描述；`load_tools(names)` 让选中 schema 在下一真实请求出现。只加载显式选择，不猜测或自动运行。load_skill 可通过技能配置的 `tools` 字段同时加载过程与参数。
4. read_history 返回委托/迁移时的冻结快照，不会读到父节点随后独立工作的实时消息。merge/fold 转交证据权限、工具能力和历史快照；职责完成仍由 complete_transferred_work 释放后继。
5. 普通可执行工具继续本地执行。集合检测根据结果容器/带ID对象结构，支持任意公开容器字段，避免只认results而漏events。已识别单记录内的artists/tags不当成新工作集合。报告中新建plan_changed保留到下一次正常调用，不再将写状态等同已作组织判断；仍不强制切换。
6. AppWorld API 参数由嵌套JSON字符串改为直接object，官方执行失败显式传播。GAIA2/AppWorld通过公共能力接口声明最终提交调用；只有Main且没有未完子任务、失败职责或迁移职责时才能提交。

这些是运行时行为：真实请求的工具schema、交接输入、执行权限、职责所有者和模型消息均发生变化。LLM仍决定业务独立性、是否值得分派/收拢；代码不按次数自动fold。不将这些已完成接口改动当作已证明的成功率或Token收益。

## 源码复用与归属

- `capabilities.py` 独立适配 [Anthropic c437962 Tool.deferred / Agent._tool_params](https://github.com/anthropics/single-agent-loop-kit/blob/c43796287b83bec847db923f07131d1cc8de750d/reference_loop/loop.py)。Apache-2.0项目；没有复制服务端tool-search接口，使用普通OpenAI兼容工具，DeepSeek可用。
- 交接/能力视图参考 [MANTA3da40879 SharedContextController](https://github.com/mao-code/MANTA/blob/3da40879d690a25459cc401292e5c6f0cc366d84/MAS/self_evolved/context.py)、[artifact lineage](https://github.com/mao-code/MANTA/blob/3da40879d690a25459cc401292e5c6f0cc366d84/MAS/artifacts.py)；作者MIT代码不改。当前实现为CALC自己编写，没有复制整个执行器或其业务停止规则。
- POrchestra revise_active、Deep Agents任务状态通知提供连续执行参考。本轮没有直接复制这两套源码；POrchestra本地根目录没有发现LICENSE，不能仅因公开就默认可逐行移植。
- 严格参数校验采用标准 `jsonschema` Draft2020-12（项目依赖），不自行编造部分schema解释器。严格wire解析由CALC实现。

## JSON 协议

`protocol.parse_tool_calls` 在任何业务提交之前解析整个批次，拒绝重复键（含嵌套/转义同名）、NaN/Infinity/数值溢出、非object参数、坏call结构、空/重复ID。没有JSON修复、补默认字段、猜测参数或隐藏重试。

- 业务工具及协作参数按声明schema验证：类型、必需字段和additionalProperties；布尔值不当整数版本。
- wire结构完整但JSON/schema错误：为各真实call ID返回明确错误，整批业务不执行。
- wire结构本身坏：原响应留trace，坏assistant消息不再发给模型，添加明确拒绝说明；不伪造ID或猜function，避免下一次API仍带非法消息。
- 无效可选report_progress有自己的错误，不取消同批合法业务动作；collaborate不能与业务工具混发。
- load_tools不能与尚未看到schema的业务调用同批；schema下一请求可见。原始调用/正常后续模型修正均进入现有计量，未新增自动付费重跑流程。

AppWorld新调用示例（旧arguments_json明确不再接受）：

```json
{"app":"api_docs","api":"show_app_descriptions","arguments":{}}
```

## 分派示例

在正常调用中可先report_progress得到p1，再提出下述协作操作（也可同一响应report_progress+collaborate）。工具参数是JSON对象，不是markdown或自然语言中的JSON片段。

```json
{
  "operation":"delegate",
  "progress_ref":"p1",
  "reason":"联系人邮件与商品查询仍有独立的未完工作",
  "proposed_next":"Main继续邮件职责，worker查询商品",
  "expected_savings":"预期避免两路查询串行，尚未测量",
  "risks":"需要统一提交最终结果，购物写入由明确责任者执行",
  "pattern":"parallel",
  "retained_work":{
    "current_scope":"给活动参与者发邮件",
    "progress":"已读取活动信息",
    "completion_condition":"所需邮件已发送且有回执",
    "unresolved":["收件人地址"],
    "failed_routes":[],
    "next_step":"查询地址并发送邮件"
  },
  "branches":[{
    "goal":"确认目标商品可用版本与价格，不结算",
    "completion_condition":"返回工具证据支持的版本ID与价格",
    "handoff":"只负责商品查询，交回证据后由Main决定购买",
    "tools":["Shopping__search_product"],
    "evidence_ids":[]
  }]
}
```

示例工具名来自GAIA2；其他benchmark使用各自真实目录，不允许凭空指定工具。

## 环境与运行

本次新增依赖 `jsonschema>=4.23,<5`；已安装Windows calc-win/manta-workbench-win及WSL gaia2/appworld环境。缓存和实验路径继续放D盘及位于D盘的CALC-Research发行版。

Windows无模型调用检查：

```powershell
D:\CALC-experiments\envs\calc-win\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp D:\CALC-experiments\tmp\work-scoped-dispatch-final
D:\CALC-experiments\envs\manta-workbench-win\Scripts\python.exe -B scripts/check_work_scoped_dispatch.py
D:\CALC-experiments\envs\manta-workbench-win\Scripts\python.exe -B scripts/check_adaptive_workbench.py
```

check_work_scoped_dispatch使用脚本化模型+真实WorkBench环境，检查Main保留职责、worker独立读取、实际schema渐进加载；刻意不完成用户任务，原生评分false是预期。它不是模型成绩。

WSL预检（不加execute，不调用模型）：

```bash
/opt/calc/envs/gaia2/bin/python -B scripts/run_gaia2_batch.py --config configs/adaptive.gaia2.work-scoped.example.json
/opt/calc/envs/appworld/bin/python -B scripts/run_adaptive_appworld.py --config configs/adaptive.appworld.example.json
```

真实运行使用同入口加 `--execute`。GAIA2批次应显式 `--methods calc`（若只执行CALC），并锁定新output_dir/题目ID；正式实验单独安排。本轮没有启动这些付费命令。WorkBench示例已启用deferred；AppWorld本来只有一个API入口，示例保持all，API文档仍按需发现。

三个runner的源码manifest包含新增capabilities.py、protocol.py及pyproject.toml，不能只锁旧adaptive.py而遗漏执行依赖。

## 本轮验证记录

- 全套pytest：323 passed（9.61秒）；Ruff与diff空白检查通过；三个示例配置通过JSON解析。
- 真实WorkBench旧接管检查：8次脚本决策、3次环境工具调用、fold后Main继续执行，0模型API请求。
- 真实WorkBench新分派检查：Main和worker各执行一次职责读取；实际请求从无业务schema变为所加载schema；0模型API请求。
- GAIA2锁定三题均完成真实环境preflight，队列exit_code=0，0模型请求。路径D:/CALC-experiments/runs/gaia2-work-scoped-flash-v3/preflight。
- AppWorld train 82e2fac_1官方文档API、环境保存与原生评分预检完成；0模型请求。路径D:/CALC-experiments/runs/appworld-work-scoped-dev3-v4/full/preflight。预检没有解题，未将false评分改成成功。
- 新增回归覆盖两个不同时间委托的父历史快照在merge后不互相覆盖；真实handoff使用带版本history_ref。

## 当前边界

仍是整loop merge/fold；未实现任意部分职责迁移或通用资源级写事务。scope控制工具能力，不证明两worker写入同一对象一定无冲突。历史快照是内存档案，不是跨进程断点恢复；保留wave模型屏障。加载的schema当前在loop内保留，没有按每一步自动卸载。现有whole-loop业务历史没有自动语义摘要。这些边界如实记录，不增加额外judge、训练或人数/总Token默认上限。

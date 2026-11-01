# GAIA2 五题完成报告与轨迹审计

完成核验与审计日期：2026-11-01（北京时间）。纯离线分析，无额外模型请求、无重判或改分。

结论：当前共同 Flash 端口下 CALC 官方评分2/5，MANTA0/5；不能据此主张 CALC 动态协作优于 MANTA。CALC五题均单loop；MANTA存在字符串观察截断、4096输出截断及写协议覆盖拓扑变更等明确混杂。应先修正接入和操作语义，再冻结下一轮。

## 覆盖与实验身份

每方法固定五个ID均有result/evaluation，exception均为null，非空终答可读。运行结束5/5不等于任务成功。MANTA使用首题授权补跑+其余四题；首题原HTTP400保留并单列成本。源码未变，skill初始/最终SHA均为74cdd9ccee0d472c099199fe44a54b3b2a13fa0f26b7936be8dd2eb64acf06ce。

CALC提交8182de3起运行，后续MANTA传输修正71fa7ab和显式重跑入口eead5b3；主策略adaptive.py没有在批次中更改。MANTA固定3da40879d690a25459cc401292e5c6f0cc366d84、self_evolved、repair1/turns2/initial5/total10；原生工具8轮、transactional_star、Flash/4096。ARE固定a9fd2edccb4bc7e22fbf45c8482a5fef30a2a5a4，数据版本与五题SHA见tasks.lock.json。

## 逐题结果与真实成本

Token为每题求解全部实际HTTP请求的返回usage，含原生重试、规划和控制；评测另列。MANTA第23题有1次连接错误usage未知，因此合计为已知下界。

| 题目（省略scenario_universe_） | 方法 | 正确 | 输入Token | 输出Token | 实际API请求 | 耗时秒 | length/空回复 |
|---|---|---|---:|---:|---:|---:|---:|
| 29_aa11lh | calc | True | 539,947 | 5,715 | 25 | 106.3 | 0/0 |
| 29_aa11lh | manta | False | 1,769,812 | 82,474 | 79 | 672.8 | 9/7 |
| 22_h34zyy | calc | False | 1,130,983 | 12,092 | 23 | 147.4 | 0/0 |
| 22_h34zyy | manta | False | 2,070,102 | 104,955 | 87 | 798.1 | 11/11 |
| 21_nc6nqf | calc | False | 1,146,421 | 11,651 | 30 | 208.3 | 0/0 |
| 21_nc6nqf | manta | False | 1,926,141 | 78,498 | 81 | 652.2 | 7/7 |
| 29_096dyu | calc | True | 562,783 | 10,217 | 20 | 150.0 | 0/0 |
| 29_096dyu | manta | False | 2,755,706 | 150,893 | 126 | 1115.9 | 16/14 |
| 23_ekcbfh | calc | False | 936,730 | 12,519 | 28 | 161.8 | 0/0 |
| 23_ekcbfh | manta | False | 2,975,331 | 155,212 | 125 | 1143.1 | 11/11 |

| 汇总 | CALC | MANTA（选定五次） |
|---|---:|---:|
| 正确题数 | 2.00 | 0.00 |
| 进程完成题数 | 5.00 | 5.00 |
| 逐题墙钟相加（秒） | 773.74 | 4,382.23 |
| 实际工具尝试 | 152.00 | 1,274.00 |
| 同题同工具同参数的额外出现次数 | 18.00 | 754.00 |
| 求解Token | 4,369,058 | 12,069,124 |
| 求解API请求 | 126 | 498 |
| 求解缺usage请求 | 0 | 1 |

CALC官方评测52907 Token/39请求，MANTA评测9203 Token/6请求。MANTA许多题先被确定性动作数量检查判错，故judge请求少；不能据此说评测工作更高效。

MANTA首次中断：161924输入+3230输出=165154已知Token，10请求，其中1次usage未知。计入该中断及五题评测后，MANTA实际总消耗至少12243481 Token、514请求，其中2次usage未知。CALC含评测4421965 Token、165请求，usage完整。缓存/推理Token已经包含在输入/输出内，不能重复加。

逐题墙钟之和CALC773.7秒、MANTA4382.2秒；首题原中断另82.0秒。首题补跑与MANTA后四题并行，环境冷启动亦计入，不能用整批墙钟作为相同并发下的吞吐比较。

## 调用用途展开

CALC按返回的工具名归类；混合请求整体仅计一次。MANTA原生事件含合成时间戳，不据该时间硬归因；按host START/DONE串行区间、TOOL_LOOP_RESULT、FORCE_FINAL和RETRY数展开HTTP序列，每题分别79/87/81/126/125个与实际日志完全对齐，未发现重叠START。

| 方法/请求用途 | 请求数 | 输入Token | 输出Token | 总Token |
|---|---:|---:|---:|---:|
| calc/mixed_control_execution | 20 | 664,718 | 12,255 | 676,973 |
| calc/execution_or_read | 83 | 2,789,759 | 29,755 | 2,819,514 |
| calc/control | 14 | 484,086 | 7,899 | 491,985 |
| calc/answer | 9 | 378,301 | 2,285 | 380,586 |
| calc/judge | 39 | 39,427 | 13,480 | 52,907 |
| manta/topology_control | 13 | 26,667 | 25,771 | 52,438 |
| manta/native_agent_read_stage | 315 | 6,874,321 | 221,597 | 7,095,918 |
| manta/native_committer_stage | 98 | 4,078,261 | 67,400 | 4,145,661 |
| manta/verification_control | 54 | 425,599 | 184,529 | 610,128 |
| manta/synthesis_repair | 18 | 92,244 | 72,735 | 164,979 |
| manta/judge | 6 | 7,032 | 2,171 | 9,203 |
| manta/interrupted_unassigned | 10 | 161,924 | 3,230 | 165,154 |

native_agent_read_stage为62工具只读阶段，native_committer_stage为101工具可写阶段；这些成本含该阶段内强制终答和原生重试。verification_control是系统内部审计/终止/投票，不是benchmark官方judge。纯报告控制491985 Token不等于可全部删除；混合676973 Token也不能全部归为控制开销。

## 模块之间真正撞在哪里

### 1. 接入表示破坏了两边原本期待的数据结构（P0）

GAIA2Adapter.invoke对所有结果执行str(result)。产品/联系人列表原本包含结构，但现在变成Python repr。CALC collection_facts只解析JSON，因此五题零collection_observed；它的“发现对象集合→重评估”入口在这个bench上没有工作。

MANTA MAS/llm.py对字符串先做默认160字符预览，而dict/list非检索结果另有12000字符完整保留路径。同一个共同适配器不能保证双方看到同等充分信息。比如联系人列表前缀含姓名/ID却很快截掉年龄与城市，读者只能分页或逐个查询；商品variant字段也容易丢失。原生上下文历史再保留最近2轮并压缩更早内容，可能再次放大丢失。源码路径和具体跨agent重复证据见trace_findings.json/F1,F5。

这是本轮接入设计不充分，也是MANTA默认字符串压缩与新工具分布的交互；不能把它统称为MANTA拓扑不行。下一版优先保留原始类型/字段与共同原文读取入口，检查最终发送给两边的观察是否完整。不能仅给MANTA扩大预算或悄悄改提示后混入此轮。

### 2. MANTA提出链式修复，写协议却把它收回星形（P0）

29_aa11lh、22_h34zyy、21_nc6nqf、29_096dyu首轮都记录了set_group_pattern(g_transaction,chain)。但对应mutation记录transaction_protocol_reapplied=true，topology_spec_versions的v0/v1都为star。原作者engine.py:379再次调用_transactional_star_spec。第23题后续轮修改global evidence访问，也记录写协议重新应用。

因此必须分别记录“模型提出什么”“代码允许什么”“实际执行什么”。当前不能说MANTA已经有效切到chain却仍失败。只读阶段仅有62工具，committer才有101工具；虽然写阶段获得较高输入成本，五题仍缺必须写操作，反映读者报告→可执行提交之间没有顺利闭环。

### 3. CALC的change同时被理解成改业务计划和改团队（P0）

34次评估实际为32 continue、2 change，协作请求/真实delegate/merge/fold均0。之前“全部continue”的描述应更正。两次change出现在订单/打车取消后，理由是执行fallback业务分支，没有提出团队调整；报告接口接受它们并继续业务工具。

这里混淆的是“任务计划发生变化”和“协作结构需要变化”。应把普通任务进度作为状态更新，将组织操作作为明确可执行请求；change应关联具体操作而非一个含糊标签。选择继续单loop仍必须合法，不为展示动态性强制分派。

### 4. 强制报告成为业务工具的前置门禁（P1）

10次progress_protocol_error全部因有checkpoint却遗漏report_progress，整批业务动作未执行。关联原请求351775 Token（约求解Token8.05%）；这是受该错误影响的调用成本，不是精确的冗余成本或保证可回收的节约。之后修复也计费。

GAIA2的全部公开通知，包括等待超时和无关日程更新，都进入environment_update并要求评估。进度账本、事件重评估、严格批次门禁三者叠加，会让记账阻挡执行。下一版保留职责迁移与工具协议的必要校验，去除“未写状态报告就拦下所有无关业务动作”的约束。

### 5. 上下文按需加载的思想与实际常驻输入脱节（P1）

AdaptiveRuntime每次发送全部101业务工具+6控制工具、动态系统状态和完整消息历史；raw字符串工具结果持续留在消息中。尽管有read_evidence/load_skill，当前没有把这些常驻输入实际缩减成按需读取。CALC输入占求解Token98.81%，五题消耗436.9万Token仍然偏高。

任务状态同时存在于system team state、报告历史、用户通知、工具返回和最终总结。动态system前缀也可能影响缓存复用，但本轮没有完整HTTP输入快照，不能伪造各组成部分的精确Token占比或因果节约。下一版用单一权威账本、保留证据ID与原始读取、记录真正发出的输入构成。

## MANTA的冗余证据与边界

1274次真实环境工具尝试中，754次是同题同工具同参数在首次之后的再次出现，约59.2%；这一统计不等于754次浪费，时间、订单状态、环境变化和独立核查可以使重读合理。原生工具记录还包括inter_agent_send及native本地拒绝，数量不应与环境工具attempt混同。

首题三个Agent对相同Pioneer product_id的get_product_details累计19次；list_orders同参数13次，list_cart12次。21题同一Calendar事件查询15次，今天日程13次，联系人分页11次。可证明证据访问重叠，不能仅凭计数证明内部思考完全相同。其任务输出还存在计划/核查/提交不同角色；应从每次读后新增字段、是否及时共享、最后写操作是否推进来判价值。

MANTA五题54次length、50次空回复；host日志另记录40次FORCE_FINAL、36次RETRY、15次EMPTY_COMPLETION（重试耗尽）；native trace中显式used_fallback=true事件为0，不代表没有空回复后的既有产物选择或强制终答。上述请求已包含在498次中，不再相加。572032输出Token中415890是reasoning子集（72.7%）。原始Gemma骨干替换为Flash后，4096上限对推理正文的含义不同；原生empty重试继续花费。此因素和模块行为要分开，不能包装成MANTA普遍弱点。

## 判错复核

| 题目 | CALC官方结果/离线观察 | MANTA官方首个失败 |
|---|---|---|
| 29_aa11lh | 通过：原订单取消后购买替代品并通知 | Failure: <br>Agent and oracle counters do not match for the following tools:<br>- Tool 'Shopping__add_to_cart': Agent count 1, Oracle count 2<br>- Tool 'Shopping__checkout': Agent count 0, Oracle count 1 |
| 22_h34zyy | 未通过：实际09:15–10:15，oracle要求09:15–10:00 | Failure: <br>Agent and oracle counters do not match for the following tools:<br>- Tool 'Calendar__delete_calendar_event': Agent count 0, Oracle count 1<br>- Tool 'Calendar__add_calendar_event': Agent count 0, Oracle count 1<br>- Tool 'CabApp__order_ride': Agent count 0, Oracle count 1 |
| 21_nc6nqf | 未通过但有评分争议：实际已发09:00–12:00 Rest time确认，tool judge reject | Failure: <br>Agent and oracle counters do not match for the following tools:<br>- Tool 'EmailClientV2__send_email': Agent count 0, Oracle count 3<br>- Tool 'Shopping__add_to_cart': Agent count 0, Oracle count 1<br>- Tool 'Shopping__checkout': Agent count 0, Oracle count 1 |
| 29_096dyu | 通过：冲突出现后取消原日程/车辆并改订 | Failure: <br>Agent and oracle counters do not match for the following tools:<br>- Tool 'Calendar__delete_calendar_event': Agent count 0, Oracle count 1<br>- Tool 'CabApp__user_cancel_ride': Agent count 0, Oracle count 1<br>- Tool 'CabApp__order_ride': Agent count 0, Oracle count 1 |
| 23_ekcbfh | 未通过：存在删除动作但causality检查拒绝，不能简化为未调用工具 | Failure: <br>Agent and oracle counters do not match for the following tools:<br>- Tool 'EmailClientV2__send_email': Agent count 0, Oracle count 1<br>- Tool 'Calendar__delete_calendar_event': Agent count 0, Oracle count 1<br>- Tool 'Calendar__add_calendar_event': Agent count 0, Oracle count 2 |

保留所有官方评分。第21题没有付费重判，也没有私自改成通过；同一评分争议不等于证明评分器一定错。

## 下一版：按优先级减法，而非再堆控制模块

1. **先修观察接口。** 真实类型、语义字段和原文入口对两方法一致；用零模型调用的固定工具结果检查截断与集合识别。
2. **合并进度与协作的决策入口。** 普通进度更新不触发独立审批；需要组织改变时在同一正常调用中给出明确操作和下一步，保持当前方式有效。删除含糊change标签的双重含义。
3. **减少事件门禁。** 等待超时保留为观察，无关通知不自动要求组织判断。真正的目标/依赖变化、明确阻塞或主动请求才提供决策机会；不把事件计数当操作规则。
4. **让上下文机制真正减输入。** 一份当前账本、证据索引、按需完整结果；记录每次实际输入构成和cache命中。语义摘要不覆盖原始证据。
5. **保留可执行的收拢语义。** merge/fold不删除，接收者接手未完工作、来源停职责、职责完成释放后继；这些正确性边界需要继续测试。
6. **先做共同接口下的小对照。** single、修正后的full、MANTA原生；不改已完成结果。先检查真分工/真接管是否发生、失败动作是否减少，再扩展到四组消融。任何新增付费批次需新的实验安排，审计没有自行启动。

## 文件与复现审计

- request_costs.csv：514次MANTA实际请求（含中断）+165次CALC实际请求，共679行数据，含actor/judge、用途、输入输出、缓存推理子集、空回复/截断/缺usage标记。
- audit_metrics.json：每题汇总、跨Agent同参数查询样例、原生结构版本与mutation、检查点/协议错误和原始路径。
- trace_timeline.json：CALC环境更新、评估、错误及结构操作事件，带trace行号；MANTA阶段可按CSV的host START/DONE编号追溯。
- trace_findings.json：观察、解释与后续验证分别列出，含证据路径/源码行。
- skill_integrity.json、manta-skill.final.md：初始最终skill一致；上游git status干净。
- audit_gaia2.py、write_report.py：只读原始实验文件的离线统计与报告生成代码；输出文件不回灌actor。

使用D盘Windows环境：`D:/CALC-experiments/envs/manta-workbench-win/Scripts/python.exe -X utf8 audit_gaia2.py`，再运行write_report.py。需可写本run目录。

结论范围：这是五题开发诊断。修复后的首题与未尝试四题作为同一条件恢复集合；不能作为严格独立的新一轮SOTA主表，也没有证据将全部成本差归给动态协作。

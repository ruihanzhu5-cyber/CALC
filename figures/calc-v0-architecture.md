# CALC V0 当前架构

对应代码提交：3e1a775。日期：2026-10-31。

主运行路径为 BrowseComp-Plus。Main 与 workers 在 V0 顺序执行；POrchestra/GAIA2 作为复用相同核心接口的可选适配，完整 ARE 环境尚未实际运行。

```mermaid
---
title: CALC V0 · 当前系统架构
---
flowchart TB
    TASK["任务与配置<br/>问题 / 模型 / 模式 / 执行预算"]

    subgraph EXEC["① 任务执行与工具层"]
        direction LR
        RUNNER["Main + Workers 执行循环<br/>V0 顺序执行<br/>模型调用 / 工具调用 / 交接后继续"]
        MODEL["模型客户端<br/>OpenAI-compatible API"]
        SEARCH["外部检索 search<br/>BrowseComp-Plus · POST /retrieve"]
        RECALL["本地证据 read_evidence<br/>目录查询 / 原文分页回查"]
        RUNNER <-->|"请求 / 返回"| MODEL
        RUNNER <-->|"查询 / 文档片段"| SEARCH
        RUNNER <-->|"回查已存证据"| RECALL
    end

    subgraph CORE["② CALC 生命周期与上下文联合管理"]
        direction LR
        STATE["任务—证据—职责状态<br/>工作项 / owner / 未完事项<br/>证据 / 原始历史 / 执行进展"]
        CONTROL["联合控制器<br/>继续 / 交接 × 近期记录 / 证据包<br/>V0 可解释评分"]
        LIFE["生命周期执行器<br/>移交证据与未完工作<br/>更新 owner / agent 运行状态"]
        CONTEXT["上下文编译器<br/>按职责选证据 / 按预算装包<br/>生成下一次真实模型输入"]
        STATE -->|"当前状态"| CONTROL
        CONTROL -->|"动作＋接收者＋上下文策略"| LIFE
        LIFE -->|"编译选定方案"| CONTEXT
        CONTROL <-->|"候选包 / 覆盖与开销"| CONTEXT
        LIFE -->|"提交职责与执行状态"| STATE
    end

    subgraph EVAL["③ 记录与离线评价"]
        direction LR
        OUTPUT["运行产物<br/>结果 JSON / 原始 trace / token usage"]
        JUDGE["官方评分器<br/>任务结束后独立运行<br/>正式 benchmark 评测待开展"]
        OUTPUT --> JUDGE
    end

    OPTIONAL["POrchestra / GAIA2 可选适配<br/>复用原生 session 与工具环境<br/>完整 ARE 环境待运行"]

    TASK --> EXEC
    EXEC -->|"检查点写回：进展、证据、工具结果"| CORE
    CORE -->|"下一轮 ContextPacket 与职责状态"| EXEC
    EXEC -->|"保存执行过程与最终输出"| EVAL
    OPTIONAL -.->|"复用相同核心接口"| CORE

    classDef input fill:#f0f9f6,stroke:#3a8b71,color:#193a30,stroke-width:1.5px;
    classDef execution fill:#eef5ff,stroke:#4b78b3,color:#173657,stroke-width:1.5px;
    classDef state fill:#f4f3ff,stroke:#8174bc,color:#352a60,stroke-width:1.5px;
    classDef method fill:#eee9ff,stroke:#7661b3,color:#35265c,stroke-width:2px;
    classDef context fill:#edf7f6,stroke:#448e88,color:#18423d,stroke-width:1.5px;
    classDef optional fill:#fafafa,stroke:#959ca7,color:#555f6f,stroke-width:1.5px,stroke-dasharray:6 4;
    classDef output fill:#fff4e9,stroke:#bf8b50,color:#69451f,stroke-width:1.5px;
    class TASK input;
    class RUNNER,MODEL,SEARCH,RECALL execution;
    class STATE state;
    class CONTROL,LIFE method;
    class CONTEXT context;
    class OPTIONAL,JUDGE optional;
    class OUTPUT output;
    style EXEC fill:#fbfdff,stroke:#c8d7e9,stroke-width:1px
    style CORE fill:#fdfbff,stroke:#c9bddf,stroke-width:1px
    style EVAL fill:#fffdf9,stroke:#e8d6be,stroke-width:1px
    linkStyle default stroke:#6b7280,stroke-width:1.5px;
```

## 如何读图

1. 执行循环调用模型与检索工具，把返回内容和进展写回 TaskState。
2. JointController 读取当前状态，通过 ContextCompiler 构造候选上下文并评估覆盖/开销，共同选择 continue/transfer 与 recent/evidence。
3. LifecycleRuntime 先编译可提交的上下文，再迁移职责、改变 owner 与 agent 状态；选定 ContextPacket 进入下一次真实模型请求。
4. 原始证据与历史保留在状态/轨迹中，read_evidence 支持本地分页回查。
5. 结果、trace 与 usage 分别落盘；官方评分发生在任务执行后，不向在线控制器提供答案。

## 代码映射

| 图中模块 | 实现 |
|---|---|
| Main / Worker 与工具循环 | src/calc/adapters/browsecomp.py::run_task |
| 模型客户端 | src/calc/llm.py::OpenAICompatibleClient |
| 任务—证据—职责状态 | src/calc/state.py::TaskState |
| 联合控制器 | src/calc/controller.py::JointController |
| 当前评分器 | src/calc/controller.py::HeuristicValueModel |
| 上下文编译 | src/calc/context.py::ContextCompiler |
| 生命周期执行 | src/calc/lifecycle.py::LifecycleRuntime |
| 可选 GAIA2 适配 | src/calc/adapters/porchestra.py |

## 当前边界

- 控制器当前评分的候选为 continue/transfer × recent/evidence；完整生命周期执行接口还支持 spawn、merge、retire、resume、reassign。
- 上下文包有预算；实际模型请求还包含共享指令与最近完整工具轮次。
- 当前使用可解释评分器；学习型 ranker、自适应 spawn 和多 worker 并发属于后续迭代。
- 73 项本地离线测试及四组 GitHub CI 已通过；真实模型、官方检索/评分和完整 ARE 环境的 benchmark 运行尚待开展。

## 导出文件

- calc-v0-architecture.png：适合直接插入汇报。
- calc-v0-architecture.svg：矢量图。
- calc-v0-architecture.mmd：可编辑 Mermaid 源码。

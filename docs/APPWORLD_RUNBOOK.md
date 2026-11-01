# AppWorld 运行说明（D 盘 + WSL）

使用 `CALC-Research` WSL；VHD 位于 `D:\WSL\CALC-Research`，`/opt/calc` 也占 D 盘。
Windows 官方环境在本机创建内存 SQLite 时因路径分隔符失败，所以真实执行使用 Linux。
本机 D 盘原先只发现 AppWorld-derived 的其他项目适配器，没有原生环境或完整任务数据。
本次官方数据已下载至 `D:\CALC-experiments\data\appworld\data`。

## 一次性安装（不调用模型）

以下命令在 WSL bash 执行。已有目录不要重新覆盖；源码必须是指定提交。

```bash
export TMPDIR=/opt/calc/tmp
export UV_CACHE_DIR=/opt/calc/cache/uv
export APPWORLD_CACHE=/opt/calc/cache/appworld
export IPYTHONDIR=/opt/calc/cache/ipython
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$TMPDIR" "$UV_CACHE_DIR" "$APPWORLD_CACHE" "$IPYTHONDIR"

# 本机已完成，不需再次安装/下载。
# 新环境需要 git-lfs；官方 bundles 为 LFS 对象。
# apt-get install git-lfs
# git clone https://github.com/StonyBrookNLP/appworld /mnt/d/CALC-experiments/upstreams/appworld
cd /mnt/d/CALC-experiments/upstreams/appworld
git checkout 42b5bcf3cd334fee33f0c37c02070a9f5807add5
git lfs install --local --skip-repo
git lfs pull

/opt/calc/tools/uv venv --python /opt/calc/python/cpython-3.12.16-linux-x86_64-gnu/bin/python3.12 /opt/calc/envs/appworld
/opt/calc/tools/uv pip install --python /opt/calc/envs/appworld/bin/python -e . pydantic==2.12.5 fastapi==0.119.0 starlette==0.48.0 pytest ruff
/opt/calc/envs/appworld/bin/python -m appworld.cli install --repo
/opt/calc/envs/appworld/bin/python -m appworld.cli download data --version 0.2.0 --root /mnt/d/CALC-experiments/data/appworld
```

固定 pydantic 2.12.5 是因为本机安装最新 2.14.2 后官方导入出现 `match_type` 参数兼容错误；
2.12.5 满足上游依赖范围。FastAPI 0.162.0 的 Path 不再接收官方环境使用的 embed 参数，
固定为满足上游范围的 FastAPI 0.119.0 / Starlette 0.48.0。没有修改官方评测源码。当前环境依赖快照见
`configs/appworld.environment.freeze.txt`。
Windows/WSL 共用源码时使用一致的 Git LFS 过滤器；不要因为二进制 LFS diff 假象而忽略完整性检查。
本机 worktree 由 Windows Git 创建，其 .git 指针是 Windows 路径；配置中的 calc_git_dir
显式指定 WSL 可读的同一 worktree Git 管理目录，用于记录真实提交。普通 Linux clone 可不设置此项。

## 数据锁、预检与真实单题命令

```bash
cd /mnt/d/CALC-experiments/code/CALC-task-progress
export PYTHONPATH="$PWD/src"
export TMPDIR=/opt/calc/tmp APPWORLD_CACHE=/opt/calc/cache/appworld IPYTHONDIR=/opt/calc/cache/ipython
export PYTHONDONTWRITEBYTECODE=1

# 数据锁只创建一次；重复运行拒绝覆盖。
/opt/calc/envs/appworld/bin/python -B scripts/run_adaptive_appworld.py --config configs/adaptive.appworld.case1.json --lock-data

# 无模型调用：真实环境初始化、文档 API 调用、保存与官方评分接口贯通。
# 该预检不求解任务，官方成功/失败字段不当作模型实验分数。
/opt/calc/envs/appworld/bin/python -B scripts/run_adaptive_appworld.py --config configs/adaptive.appworld.case1.json

# 仅在 DEEPSEEK_API_KEY 已由环境安全注入后执行；不要将密钥写进配置/命令/日志。
# 这一步调用付费模型，仅固定的一题 full 模式。
/opt/calc/envs/appworld/bin/python -B scripts/run_adaptive_appworld.py --config configs/adaptive.appworld.case1.json --execute
```

Windows 启动时可通过 WSLENV 传递已存在的 `DEEPSEEK_API_KEY` 环境变量；不要打印变量值。
所有配置中的缓存路径均指向 D 或 D 承载的 WSL。程序不隐式下载、不自动重跑、不覆盖已有运行目录。
AppWorld 也会在 `appworld_root/experiments/outputs` 下保存原生执行记录与评测产物。

固定单题 `82e2fac_1`，train。新三题开发配置为 `adaptive.appworld.example.json`，
目前没有授权执行三题或四对照批量；后续分别使用 `--mode single|initial_static|no_merge_fold|full`。
每次新实验需指定新的 output_dir，先生成并核对对应 data_lock。

## 测试

```bash
PYTHONPATH=src /opt/calc/envs/appworld/bin/python -B -m pytest tests -q -p no:cacheprovider --basetemp /opt/calc/tmp/calc-tests
/opt/calc/envs/appworld/bin/ruff check src/calc/adaptive.py src/calc/progress.py src/calc/benchmarks scripts/run_adaptive_appworld.py tests/test_adaptive.py tests/test_appworld_adapter.py --no-cache
```

Windows WorkBench 真实工具回归使用已有含 pandas 的环境，而非 AppWorld 最小环境：

```powershell
$env:PYTHONPATH='D:\CALC-experiments\code\CALC-task-progress\src'
$env:TEMP='D:\CALC-experiments\tmp'
$env:TMP=$env:TEMP
& D:\CALC-experiments\envs\manta-workbench-win\Scripts\python.exe -B D:\CALC-experiments\code\CALC-task-progress\scripts\check_adaptive_workbench.py
```

单元测试中的模拟模型和环境仅验证协议，不用于报告 benchmark 得分。
真实预检与模型运行分别保存在 `preflight`、`execute`，各含 manifest、每题 result/evaluation、summary。
真实模型另有逐条 flush 的 trace.jsonl；未报告 usage 必须单列并把 Token 视为下界。
错误会保留 failure.json 并终止，不生成替代答案或伪造评测完成状态。

## 本轮验证记录

- 状态机与 AppWorld 隔离单测 28 项通过，含父节点提前答复时保留待审批请求的决策机会。
- 最终 WSL 完整回归 138 项通过；相关 28 项状态机/适配器测试及 Ruff 检查通过。
  Windows 初次 CLI 子进程因未安装新 worktree 模块路径失败，设置 PYTHONPATH=src 后通过。
- WorkBench 离线贯通通过：8 个脚本决策、3 次真实业务工具，fold 后父节点执行；
  故意未完成业务任务，官方适配评分为 false。零外部模型请求。
- Windows AppWorld 路径兼容失败原记录保留在
  `D:\CALC-experiments\runs\appworld-task-progress-dev3-v1`，不混入 WSL 结果。
- WSL 原生预检已通过：`appworld-task-progress-case1-v1/full/preflight`，模型请求 0，
  真实初始化、文档 API、保存和官方评分耗时 24.409 秒。只查文档未做题，官方 success=false 是预期值。
  不能把该预检当成模型成绩；真实单题结果以 execute 目录和本次运行报告为准。
- Flash 单题已完成，官方成功 1/1，15 请求、161160 Token；详见
  [真实单题运行记录](APPWORLD_CASE1_20261101.md)。未自动启动下一题。

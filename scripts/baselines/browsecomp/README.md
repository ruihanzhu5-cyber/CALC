# Shared BrowseComp-Plus preparation and official BM25 service

These are original preparation/transport scripts. They load the separately
cloned, pinned official `BM25Searcher`; no upstream code or benchmark data is
vendored here. Pins and task-file hashes are in
`configs/first20-data.lock.json` at the repository root.

`CALC_EXP_ROOT` defaults to `D:/CALC-experiments` on Windows and
`/mnt/d/CALC-experiments` on Linux. Data and index always go to its
`bench/browsecomp-plus` directory, never into this source directory.

The existing tested runtime is `/opt/calc/envs/bcp` in the D-backed
`CALC-Research` WSL ext4 disk. Java21 is required. To recreate the CPU-only
Python3.12 environment with uv, install the flat resolved lock without
transitive resolution:

```bash
uv pip install --python /opt/calc/envs/bcp/bin/python --no-deps \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  --index-strategy unsafe-best-match -r requirements.lock.txt
```

Every package is pinned, including `torch==2.7.1+cpu`. `--no-deps` avoids
Pyserini's broad dependency declaration pulling an additional CUDA stack.
PyArrow23.0.1 is used only by the preparation script; no model weights are used.

```bash
python prepare_bcp.py --queries       # range-read official query columns
python prepare_bcp.py --index         # official BM25 files + SHA256 checks
bash start_service.sh                # 0.0.0.0:8765
```

Preparation writes agent tasks with only query_id/query and a separate
`scoring-only` answer file. Query access must stay restricted to task files in
the agent runner. The researcher split uses SHA256(`CALC-v0-dev|` + query_id):
first80 dev, remaining750 heldout, first20=dev[:20]. No data or answers should
be added to this repository.

`GET /health` reports revisions and caps. `POST /retrieve {"query":"..."}`
returns the official REST result shape at top10/snippet512. Added
`POST /document {"docid":"..."}` returns stored original text capped8192
tokens and `truncated`. Both use the same pinned Qwen3-0.6B tokenizer. All
methods should consume the service response unchanged before applying their
own memory policy.

The launcher sets JAVA_HOME and a dummy, unreachable OpenAI encoder client
because Pyserini eagerly imports that unused class even for BM25. Retrieval
itself never calls a model API. Override `BCP_SOURCE_ROOT`, `BCP_PYTHON` or
`CALC_EXP_ROOT` as needed; default source is
`/opt/calc/upstreams/BrowseComp-Plus`.

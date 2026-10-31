# BrowseComp-Plus adapter

This is an executable CALC development harness for the **existing** BrowseComp-Plus
benchmark. It does not create tasks, supply gold evidence to the agents, run a
judge, or claim a reproduced paper score. The integration tests use
`httpx.MockTransport`; passing them establishes transport and lifecycle behavior,
not benchmark accuracy.

## Supported upstream contract

The implementation was checked against the official
[BrowseComp-Plus repository](https://github.com/texttron/BrowseComp-Plus), including
[search_r1_server.py](https://github.com/texttron/BrowseComp-Plus/blob/046949032b0328319cc9a02663a759ec601d9402/searcher/search_r1_server.py),
[query templates](https://github.com/texttron/BrowseComp-Plus/blob/046949032b0328319cc9a02663a759ec601d9402/search_agent/prompts.py),
and [evaluate_run.py](https://github.com/texttron/BrowseComp-Plus/blob/046949032b0328319cc9a02663a759ec601d9402/scripts_evaluation/evaluate_run.py).

The official REST server accepts:

```http
POST /retrieve
Content-Type: application/json

{"query":"research query"}
```

and responds with:

```json
{"result":[{"docid":"42","document":{"title":"Title","text":"Document snippet"}}]}
```

The retriever's `k` and snippet limit are fixed when starting the server; CALC
does not send invented per-query parameters. The official REST server has **no
get_document route**. Although upstream's MCP server can optionally register a
`get_document` tool, this adapter is deliberately the official **search-only REST
setting**. A custom `/search` or `/document` service is not interchangeable with
this protocol. All modes also expose `read_evidence`, a **local memory tool** over
previously retrieved snippets. It is not a REST endpoint, cannot fetch unseen
corpus content, and does not restore text beyond the server's original snippet.
All modes must use the same corpus/index, retriever settings and snippet policy.

## Prepare and run

Prepare the official corpus/index and decrypted data using upstream's documented
workflow, then start its REST server, for example from its checkout:

```powershell
python searcher/search_r1_server.py --searcher-type bm25 --index-path PATH_TO_INDEX --port 8001 --k 5 --snippet-max-tokens 512
```

Consult the chosen searcher's upstream arguments if using a dense index. CALC
does not download the corpus, train a retriever or silently replace retrieval
with live web search.

`tasks_path` points to JSONL with `query_id` and `query`. The official decrypted
JSONL can contain other fields, but `load_tasks` copies **only these two fields**
into the agent-visible `BrowseCompTask`. Answers, gold documents and qrels are
not passed to task state, prompts or traces. Keep the untouched original file
available separately for the official evaluator. Declare train/tuning/test task
IDs before running experiments; CALC does not invent a benchmark split.

Copy `configs/browsecomp.example.json` to a private config, set its real model
base URL/name, retriever URL and task/output paths. Relative paths resolve
against the config's directory. Set the named API-key environment variable
outside the config and run:

```powershell
python -m calc run-browsecomp --config configs/browsecomp.local.json
```

The supplied example uses a deliberately invalid model hostname. It cannot call
a paid model until configured. A live run uses real configured APIs and can
incur charges; no live run is part of the offline tests. API keys are excluded
from serialized requests and traces. `allow_no_api_key` is available for an
unauthenticated local compatible server. Use `output_token_field` to select
`max_tokens` or `max_completion_tokens`, and optional `reasoning_effort` or
provider-specific `extra_body` for your deployment.

Programmatic entry points:

```python
load_tasks(path, task_ids=None, limit=None)  # list[BrowseCompTask]
run_task(task, config, llm, retriever)       # TaskRun
run_browsecomp(config_path_or_dict, llm=None, retriever=None)  # summary dict
```

## What the modes actually execute

Workers are **sequential** in this initial implementation. The harness measures
real wall time and makes no parallel speedup claim. Non-main modes use the same
configurable initial `worker_goals`, model, tool access and request limits. This
is a controlled initial team, not yet learned task decomposition or adaptive
creation. Workers genuinely call the model and retriever; the mode names do not
stand in for simulated answers.

| Mode | Actual behavior |
|---|---|
| `main` | One Main executes the search/local-recall loop, with no workers. |
| `fixed` | Each worker executes until a normal report or fixed step cap; the same checkpoint/compiler mechanism selects the standard recent context after each tool round. Main receives completed findings and unfinished responsibilities. |
| `lifecycle` | The core controller selects continue/transfer on its standard recent-context candidate. |
| `context` | Workers keep a fixed lifetime while the core controller chooses context packets at checkpoints. |
| `independent` | The core controller chooses lifecycle on a standard packet, then independently chooses the context for that action. |
| `joint` | The core controller scores lifecycle/context candidates together. A selected transfer stops that worker's model loop, migrates its work to Main and passes the compiled packet. |

Every worker checkpoint updates recent new-evidence count and stagnation. Evidence
IDs combine document ID and content hash; immutable content is stored once, while
work-specific links remain on work items. The harness makes real repeated
retrieval calls, which remain visible in its tool counts; evidence deduplication
does not falsely count a repeated search as a saved HTTP call. All modes share
this behavior. `read_evidence(evidence_id="", offset=0, limit=...)` lists catalog
entries with source and evidence IDs (at most 32 entries per page). Supplying an
ID reads a character page, with `offset`, `next_offset`, and `total_chars`. The
per-call limit is at most 4096 characters. Returned local pages can be linked to
the current responsibility without becoming newly retrieved documents.

In **every mode**, the next prompt is built from a bounded context packet, a
short common local-recall hint, and the latest **complete** assistant/tool round.
The latest round is retained as the common immediate observation, preserving
tool-call ID pairing; older rounds remain in the archive and are selected by the
compiler. Fixed and lifecycle-only workers use the same standard `recent` view;
the lifecycle decision is what differs. Main uses the same `full` compiler mode
across all arms, including `main` and `fixed`, at every tool checkpoint. Thus a
context-projection mechanism is not available exclusively to the joint method.
Raw messages remain in trace sidecars. Omitted evidence is recoverable using
the local catalog and paginated reads in all arms.
At handoff, Main receives both results and pending work. Completed worker reports
also transfer through the runtime, so they are not lost simply because Main's
compiler selects work by owner. Mandatory state that cannot fit the context
budget fails visibly rather than silently dropping duties. The token-packing
estimate is the core compiler's estimate, not billed provider usage.

`main_max_steps`, `worker_max_steps` and `max_model_requests` impose explicit
execution limits. Optional `max_total_tokens` is checked against reported usage
**between requests**; it is not a strict pre-tokenization cap and can overshoot
by a request. Context budget is a packet budget, not the entire serialized HTTP
prompt: the common system/task instructions, short memory hint, tool schemas and
latest complete observation round are additional input. Missing provider usage is flagged rather than estimated as measured
usage. These limitations should be retained in experiment manifests.

## Artifacts and official evaluation

Each task writes:

```text
OUTPUT/
  runs/run_QUERY_HASH.json     # official evaluator input only
  traces/run_QUERY_HASH.json   # state, exact requests/responses, tools, lifecycle events
  usage/run_QUERY_HASH.json    # inclusive token counters and elapsed time
  summary.json                # statuses; evaluation="not_run"
```

The official result contains `query_id`, `tool_call_counts`, `status`,
`retrieved_docids`, and `result=[{"type":"output_text","output":"..."}]`.
Tool counts separately report `search` and `read_evidence`. Local recall neither
calls the retriever nor adds document IDs to `retrieved_docids`.
`retrieved_docids` includes every document ever returned, not just cited or
retained documents. The answer is prompted to include explanation with document
citations, exact answer and confidence, consistent with upstream's format.

`completed` denotes a normal model stop with nonempty final text; correctness is
determined separately by the official judge. Exhausted steps/requests,
truncated output, missing final text, API failure or context-budget failure are
not marked completed. Runtime failure after a model response still writes the
failed official record, partial trace and spent usage. An interrupt is persisted
by the batch wrapper before propagating `KeyboardInterrupt`; in-flight usage
may be unavailable. Existing task files are not overwritten.

Point upstream's evaluator to **OUTPUT/runs**, never OUTPUT or its trace/usage
directories:

```powershell
python scripts_evaluation/evaluate_run.py --input_dir PATH_TO_OUTPUT/runs
```

Run this from the official checkout with its documented ground-truth and judge
dependencies prepared. The official evaluation can require local GPU resources;
CALC does not automatically launch it. No result from the mocked tests is a
benchmark result or SOTA claim.

## Usage accounting

Prompt/input and completion/output counts are inclusive. Cached input is a subset
of prompt tokens; reasoning is a subset of completion tokens. They are saved
separately but **not added again** to the total. Provider-reported total and raw
usage fields are preserved. Requests with missing usage or interrupted/failed
transport are counted as unreported, not free. The current adapter reports
tokens and elapsed time, not fabricated dollar costs. Apply a frozen, documented
provider price schedule separately if comparing actual currency cost.

## Offline verification

```powershell
python -m pytest tests/test_browsecomp.py -q
```

These tests exercise HTTP request bodies, assistant/tool message linkage,
official result shape, removal of gold fields at the task boundary, usage subset
accounting, real controller-driven worker transfer, failed-run accounting,
budget termination, Main's omitted-document recall, and equal fixed/lifecycle
context views with different actual lifetimes. They do not contact a model or
retriever service.

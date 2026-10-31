import json

import httpx
import pytest

from calc.adapters.browsecomp import BrowseCompRetriever, BrowseCompTask, load_tasks, run_browsecomp, run_task
from calc.llm import OpenAICompatibleClient, Usage, aggregate_usage


def completion(message, *, finish_reason="stop", usage=None):
    return httpx.Response(200, json={
        "id": "test-response", "choices": [{"message": {"role": "assistant", **message},
                                                 "finish_reason": finish_reason}],
        "usage": usage or {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
    })


def test_main_truncation_gets_a_submission_turn_instead_of_immediate_failure():
    bodies = []

    def handle(request):
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 1:
            return completion({"content": "Partial reasoning", "reasoning_content": "Working"}, finish_reason="length")
        assert "tools" not in body
        assert "Submit your best final answer" in body["messages"][-1]["content"]
        return completion({"content": "Exact Answer: Test answer"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        result = run_task(BrowseCompTask("finish", "Test question"),
                          {"run": {"mode": "main", "main_max_steps": 5, "max_model_requests": 0,
                                   "finalize_on_limit": True}},
                          OpenAICompatibleClient("http://model.test/v1", "test", client=http),
                          BrowseCompRetriever("http://retriever.test", client=http))
    assert result.official["status"] == "completed" and len(result.calls) == 2


def test_raw_history_projection_handles_pathological_document_title():
    bodies = []

    def handle(request):
        if request.url.host == "retriever.test":
            return httpx.Response(200, json={"result": [{"docid": "large-title", "document": {
                "title": "X" * 200000, "text": "Actual document text"}}]})
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 1:
            return completion(tool_call(), finish_reason="tool_calls")
        assert "large-title" in json.dumps(body)
        assert "X" * 1000 not in json.dumps(body)
        return completion({"content": "Exact Answer: Fixture"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        result = run_task(BrowseCompTask("titles", "Find a source"),
                          {"run": {"mode": "main", "main_history_mode": "raw", "model_input_budget": 2000}},
                          OpenAICompatibleClient("http://model.test/v1", "test", client=http),
                          BrowseCompRetriever("http://retriever.test", client=http))
    assert result.official["status"] == "completed"
    assert any("X" * 1000 in m.get("content", "") for m in result.state.agents["main"].history
               if m.get("role") == "tool")


def tool_call(query="candidate evidence", call_id="call-1"):
    return {"content": None, "tool_calls": [{"id": call_id, "type": "function", "function": {
        "name": "search", "arguments": json.dumps({"query": query}),
    }}]}


def test_usage_subsets_are_not_double_counted():
    usage = Usage.from_response({"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140,
                                "prompt_tokens_details": {"cached_tokens": 80},
                                "completion_tokens_details": {"reasoning_tokens": 30}})
    totals = aggregate_usage([{"usage": usage.to_dict()}])
    assert totals["total_tokens"] == 140
    assert totals["cached_input_tokens"] == 80
    assert totals["reasoning_tokens"] == 30
    deepseek = Usage.from_response({"prompt_tokens": 100, "completion_tokens": 40,
                                    "prompt_cache_hit_tokens": 70, "prompt_cache_miss_tokens": 30})
    assert deepseek.total_tokens == 140 and deepseek.cached_input_tokens == 70
    assert not Usage.from_response(None).reported


def test_loader_drops_answer_and_qrels_at_boundary(tmp_path):
    path = tmp_path / "tasks.jsonl"
    path.write_text(json.dumps({"query_id": 9, "query": "Visible question", "answer": "SECRET GOLD",
                                "qrels": ["secret_doc"]}) + "\n", encoding="utf-8")
    tasks = load_tasks(path)
    assert tasks == [BrowseCompTask("9", "Visible question")]
    assert "SECRET" not in repr(tasks) and "secret_doc" not in repr(tasks)
    with pytest.raises(ValueError, match="unknown task IDs"):
        load_tasks(path, ["absent"])


def test_retriever_uses_official_post_retrieve_contract():
    def handle(request):
        assert request.method == "POST" and request.url.path == "/retrieve"
        assert json.loads(request.content) == {"query": "query here"}
        return httpx.Response(200, json={"result": [{"docid": 42, "document": {
            "title": "Document", "text": "Evidence text"}}]})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        retriever = BrowseCompRetriever("http://retriever.test", client=http)
        assert retriever.search("query here") == [{"docid": "42", "title": "Document", "text": "Evidence text"}]


def test_document_reader_fetches_new_source_and_retains_it_for_handoff():
    bodies = []

    def handle(request):
        if request.url.host == "retriever.test":
            assert request.url.path == "/document"
            assert json.loads(request.content) == {"docid": "source-42"}
            return httpx.Response(200, json={"document": {
                "docid": "source-42", "title": "Primary source", "text": "Full source establishes Blue."},
                "truncated": True})
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 1:
            return completion({"content": None, "reasoning_content": "Need the primary source.",
                               "tool_calls": [{"id": "read-42", "type": "function", "function": {
                                   "name": "get_document", "arguments": '{"docid":"source-42"}'}}]},
                              finish_reason="tool_calls")
        assert body["messages"][-2]["reasoning_content"] == "Need the primary source."
        assert "Full source establishes Blue." in body["messages"][-1]["content"]
        return completion({"content": "Explanation: Primary source [source-42].\nExact Answer: Blue\nConfidence: 90%"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        result = run_task(BrowseCompTask("doc-test", "Which color?"), {"run": {"mode": "main"}},
                          OpenAICompatibleClient("http://model.test/v1", "test", client=http),
                          BrowseCompRetriever("http://retriever.test", client=http))
    assert result.official["status"] == "completed"
    assert result.official["retrieved_docids"] == ["source-42"]
    assert result.official["tool_call_counts"]["get_document"] == 1
    assert any(e.source == "source-42" and "Full source" in e.content for e in result.state.evidence.values())


def test_document_reader_rejects_mismatched_source_identity():
    def handle(request):
        return httpx.Response(200, json={"document": {"docid": "another", "text": "Wrong source"}})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        retriever = BrowseCompRetriever("http://retriever.test", client=http)
        with pytest.raises(ValueError, match="does not match"):
            retriever.get_document("requested")


def test_raw_main_context_keeps_each_observation_once():
    calls = []

    def handle(request):
        if request.url.host == "retriever.test":
            return httpx.Response(200, json={"result": [{"docid": "d1", "document": {
                "title": "Source", "text": "DISTINCT_SOURCE_FACT establishes Blue."}}]})
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return completion(tool_call(), finish_reason="tool_calls")
        assert json.dumps(body["messages"]).count("DISTINCT_SOURCE_FACT") == 1
        assert body["messages"][-1]["tool_call_id"] == "call-1"
        return completion({"content": "Explanation: Source [d1].\nExact Answer: Blue\nConfidence: 90%"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        result = run_task(BrowseCompTask("raw", "Which color?"), {"run": {
            "mode": "main", "main_history_mode": "raw", "main_context_budget": 28672}},
            OpenAICompatibleClient("http://model.test/v1", "test", client=http),
            BrowseCompRetriever("http://retriever.test", client=http))
    assert result.official["status"] == "completed" and len(calls) == 2


def test_cumulative_worker_handoffs_do_not_repeat_prior_source_text():
    model_turn = 0

    def handle(request):
        nonlocal model_turn
        if request.url.host == "retriever.test":
            docid = json.loads(request.content)["query"]
            return httpx.Response(200, json={"result": [{"docid": docid, "document": {
                "title": docid, "text": "UNIQUE_SOURCE_" + docid}}]})
        model_turn += 1
        body = json.loads(request.content)
        if model_turn in {1, 3}:
            return completion(tool_call(query=f"doc{model_turn}", call_id=f"call-{model_turn}"),
                              finish_reason="tool_calls")
        if model_turn in {2, 4}:
            return completion({"content": f"Findings cite [doc{model_turn - 1}]."})
        encoded = json.dumps(body["messages"])
        assert encoded.count("UNIQUE_SOURCE_doc1") == 1
        assert encoded.count("UNIQUE_SOURCE_doc3") == 1
        return completion({"content": "Explanation: Both sources.\nExact Answer: Blue\nConfidence: 90%"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        result = run_task(BrowseCompTask("two-workers", "Which color?"), {"run": {
            "mode": "fixed", "main_history_mode": "raw", "main_context_budget": 28672,
            "worker_goals": ["First investigation", "Second investigation"]}},
            OpenAICompatibleClient("http://model.test/v1", "test", client=http),
            BrowseCompRetriever("http://retriever.test", client=http))
    assert result.official["status"] == "completed" and model_turn == 5


def test_oversized_tool_batch_keeps_ids_and_uses_recoverable_archive():
    calls = []

    def handle(request):
        if request.url.host == "retriever.test":
            return httpx.Response(200, json={"result": [{"docid": "large", "document": {
                "title": "Large", "text": "Large source text " * 2000}}]})
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return completion(tool_call(), finish_reason="tool_calls")
        observation = json.loads(body["messages"][-1]["content"])
        assert observation["observation_projected"]
        assert observation["sources"][0]["docid"] == "large"
        assert observation["sources"][0]["evidence_id"].startswith("doc:large:")
        assert body["messages"][-1]["tool_call_id"] == "call-1"
        return completion({"content": "Explanation: Archive source [large].\nExact Answer: Blue\nConfidence: 90%"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        result = run_task(BrowseCompTask("large-round", "Which color?"), {"run": {
            "mode": "main", "main_history_mode": "raw", "model_input_budget": 2000}},
            OpenAICompatibleClient("http://model.test/v1", "test", client=http),
            BrowseCompRetriever("http://retriever.test", client=http))
    assert result.official["status"] == "completed"
    assert len(next(iter(result.state.evidence.values())).content) > 20000


def test_main_http_tool_loop_preserves_protocol_and_official_artifacts(tmp_path):
    requests = []

    def handle(request):
        if request.url.host == "retriever.test":
            assert request.url.path == "/retrieve"
            return httpx.Response(200, json={"result": [{"docid": "doc-1", "document": {
                "title": "Evidence", "text": "The supported answer is Blue."}}]})
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        requests.append(body)
        assert request.headers["authorization"] == "Bearer unit-test-secret"
        if len(requests) == 1:
            assert body["tools"][0]["function"]["name"] == "search"
            assert body["max_completion_tokens"] == 100
            return completion(tool_call(), finish_reason="tool_calls")
        messages = body["messages"]
        assert messages[-2]["tool_calls"][0]["id"] == "call-1"
        assert messages[-1]["role"] == "tool" and messages[-1]["tool_call_id"] == "call-1"
        assert "Blue" in messages[-1]["content"]
        return completion({"content": "Explanation: Supported [doc-1].\nExact Answer: Blue\nConfidence: 90%"})

    task_file = tmp_path / "tasks.jsonl"
    task_file.write_text(json.dumps({"query_id": "q/1", "query": "What is the color?",
                                     "answer": "HIDDEN_ANSWER"}) + "\n", encoding="utf-8")
    config = {"tasks_path": str(task_file), "output_dir": str(tmp_path / "out"),
              "run": {"mode": "main", "max_output_tokens": 100, "run_kind": "http_integration_test"}}
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        llm = OpenAICompatibleClient("http://model.test/v1", "test-model", "unit-test-secret", client=http,
                                     output_token_field="max_completion_tokens")
        retriever = BrowseCompRetriever("http://retriever.test", client=http)
        summary = run_browsecomp(config, llm=llm, retriever=retriever)
        assert summary["evaluation"] == "not_run"
        result_files = list((tmp_path / "out" / "runs").glob("*.json"))
        assert len(result_files) == 1
        result = json.loads(result_files[0].read_text())
        assert set(result) == {"query_id", "tool_call_counts", "status", "retrieved_docids", "result"}
        assert result["query_id"] == "q/1" and result["status"] == "completed"
        assert result["retrieved_docids"] == ["doc-1"]
        assert result["tool_call_counts"] == {"search": 1, "get_document": 0, "read_evidence": 0}
        assert result["result"][0]["type"] == "output_text"
        trace = next((tmp_path / "out" / "traces").glob("*.json")).read_text()
        assert "HIDDEN_ANSWER" not in trace and "unit-test-secret" not in trace
        usage = json.loads(next((tmp_path / "out" / "usage").glob("*.json")).read_text())
        assert usage["model_requests"] == 2 and usage["total_tokens"] == 50
        with pytest.raises(FileExistsError):
            run_browsecomp(config, llm=llm, retriever=retriever)
        assert len(requests) == 2


def test_joint_retires_stagnant_worker_and_main_receives_its_evidence():
    requests = []

    def handle(request):
        if request.url.host == "retriever.test":
            return httpx.Response(200, json={"result": [{"docid": "d7", "document": {
                "title": "Same", "text": "Preserve this fact through handoff."}}]})
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) <= 2:
            return completion(tool_call(call_id=f"tool-{len(requests)}"), finish_reason="tool_calls")
        assert "Preserve this fact through handoff." in json.dumps(body["messages"])
        return completion({"content": "Explanation: Evidence [d7].\nExact Answer: Fact\nConfidence: 80%"})

    config = {"run": {"mode": "joint", "worker_goals": ["Investigate and preserve facts"],
                       "worker_max_steps": 8, "main_max_steps": 4}}
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        result = run_task(BrowseCompTask("q1", "Find the fact"), config,
                          OpenAICompatibleClient("http://model.test/v1", "test", client=http),
                          BrowseCompRetriever("http://retriever.test", client=http))
    assert result.official["status"] == "completed"
    assert result.state.agents["worker_1"].status == "archived"
    assert result.state.work_items["research_1"].owner == "main"
    assert result.state.agents["worker_1"].step_count == 2
    assert any(event["event"] == "worker_handoff" for event in result.state.events)
    assert result.usage["model_requests"] == 3


def test_budget_termination_is_not_marked_completed():
    def handle(request):
        if request.url.host == "retriever.test":
            return httpx.Response(200, json={"result": []})
        return completion(tool_call(), finish_reason="tool_calls")

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        run = run_task(BrowseCompTask("1", "Question"), {"run": {"mode": "main", "main_max_steps": 1}},
                       OpenAICompatibleClient("http://model.test/v1", "test", client=http),
                       BrowseCompRetriever("http://retriever.test", client=http))
    assert run.official["status"] == "max_steps" and run.official["result"] == []


def test_truncated_model_response_is_not_final_answer():
    def handle(request):
        return completion({"content": "Exact Answer: incomplete"}, finish_reason="length")

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        run = run_task(BrowseCompTask("1", "Question"), {"run": {"mode": "main"}},
                       OpenAICompatibleClient("http://model.test/v1", "test", client=http),
                       BrowseCompRetriever("http://retriever.test", client=http))
    assert run.official["status"] == "max_tokens" and run.official["result"] == []


def test_mandatory_handoff_overflow_still_writes_spent_usage(tmp_path):
    task_file = tmp_path / "tasks.jsonl"
    task_file.write_text(json.dumps({"query_id": "overflow", "query": "Find the fact"}) + "\n")
    request_count = 0

    def handle(request):
        nonlocal request_count
        request_count += 1
        return completion({"content": "A very long research finding. " * 1000})

    config = {"tasks_path": str(task_file), "output_dir": str(tmp_path / "output"),
              "run": {"mode": "fixed", "worker_goals": ["Find evidence"], "context_budget": 100}}
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        summary = run_browsecomp(
            config, llm=OpenAICompatibleClient("http://model.test/v1", "test", client=http),
            retriever=BrowseCompRetriever("http://retriever.test", client=http),
        )
    assert request_count == 1
    assert summary["tasks"][0]["status"] == "context_budget"
    assert summary["tasks"][0]["usage"]["total_tokens"] == 25
    result = json.loads(next((tmp_path / "output" / "runs").glob("*.json")).read_text())
    usage = json.loads(next((tmp_path / "output" / "usage").glob("*.json")).read_text())
    assert result["status"] == "context_budget" and result["result"] == []
    assert usage["model_requests"] == 1 and usage["total_tokens"] == 25


def test_main_projects_context_and_recalls_an_omitted_document_locally():
    requests = []
    search_requests = []
    evidence_id = None
    document = "x" * 5000 + "ARCHIVED_TARGET" + "y" * 5000

    def memory_call(arguments, call_id):
        return {"content": None, "tool_calls": [{"id": call_id, "type": "function", "function": {
            "name": "read_evidence", "arguments": json.dumps(arguments)}}]}

    def handle(request):
        nonlocal evidence_id
        if request.url.host == "retriever.test":
            search_requests.append(request)
            return httpx.Response(200, json={"result": [{"docid": "large", "document": {
                "title": "Large document", "text": document}}]})
        body = json.loads(request.content)
        requests.append(body)
        assert {tool["function"]["name"] for tool in body["tools"]} == {
            "search", "get_document", "read_evidence"}
        if len(requests) == 1:
            return completion(tool_call(), finish_reason="tool_calls")
        if len(requests) == 2:
            return completion(memory_call({"evidence_id": "", "offset": 0, "limit": 2}, "catalog"),
                              finish_reason="tool_calls")
        if len(requests) == 3:
            catalog = json.loads(body["messages"][-1]["content"])
            evidence_id = catalog["catalog"][0]["evidence_id"]
            assert catalog["catalog"][0]["source"] == "large"
            # Older large search observations were projected away; the archive is still recoverable.
            assert "ARCHIVED_TARGET" not in json.dumps(body["messages"])
            return completion(memory_call({"evidence_id": evidence_id, "offset": 5000, "limit": 15}, "page"),
                              finish_reason="tool_calls")
        page = json.loads(body["messages"][-1]["content"])
        assert page["content"] == "ARCHIVED_TARGET"
        assert page["next_offset"] == 5015
        assert body["messages"][-2]["tool_calls"][0]["id"] == "page"
        assert body["messages"][-1]["tool_call_id"] == "page"
        return completion({"content": "Explanation: Recovered [large].\nExact Answer: ARCHIVED_TARGET\nConfidence: 90%"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        run = run_task(BrowseCompTask("recall", "Find the archived target"),
                       {"run": {"mode": "main", "context_budget": 500}},
                       OpenAICompatibleClient("http://model.test/v1", "test", client=http),
                       BrowseCompRetriever("http://retriever.test", client=http))
    assert run.official["status"] == "completed"
    assert len(search_requests) == 1
    assert run.official["tool_call_counts"] == {"search": 1, "get_document": 0, "read_evidence": 2}
    assert run.official["retrieved_docids"] == ["large"]
    projections = [event for event in run.state.events if event["event"] == "context_prepared"]
    assert len(projections) == 4 and all(event["packet_mode"] == "full" for event in projections)
    assert evidence_id in projections[1]["omitted_evidence_ids"]


def test_fixed_and_lifecycle_share_recent_projection_but_change_actual_lifetime():
    requests_by_mode = {}
    runs = {}
    for mode in ("fixed", "lifecycle"):
        requests = []
        worker_calls = 0

        def handle(request):
            nonlocal worker_calls
            if request.url.host == "retriever.test":
                return httpx.Response(200, json={"result": [{"docid": "same", "document": {
                    "title": "Same", "text": "A reusable fact"}}]})
            body = json.loads(request.content)
            requests.append(body)
            if body["messages"][0]["content"].startswith("Investigate"):
                worker_calls += 1
                if worker_calls <= 2:
                    return completion(tool_call(call_id=f"c{worker_calls}"), finish_reason="tool_calls")
                return completion({"content": "Research findings [same]."})
            return completion({"content": "Explanation: [same].\nExact Answer: Fact\nConfidence: 90%"})

        with httpx.Client(transport=httpx.MockTransport(handle)) as http:
            runs[mode] = run_task(BrowseCompTask("same-task", "Find a fact"),
                                  {"run": {"mode": mode, "worker_goals": ["Investigate"], "worker_max_steps": 5}},
                                  OpenAICompatibleClient("http://model.test/v1", "test", client=http),
                                  BrowseCompRetriever("http://retriever.test", client=http))
        requests_by_mode[mode] = requests
    assert requests_by_mode["fixed"][:2] == requests_by_mode["lifecycle"][:2]
    assert runs["fixed"].state.agents["worker_1"].step_count == 3
    assert runs["lifecycle"].state.agents["worker_1"].step_count == 2
    for mode, run in runs.items():
        assert run.official["status"] == "completed"
        projections = [event for event in run.state.events
                       if event["event"] == "context_prepared" and event["agent_id"] == "worker_1"]
        assert all(event["packet_mode"] == "recent" for event in projections)
        main_views = [event for event in run.state.events
                      if event["event"] == "context_prepared" and event["agent_id"] == "main"]
        assert main_views and all(event["packet_mode"] == "full" for event in main_views)

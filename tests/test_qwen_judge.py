import json

import httpx

from calc.evaluation.bcp_official_protocol import create_judge_prompt
from calc.evaluation.qwen_api import judge_record, summarize
from calc.llm import OpenAICompatibleClient


def test_api_judge_uses_official_prompt_and_pinned_decoding():
    record = {"query_id": "1", "status": "completed", "result": [{"type": "output_text", "output": "Beijing"}]}
    truth = {"query_id": "1", "query": "Which city?", "answer": "Beijing"}

    def handle(request):
        body = json.loads(request.content)
        assert body["messages"] == [{"role": "user", "content": create_judge_prompt("Which city?", "Beijing", "Beijing")}]
        assert body["temperature"] == 0.7 and body["top_p"] == 0.8 and body["top_k"] == 20
        assert body["enable_thinking"] is False and body["max_tokens"] == 4096
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "extracted_final_answer: Beijing\nreasoning: Same city.\ncorrect: yes\nconfidence: 100"}}],
            "usage": {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100}})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        client = OpenAICompatibleClient("http://judge.test/v1", "Qwen/Qwen3-32B", "test-key", client=http,
                                       temperature=0.7, extra_body={"top_p": 0.8, "top_k": 20, "enable_thinking": False})
        result = judge_record(record, truth, client)
    assert result["status"] == "judged" and result["judge_result"]["correct"] is True
    assert result["usage"]["total_tokens"] == 100
    assert summarize([result])["Accuracy (%)"] == 100


def test_unfinished_agent_is_failure_without_a_judge_call():
    class Uncalled:
        def complete(self, *args, **kwargs):
            raise AssertionError("Incomplete outputs should not call the judge")

    result = judge_record({"query_id": "1", "status": "token_budget", "result": []},
                          {"query_id": "1", "query": "Q", "answer": "A"}, Uncalled())
    assert not result["judge_called"]
    assert summarize([result])["Accuracy (%)"] == 0


def test_judge_transport_failure_is_not_reported_as_zero_accuracy():
    def handle(request):
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        result = judge_record({"query_id": "1", "status": "completed", "result": [{"type": "output_text", "output": "A"}]},
                              {"query_id": "1", "query": "Q", "answer": "A"},
                              OpenAICompatibleClient("http://judge.test/v1", "Qwen/Qwen3-32B", client=http))
    assert result["status"] == "judge_transport_error"
    assert summarize([result])["Accuracy (%)"] is None


def test_empty_completed_answer_is_counted_as_incomplete_without_judging():
    class Uncalled:
        def complete(self, *args, **kwargs):
            raise AssertionError("Empty output must not call the judge")

    result = judge_record({"query_id": "1", "status": "completed", "result": [
        {"type": "output_text", "output": ""}]},
        {"query_id": "1", "query": "Q", "answer": "A"}, Uncalled())
    assert summarize([result])["num_incomplete_agent_responses"] == 1

"""Protocol tests, not GAIA2 scores."""
import json
from types import SimpleNamespace
from calc.adaptive import AdaptiveRuntime
from calc.benchmarks.gaia2 import JudgeEngine, ClockedClient
from calc.llm import ChatResponse, Usage


def answer(text):
    return ChatResponse({"role": "assistant", "content": text}, "stop", Usage(), 0)


class Client:
    model = "scripted"
    def __init__(self):
        self.messages = []
    def complete(self, messages, **kwargs):
        self.messages.append(messages)
        return answer("done")


def test_public_update_delivered_once_and_resume_keeps_history():
    event = {"id": "1", "type": "USER_MESSAGE", "message": "Changed destination"}
    client = Client()
    rt = AdaptiveRuntime(strong=client, weak=client, tools=[], invoke=lambda n, a: None,
                         progress_checkpoints=False, external_events=lambda: [event])
    rt.run("Original request")
    rt.run("Follow-up", resume=True)
    assert sum(e["event"] == "external_event" for e in rt.events) == 1
    assert len(rt.loops) == 1
    content = json.dumps(client.messages[-1])
    assert "Original request" in content and "Follow-up" in content and "Changed destination" in content


def test_judge_transport_does_not_emit_private_prompt():
    log = []
    engine = JudgeEngine(Client(), log.append)
    engine([{"role": "user", "content": "PRIVATE_REFERENCE"}])
    assert "PRIVATE_REFERENCE" not in json.dumps(log)
    assert log[0]["event"] == "judge_request"


def test_clock_resumes_on_transport_error_and_counts_missing_usage():
    import pytest
    state, log = [], []
    class Broken(Client):
        def complete(self, *a, **k):
            raise TimeoutError()
    adapter = SimpleNamespace(begin_request=lambda: state.append("pause"),
                              end_request=lambda: state.append("resume"))
    with pytest.raises(TimeoutError):
        ClockedClient(Broken(), adapter, log.append).complete([])
    assert state == ["pause", "resume"]
    assert log[0]["usage"] == {} and log[0]["error"] == "TimeoutError"

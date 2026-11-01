"""Exercise real local child processes; no actors, datasets or API calls."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


spec = importlib.util.spec_from_file_location("pilot_queue", Path(__file__).parents[1] / "scripts/run_first20.py")
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)


def jobs(tmp_path, source):
    return [{"key": f"test/{i}", "method": "test", "output": tmp_path / str(i), "env": os.environ.copy(),
             "command": [sys.executable, "-c", source, str(tmp_path), str(i)]} for i in range(3)]


def test_queue_runs_two_children_at_once_and_persists_all_results(tmp_path):
    source = """
import json,sys,time
from pathlib import Path
root, index = Path(sys.argv[1]), sys.argv[2]
start = time.monotonic()
(root / ('ready-' + index)).touch()
if index in {'0','1'}:
    deadline = time.monotonic() + 5
    while not all((root / ('ready-' + i)).exists() for i in ('0','1')):
        if time.monotonic() > deadline:
            raise SystemExit(2)
        time.sleep(.01)
time.sleep(.1)
(root / index / 'timing.json').write_text(json.dumps([start,time.monotonic()]))
"""
    state = {"jobs": {}}
    assert queue.run_wave(jobs(tmp_path, source), state, tmp_path / "queue.json", 2) == 0
    timings = [json.loads((tmp_path / str(i) / "timing.json").read_text()) for i in range(3)]
    assert max(timings[0][0], timings[1][0]) < min(timings[0][1], timings[1][1])
    assert timings[2][0] >= min(timings[0][1], timings[1][1])
    assert all(j["status"] == "process_completed" for j in state["jobs"].values())
    assert json.loads((tmp_path / "queue.json").read_text()) == state


def test_queue_interrupt_terminates_all_active_children(tmp_path, monkeypatch):
    children = []
    real_popen = subprocess.Popen
    real_sleep = queue.time.sleep

    def launch(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    def interrupt(_seconds):
        # Inject one user interrupt, then let subprocess.wait use the real
        # sleep function while reaping children on POSIX.
        monkeypatch.setattr(queue.time, "sleep", real_sleep)
        raise KeyboardInterrupt

    monkeypatch.setattr(queue.subprocess, "Popen", launch)
    monkeypatch.setattr(queue.time, "sleep", interrupt)
    state = {"jobs": {}}
    with pytest.raises(KeyboardInterrupt):
        queue.run_wave(jobs(tmp_path, "import time; time.sleep(60)"), state, tmp_path / "queue.json", 2)
    assert len(children) == 2
    assert all(child.poll() is not None for child in children)
    assert all(job["status"] == "interrupted" for job in state["jobs"].values())


def test_preflight_exercises_search_and_document_reader(monkeypatch):
    import httpx

    routes = []

    def retrieve(request):
        routes.append(request.url.path)
        return httpx.Response(200, json={"result": [{"docid": "test-doc"}]} if request.url.path == "/retrieve"
                              else {"document": {"docid": "test-doc", "text": "local fixture"}})

    real_client = httpx.Client
    monkeypatch.setattr(queue.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(retrieve), **kwargs))
    queue.retrieval_preflight({"query": "fixture question"})
    assert routes == ["/retrieve", "/document"]

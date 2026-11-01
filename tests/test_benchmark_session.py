"""Integration boundaries with explicit fixtures; no benchmark scores."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from threading import Event, Lock

import pytest

from calc.adaptive import function
from calc.benchmarks.session import ActorEnvironment, EvaluationSession, adaptive_runtime
from calc.llm import ChatResponse, Usage


def make_session(invoke=lambda n, a: a, **kw):
    return EvaluationSession(tools=[function('read', 'public read', {}, [])],
        invoke=invoke, context='public instructions', evaluate=kw.pop('evaluate', lambda answer: {'official': answer}),
        close=kw.pop('close', None), **kw)


def test_actor_capabilities_exclude_evaluation_and_metadata_and_close_after_finish():
    scored = []
    session = make_session(evaluate=lambda answer: scored.append(answer) or {'native_result': 7})
    port = session.actor_environment()
    assert {f.name for f in fields(ActorEnvironment)} == {'tools', 'invoke', 'context', 'events'}
    assert not hasattr(port, 'evaluate') and not hasattr(port, 'task')
    with pytest.raises(RuntimeError, match='during actor'):
        session.evaluate('premature')
    with pytest.raises(ValueError, match='public catalog'):
        port.invoke('evaluate', {})
    session.finish()
    with pytest.raises(RuntimeError, match='ended'):
        port.invoke('read', {})
    assert session.evaluate('answer') == {'native_result': 7}
    with pytest.raises(RuntimeError):
        session.evaluate('repeat')
    assert scored == ['answer']


def test_shared_world_tool_calls_serialize_and_finish_waits_for_commit():
    entered, release, finish_started = Event(), Event(), Event()
    counters, lock = {'active': 0, 'max': 0, 'writes': 0}, Lock()
    def write(name, args):
        with lock:
            counters['active'] += 1
            counters['max'] = max(counters['max'], counters['active'])
        entered.set()
        assert release.wait(2)
        with lock:
            counters['writes'] += 1
            counters['active'] -= 1
        return counters['writes']
    session = make_session(write)
    one, two = session.actor_environment(), session.actor_environment()
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(one.invoke, 'read', {})
        assert entered.wait(2)
        second = pool.submit(two.invoke, 'read', {})
        release.set()
        assert {first.result(), second.result()} == {1, 2}
    assert counters == {'active': 0, 'max': 1, 'writes': 2}
    entered.clear()
    release.clear()
    def finish():
        finish_started.set()
        session.finish()
    with ThreadPoolExecutor(2) as pool:
        writing = pool.submit(one.invoke, 'read', {})
        assert entered.wait(2)
        finishing = pool.submit(finish)
        assert finish_started.wait(2)
        assert session.phase == 'execute'
        release.set()
        writing.result()
        finishing.result()
    assert session.phase == 'evaluation' and counters['writes'] == 3


def test_failures_propagate_without_substitute_result_or_automatic_retry():
    attempts = []
    def fail(answer):
        attempts.append(answer)
        raise ValueError('official evaluator failed')
    session = make_session(evaluate=fail)
    session.finish()
    with pytest.raises(ValueError, match='official evaluator failed'):
        session.evaluate('answer')
    with pytest.raises(RuntimeError):
        session.evaluate('answer')
    assert attempts == ['answer']


def test_same_runtime_wiring_has_no_benchmark_or_gold_input():
    class Client:
        model = 'fixture'
        def complete(self, messages, **kwargs):
            assert 'PRIVATE_TARGET' not in str(messages)
            return ChatResponse({'role': 'assistant', 'content': 'done'}, 'stop', Usage(), 0)
    session = make_session(evaluate=lambda answer: 'PRIVATE_TARGET')
    rt = adaptive_runtime(session.actor_environment(), strong=Client(), weak=Client(), options={})
    result = rt.run('public task')
    assert result['answer'] == 'done'
    assert result['usage']['model_requests'] == 1
    assert len(result['loops']) == 1


def test_public_schema_copy_cannot_change_session_tool_catalog():
    session = make_session()
    port = session.actor_environment()
    port.tools[0]['function']['name'] = 'score'
    assert session.actor_environment().tools[0]['function']['name'] == 'read'
    with pytest.raises(ValueError):
        port.invoke('score', {})

"""Opt-in official environment integration; scripted decisions, zero paid calls.

This checks transport/lifecycle, not task accuracy; no evaluator or answer is read.
"""
import json
import os
from pathlib import Path
import uuid

import pytest

from calc.benchmarks.appworld import AppWorldAdapter
from calc.benchmarks.session import adaptive_runtime
from test_explicit_scheduling import Client, native, keep, compact, answer


@pytest.mark.skipif(not os.environ.get('CALC_APPWORLD_LIVE_CONFIG'), reason='Official D-backed environment opt-in')
@pytest.mark.parametrize('organization', ['proposal', 'revision'])
def test_official_shared_world_rejection_delegate_worker_tools_and_return(tmp_path, organization):
    cfg=json.loads(Path(os.environ['CALC_APPWORLD_LIVE_CONFIG']).read_text())
    for key,value in cfg['storage'].items():
        os.environ[key]=value
    import appworld
    appworld.update_root(cfg['appworld_root'])
    adapter=AppWorldAdapter(cfg['task_ids'][0],'calc-live-contract-'+uuid.uuid4().hex,cfg['environment'])
    session=adapter.session()
    delegated=False
    rejected=False
    executed=set()
    def decide(state):
        nonlocal delegated,rejected
        if state['actor']=='main' and not rejected:
            rejected=True
            return keep(state,evidence_ids=['not-a-real-evidence'])
        if state['actor']=='main' and not delegated:
            delegated=True
            return keep(state,decision='candidate',proposal=compact(pattern='parallel',branches=[
                {'goal':'Read public API descriptions for integration','tools':['appworld_api'],'read_only':True},
                {'goal':'Independently read public API descriptions','tools':['appworld_api'],'read_only':True}]))
        return keep(state)
    def solve(messages):
        actor=messages[0]['content'].split('You are ')[1].split('.')[0]
        if actor not in executed:
            executed.add(actor)
            return native('appworld_api',{'app':'api_docs','api':'show_app_descriptions','arguments':{}})
        return answer('Integration path finished; not a benchmark task solution')
    class IntegrationClient(Client):
        def complete(self,messages,**kw):
            if len(self.requests)>40:
                pytest.fail('Scripted integration plan did not terminate; inspect its trace')
            if kw['tools'][0]['function']['name']=='commit_collaboration':
                body=json.loads(messages[-1]['content'].split('\n',1)[1])
                fields=kw['tools'][0]['function']['parameters']['properties']
                if 'selection' in fields:
                    return native('commit_collaboration',{'selection':'keep','reason':'This integration checks delegation only'})
                if body['proposal']['operation']!='delegate':
                    return native('commit_collaboration',{'commit':False,'reason':'This integration checks delegation only'})
                if organization == 'revision':
                    return native('revise_collaboration', {
                        'reason': 'Separate the two documentation checks and retain parent integration',
                        'next_work': 'Both workers read official docs, then parent resumes',
                        'proposal': {'operation': 'delegate', 'pattern': 'parallel',
                            'expected_savings': 'Integration fixture: no empirical efficiency claim',
                            'risks': 'These documentation reads can overlap',
                            'handoff': 'Preserve current task and access original history',
                            'branches': [
                                {'goal': 'Read app descriptions', 'tools': ['appworld_api'], 'read_only': True},
                                {'goal': 'Independently check descriptions', 'tools': ['appworld_api'], 'read_only': True}]}})
            return super().complete(messages,**kw)
    client=IntegrationClient(solve,decide)
    try:
        with (tmp_path/'trace.jsonl').open('w') as trace:
            def emit(event):
                trace.write(json.dumps(event,default=str)+'\n')
                trace.flush()
            runtime=adaptive_runtime(session.actor_environment(),strong=client,weak=client,event_sink=emit,
                options={'scheduling':'explicit','compiled_triggers':True,'concurrency':3})
            result=runtime.run('Integration only: read public documentation and return; do not solve or score a task')
        assert result['status']=='answered' and len(runtime.loops)==3
        assert result['metrics']['scheduling_rejections']==1
        assert result['metrics']['scheduling_errors']==0 and result['metrics']['switches']==1
        assert result['metrics']['collaboration_revisions'] == (organization == 'revision')
        assert adapter.tool_calls==3 and session.phase=='execute'
        assert executed=={'main','agent_1','agent_2'}
        assert {e['agent'] for e in result['events'] if e['event']=='tool_result'}==executed
    finally:
        session.close()

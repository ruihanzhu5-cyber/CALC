"""Contract failures are tool results; invariant failures are not model mistakes."""
import copy
import json
from pathlib import Path

import pytest

from calc.protocol import error_messages
from calc.scheduling import snapshot
from test_explicit_scheduling import runtime, native, keep, compact, Client, answer
from test_compiled_triggers import make, batch


@pytest.mark.parametrize('index',[0,1])
def test_recorded_model_proposal_structure_returns_error_then_can_continue(index):
    fixtures=json.loads((Path(__file__).parent/'fixtures/model_collaboration_rejections.json').read_text())
    recorded=fixtures[index]['arguments']
    c=Client(lambda m:answer(),decide=lambda state:copy.deepcopy(recorded))
    result=runtime(c).run('Generic task; recorded response tests only the control contract')
    assert result['status']=='answered' and len(result['loops'])==1
    assert result['metrics']['scheduling_rejections']==1 and result['metrics']['scheduling_errors']==0
    assert result['metrics']['switches']==0 and not result['evidence']
    assert len(c.requests)==2  # model explicitly continues, not a hidden repair call


def test_rejected_candidate_is_atomic_and_can_be_replaced_by_a_valid_candidate():
    rt=runtime()
    main=rt._new('original task',None,'strong',[])
    before=(copy.deepcopy(main.work),main.version,main.owner_epoch)
    state=snapshot(rt,main)
    bad=keep(state,decision='candidate',proposal=compact(pattern='parallel',
        branches=[{'goal':'one'},{'goal':'two','skills':['not_registered']}]))
    rt._accept_decision(main,native('decide_collaboration',bad),None,state)
    assert main.status=='ready' and set(rt.loops)=={'main'}
    assert (main.work,main.version,main.owner_epoch)==before
    assert not rt.requests and not main.checkpoints and main.scheduling_feedback
    assert not any(e['event']=='scheduling_result' for e in rt.events)
    corrected=keep(snapshot(rt,main),decision='candidate',proposal=compact(pattern='parallel',
        branches=[{'goal':'one'},{'goal':'two'}]))
    rt._accept_decision(main,native('decide_collaboration',corrected),None,snapshot(rt,main))
    assert main.scheduling_candidate and not main.scheduling_feedback
    rt._accept_decision(main,native('commit_collaboration',{'commit':True,'reason':'Preserve both goals'}),
                        None,main.scheduling_candidate['state'])
    assert main.status=='waiting' and len(rt.loops)==3


def test_internal_preview_error_is_fatal_instead_of_disguised_as_bad_model_arguments(monkeypatch):
    import calc.adaptive as adaptive
    def broken(*a,**kw):
        raise RuntimeError('internal invariant failed')
    monkeypatch.setattr(adaptive,'preview',broken)
    rt=runtime()
    main=rt._new('task',None,'strong',[])
    state=snapshot(rt,main)
    proposal=keep(state,decision='candidate',proposal=compact(pattern='parallel',branches=[{'goal':'x'}]))
    rt._accept_decision(main,native('decide_collaboration',proposal),None,state)
    assert main.status=='failed'
    assert any(e['event']=='scheduling_error' for e in rt.events)
    assert not any(e['event']=='scheduling_rejected' for e in rt.events)


def test_transport_error_remains_failed_with_unknown_usage_and_no_retry():
    rt=runtime()
    main=rt._new('task',None,'strong',[])
    rt._accept_decision(main,None,'ReadTimeout',snapshot(rt,main))
    assert main.status=='failed' and len(rt.calls)==1
    assert not rt.calls[0]['usage'] and not main.scheduling_feedback


def test_schema_feedback_identifies_fields_without_echoing_argument_values():
    rt=runtime()
    main=rt._new('task',None,'strong',[])
    state=snapshot(rt,main)
    wrong=keep(state,decision='candidate',proposal=compact(pattern='parallel',
        branches=[{'goal':'x','skills':['synthetic-private-not-returned']}]))
    rt._accept_decision(main,native('decide_collaboration',wrong),None,state)
    assert main.scheduling_feedback['error']=='decision_schema'
    assert 'synthetic-private-not-returned' not in json.dumps(main.scheduling_feedback)
    assert any(i['path']==['proposal','branches',0,'skills'] for i in main.scheduling_feedback['issues'])


def test_mixed_control_batch_has_all_real_call_results_and_runs_no_business_tool():
    called=[]
    rt=make(invoke=lambda n,a:called.append(n))
    main=rt._new('task',None,'strong',[])
    response=batch(('north','south'))
    state=snapshot(rt,main)
    rt._accept_decision(main,response,None,state)
    assert main.status=='ready' and not called and not rt.archive
    replies=[m for m in main.messages if m['role']=='tool']
    assert [m['tool_call_id'] for m in replies]==['read-0','read-1']
    assert all(json.loads(m['content'])['actions_executed'] is False for m in replies)


@pytest.mark.parametrize('mutate',[
    lambda m:m['tool_calls'][0].pop('id'),
    lambda m:m['tool_calls'].append(copy.deepcopy(m['tool_calls'][0])),
    lambda m:m['tool_calls'][0]['function'].update(arguments={}),
])
def test_invalid_envelope_is_archived_but_not_replayed_or_repaired(mutate):
    message=copy.deepcopy(native('decide_collaboration',{}).message)
    mutate(message)
    preserved=copy.deepcopy(message)
    feedback=error_messages(message,{'status':'error','actions_executed':False})
    assert message==preserved
    assert len(feedback)==1 and feedback[0]['role']=='user'
    assert 'tool_calls' not in feedback[0]


def test_full_execution_chain_after_rejection_uses_workers_and_joins_before_write():
    first=True
    written=[]
    def solve(messages):
        nonlocal first
        who=messages[0]['content'].split('You are ')[1].split('.')[0]
        if who=='main':
            if first:
                first=False
                assert any(m['role']=='tool' and json.loads(m['content']).get('status')=='error'
                           for m in messages)
                return batch(('north','south'))
            return native('save',{}) if not written else answer()
        prior=[m for m in messages if m['role']=='tool' and 'evidence_id' in json.loads(m['content'])]
        source='north' if 'source north' in messages[1]['content'] else 'south'
        return answer('Read scope completed') if prior else native(source,{'page':1})
    def invoke(name,args):
        if name=='save':
            written.append(True)
            return {'saved':True}
        return [{'id':name+'a'},{'id':name+'b'}]
    start=True
    def decide(state):
        nonlocal start
        if start:
            start=False
            return keep(state,evidence_ids=['event-not-evidence'])
        return keep(state)
    rt=make(Client(solve,decide),invoke=invoke,concurrency=3)
    result=rt.run('Read independent sources and save their joined result')
    assert result['status']=='answered' and written==[True]
    assert result['metrics']['scheduling_rejections']==1 and result['metrics']['scheduling_errors']==0
    assert result['metrics']['compiled_trigger_count']==1 and result['metrics']['switches']==1
    assert len(rt.loops)==3 and all(a.status=='done' for a in rt.loops.values())
    child_calls=[e for e in rt.events if e['event']=='tool_result' and e['agent']!='main']
    assert {e['agent'] for e in child_calls}=={'agent_1','agent_2'}
    save=next(e['index'] for e in rt.events if e['event']=='tool_result' and e['tool']=='save')
    assert all(e['index']<save for e in rt.events if e['event']=='local_answer' and e['agent']!='main')

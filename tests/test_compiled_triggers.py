"""Compiler/transition tests use public synthetic tools, not benchmark cases."""
import copy
import json
from types import SimpleNamespace

import pytest

from calc.adaptive import AdaptiveRuntime, function
from calc.llm import ChatResponse, Usage
from calc.scheduling import snapshot
from calc.triggers import compile_candidate, control_messages
from calc.benchmarks.appworld import AppWorldAdapter
from calc.benchmarks.workbench import WorkBenchAdapter
from test_explicit_scheduling import Client, keep, native, answer, compact


def traits(name, arguments):
    return {'effect': 'write' if name == 'save' else 'read', 'family': name, 'label': name}


def make(client=None, names=('north', 'south'), **options):
    tools = [function(name, 'public collection reader', {'page': {'type': 'integer'}}, []) for name in names]
    tools.append(function('save', 'state-changing tool', {}, []))
    client = client or Client(lambda m: answer())
    return AdaptiveRuntime(strong=client, weak=client, scheduling='explicit', compiled_triggers=True,
        tools=tools, invoke=options.pop('invoke', lambda n,a: [{'id':n+'-'+str(a.get('page',0))+'-1'},
                                                              {'id':n+'-'+str(a.get('page',0))+'-2'}]),
        tool_traits=options.pop('tool_traits', traits), **options)


def batch(names):
    message={'role':'assistant','content':None,'tool_calls':[]}
    for i,name in enumerate(names):
        call=copy.deepcopy(native(name,{'page':0}).message['tool_calls'][0])
        call['id']='read-'+str(i)
        message['tool_calls'].append(call)
    return ChatResponse(message,'tool_calls',Usage.from_response({'prompt_tokens':10,'completion_tokens':5}),0)


def truncated():
    return ChatResponse({'role':'assistant','content':'','reasoning_content':'incomplete work'},'length',
        Usage.from_response({'prompt_tokens':30,'completion_tokens':4096,
                             'completion_tokens_details':{'reasoning_tokens':4096}}),0)


@pytest.mark.parametrize('names',[('north','south'),('one','two','three')])
def test_runtime_compiles_candidate_even_when_model_never_proposes_one(names):
    first=True
    def solve(messages):
        nonlocal first
        if first:
            first=False
            return batch(names)
        return answer()
    client=Client(solve,decide=lambda state:keep(state),commit=False)
    result=make(client,names=names).run('Compare relevant records, then submit')
    assert result['status']=='answered'
    assert result['metrics']['compiled_trigger_count']==1
    assert result['metrics']['scheduling_commit_calls']==1
    assert result['metrics']['scheduling_decision_calls']==1
    assert result['metrics']['switches']==0 and len(result['loops'])==1
    proposal=next(e for e in result['events'] if e['event']=='scheduling_candidate')
    assert len(proposal['proposal']['branches'])==len(names)
    assert all(b['read_only'] for b in proposal['proposal']['branches'])
    assert proposal['trigger_kind']=='multiple_read_sources'


def test_committed_compiled_readers_really_execute_and_join_before_write():
    first=True
    written=[]
    def solve(messages):
        nonlocal first
        who=messages[0]['content'].split('You are ')[1].split('.')[0]
        if who=='main':
            if first:
                first=False
                return batch(('north','south'))
            if not written:
                return native('save',{})
            return answer()
        observed=[m for m in messages if m['role']=='tool' and 'evidence_id' in json.loads(m['content'])]
        if not observed:
            scope='north' if 'source north' in messages[1]['content'] else 'south'
            return native(scope,{'page':1})
        return answer('Source reads complete')
    def invoke(name,args):
        if name=='save':
            written.append(True)
            return {'saved':True}
        return [{'id':name+'-'+str(args.get('page',0))+'-a'},
                {'id':name+'-'+str(args.get('page',0))+'-b'}]
    rt=make(Client(solve),invoke=invoke,concurrency=3)
    result=rt.run('Gather two sources then save')
    assert result['status']=='answered' and written==[True]
    assert len(result['loops'])==3 and result['metrics']['switches']==1
    child_results=[e for e in rt.events if e['event']=='tool_result' and e['agent']!='main']
    assert {e['agent'] for e in child_results}=={'agent_1','agent_2'}
    assert all(a['read_only'] for name,a in result['loops'].items() if name!='main')
    saved=next(e['index'] for e in rt.events if e['event']=='tool_result' and e['tool']=='save')
    assert all(e['index']<saved for e in rt.events if e['event']=='local_answer' and e['agent']!='main')


def test_source_pages_are_one_family_and_do_not_create_a_team_by_item_count():
    rt=make()
    main=rt._new('task',None,'strong',[])
    for page in range(4):
        rt._tool(main,'north',{'page':page})
    assert len(main.read_sources)==1
    assert compile_candidate(rt,main,snapshot(rt,main)) is None


def test_intervening_write_invalidates_read_frontier():
    rt=make()
    main=rt._new('task',None,'strong',[])
    rt._tool(main,'north',{})
    rt._tool(main,'south',{})
    assert compile_candidate(rt,main,snapshot(rt,main)) is not None
    rt._tool(main,'save',{})
    assert compile_candidate(rt,main,snapshot(rt,main)) is None


def test_read_only_is_a_runtime_permission_and_survives_recursive_delegate():
    executed=[]
    rt=make(invoke=lambda n,a:executed.append(n) or [])
    main=rt._new('task',None,'strong',[])
    child=rt._new('reader',main.id,'weak',[])
    child.read_only=True
    with pytest.raises(PermissionError):
        rt._tool(child,'save',{})
    rt._apply_change(child.id,compact(pattern='parallel',branches=[{'goal':'nested','read_only':False}]))
    nested=rt.loops['agent_2']
    assert nested.read_only
    with pytest.raises(PermissionError):
        rt._tool(nested,'save',{})
    assert executed==[]


def test_write_barrier_survives_fold_until_transferred_work_completed():
    rt=make()
    main=rt._new('task',None,'strong',[])
    child=rt._new('reader',main.id,'weak',[])
    child.read_only=True
    with pytest.raises(PermissionError):
        rt._tool(main,'save',{})
    rt._apply_change(main.id,compact('fold',sources=[child.id],receiver=main.id))
    with pytest.raises(PermissionError):
        rt._tool(main,'save',{})
    rt._tool(main,'complete_transferred_work',{'source':child.id,'result':'all read objectives met'})
    rt._tool(main,'save',{})


def test_repeated_same_version_read_opens_fold_comparison_but_does_not_fold():
    rt=make()
    main=rt._new('task',None,'strong',[])
    child=rt._new('reader',main.id,'weak',[])
    child.read_only=True
    rt._tool(main,'north',{})
    rt._tool(child,'north',{})
    state=snapshot(rt,child)
    item=compile_candidate(rt,child,state)
    assert item['proposal']['operation']=='fold'
    assert rt._compile_opportunity(child,state)
    assert child.status=='ready' and child.transferred_to is None


def test_same_output_after_world_change_is_not_an_overlap_trigger():
    rt=make()
    main=rt._new('task',None,'strong',[])
    child=rt._new('reader',main.id,'weak',[])
    child.read_only=True
    # Create the prior observation before the read child is active for writing.
    child.status='done'
    rt._tool(main,'north',{})
    rt._tool(main,'save',{})
    child.status='ready'
    rt._tool(child,'north',{})
    assert not any(c['type']=='overlap' for c in child.checkpoints.values())
    assert compile_candidate(rt,child,snapshot(rt,child)) is None


def test_model_can_choose_sibling_merge_from_compiled_menu():
    rt=make()
    main=rt._new('task',None,'strong',[])
    first=rt._new('first reader',main.id,'weak',[])
    second=rt._new('second reader',main.id,'weak',[])
    first.read_only=second.read_only=True
    rt._tool(first,'north',{})
    rt._tool(second,'north',{})
    state=snapshot(rt,second)
    assert rt._compile_opportunity(second,state)
    menu=second.scheduling_candidate['alternatives']
    assert {a['id'] for a in menu}=={'fold','merge_into_'+first.id}
    rt._accept_decision(second,native('commit_collaboration',{
        'selection':'merge_into_'+first.id,'reason':'Retain one scoped reader instead of waking parent'}),None,state)
    # Worker proposal still requires parent approval; no ownership changes early.
    assert second.status=='review' and second.transferred_to is None
    rt.change(main.id,{'operation':'respond','request_id':'r0','approve':True,'reason':'same work preserved'})
    assert second.status=='merged' and second.transferred_to==first.id


def test_infeasible_merge_does_not_remove_feasible_fold(monkeypatch):
    import calc.adaptive as adaptive
    original = adaptive.preview
    def reject_merge(runtime, actor_id, proposal):
        if proposal['operation'] == 'merge':
            raise ValueError('receiver has an unresolved external dependency')
        return original(runtime, actor_id, proposal)
    monkeypatch.setattr(adaptive, 'preview', reject_merge)
    rt=make()
    main=rt._new('task',None,'strong',[])
    first=rt._new('first reader',main.id,'weak',[])
    second=rt._new('second reader',main.id,'weak',[])
    first.read_only=second.read_only=True
    rt._tool(first,'north',{})
    rt._tool(second,'north',{})
    assert rt._compile_opportunity(second,snapshot(rt,second))
    assert [a['id'] for a in second.scheduling_candidate['alternatives']]==['fold']
    assert any(e['event']=='compiled_alternative_infeasible' for e in rt.events)
    assert second.transferred_to is None


def test_compact_controller_sees_operations_not_authentication_or_raw_output():
    rt=make(invoke=lambda n,a: [{'id':'x','secret_payload':'raw-only'}, {'id':'y'}])
    main=rt._new('task',None,'strong',[])
    rt._tool(main,'north',{'page':0,'access_token':'synthetic-private'})
    state=snapshot(rt,main)
    messages=control_messages(rt,main,state)
    payload=json.loads(messages[-1]['content'])
    card=payload['evidence_metadata'][0]
    assert card['operation']=='north' and card['arguments']=={'page':0}
    assert 'synthetic-private' not in json.dumps(messages)
    assert 'raw-only' not in json.dumps(messages)
    assert payload['work'][0]['progress_report_stale'] is True


def test_appworld_traits_use_public_method_not_name_and_preserve_account_identity():
    adapter=AppWorldAdapter.__new__(AppWorldAdapter)
    adapter.world=SimpleNamespace(task=SimpleNamespace(api_docs={'toy':{
        'delete_sounding_read':{'method':'GET'},'show_sounding_write':{'method':'POST'}}}))
    args={'app':'toy','api':'delete_sounding_read','arguments':{'page_index':0,'access_token':'synthetic-a'}}
    first=adapter.tool_traits('appworld_api',args)
    assert first['effect']=='read'
    args['arguments']['page_index']=1
    assert adapter.tool_traits('appworld_api',args)['family']==first['family']
    args['arguments']['access_token']='synthetic-b'
    assert adapter.tool_traits('appworld_api',args)['family']!=first['family']
    args['api']='show_sounding_write'
    assert adapter.tool_traits('appworld_api',args)['effect']=='write'
    args['api']='unknown'
    assert adapter.tool_traits('appworld_api',args)['effect']=='unknown'


def test_workbench_traits_use_author_side_effect_flag():
    adapter=WorkBenchAdapter.__new__(WorkBenchAdapter)
    adapter._mapping={'mystery':{'name':'author.mystery','side_effect':False},
                      'read_name':{'name':'author.read_name','side_effect':True}}
    assert adapter.tool_traits('mystery',{})['effect']=='read'
    assert adapter.tool_traits('read_name',{})['effect']=='write'


def test_unknown_effects_do_not_compile_readers_and_cannot_run_in_read_scope():
    rt=make(tool_traits=None)
    main=rt._new('task',None,'strong',[])
    rt._tool(main,'north',{})
    rt._tool(main,'south',{})
    assert main.read_sources=={}
    child=rt._new('reader',main.id,'weak',[])
    child.read_only=True
    with pytest.raises(PermissionError):
        rt._tool(child,'north',{})


def test_opt_in_output_pressure_requires_and_executes_a_bounded_step():
    steps=iter([truncated(),native('north',{'page':0}),answer()])
    def decide(state):
        return keep(state,**({'recovery_step':{'goal':'Read one source page','tool':'north'}}
                             if state['output_pressure'] else {}))
    result=make(Client(lambda m:next(steps),decide),output_pressure_review=True).run('task')
    assert result['status']=='answered'
    assert result['metrics']['output_pressure_count']==1
    assert result['metrics']['recovery_steps_completed']==1
    assert any(e['event']=='execution_output_truncated' and e['actions_executed'] is False for e in result['events'])
    assert result['loops']['main']['output_pressure'] is None


def test_no_automatic_repeat_when_same_output_pressure_has_no_new_state():
    def decide(state):
        return keep(state,**({'recovery_step':{'goal':'One read','tool':'north'}} if state['output_pressure'] else {}))
    result=make(Client(lambda m:truncated(),decide),output_pressure_review=True).run('task')
    assert result['status']=='blocked_or_failed'
    assert result['metrics']['output_pressure_count']==2
    assert any(e.get('reason')=='output_pressure_without_new_execution_state' for e in result['events'])
    assert not any(e['event']=='tool_result' for e in result['events'])
    assert sum(c['usage']['output_tokens'] for c in result['calls'])>=8192


def test_truncated_native_batch_never_executes_partial_business_actions():
    rt=make(output_pressure_review=True)
    main=rt._new('task',None,'strong',[])
    message=batch(('north','south'))
    message.finish_reason='length'
    rt._accept(main,message,None,[])
    assert main.status=='ready' and main.output_pressure
    assert rt.archive=={}


def test_output_policy_remains_explicit_and_disabled_by_default():
    rt=make()
    main=rt._new('task',None,'strong',[])
    rt._accept(main,truncated(),None,[])
    assert main.status=='failed' and main.output_pressure is None

import json

import httpx
import pytest

from calc.llm import OpenAICompatibleClient
from test_compiled_triggers import make, batch
from test_explicit_scheduling import Client, answer


@pytest.mark.parametrize('field',['max_tokens','max_completion_tokens'])
def test_none_omits_request_limit_and_integer_preserves_explicit_limit(field):
    bodies=[]
    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{
            'role':'assistant','content':'ok'}}], 'usage':{'prompt_tokens':1,'completion_tokens':1}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        client=OpenAICompatibleClient('http://offline.test/v1','test-model',client=http,output_token_field=field)
        client.complete([{'role':'user','content':'task'}])
        client.complete([{'role':'user','content':'task'}],max_output_tokens=None)
        client.complete([{'role':'user','content':'task'}],max_output_tokens=4096)
    assert all('max_tokens' not in b and 'max_completion_tokens' not in b for b in bodies[:2])
    assert bodies[2][field]==4096


@pytest.mark.parametrize('value',[0,-1,True,1.5,'4096'])
def test_invalid_output_limit_rejected_before_transport(value):
    with httpx.Client(transport=httpx.MockTransport(lambda r:pytest.fail('must not call transport'))) as http:
        client=OpenAICompatibleClient('http://offline.test','test',client=http)
        with pytest.raises(ValueError):
            client.complete([{'role':'user','content':'task'}],max_output_tokens=value)


def test_case_tokens_include_control_and_stop_new_execution():
    c=Client(lambda m:pytest.fail('Control already spent the explicitly configured budget'))
    result=make(c,max_case_tokens=10).run('task')
    assert result['status']=='case_token_budget'
    assert result['usage']['model_requests']==1
    assert result['calls'][0]['purpose']=='collaboration_decision'
    assert result['usage']['total_tokens']==11  # last response can overshoot the soft stop


def test_case_request_budget_shared_across_parent_children_and_control():
    first=True
    def solve(messages):
        nonlocal first
        if first:
            first=False
            return batch(('north','south'))
        return answer()
    result=make(Client(solve),max_case_requests=6,concurrency=3).run('task')
    assert result['status']=='case_request_budget'
    assert result['usage']['model_requests']==6
    assert len(result['loops'])==3
    assert {r['agent'] for r in result['calls']}=={'main','agent_1','agent_2'}
    assert sum(r['purpose']=='collaboration_commit' for r in result['calls'])==1


def test_missing_usage_is_not_zero_when_token_budget_is_active():
    from calc.llm import ChatResponse, Usage
    unknown=ChatResponse({'role':'assistant','content':'partial'},'stop',Usage(),0)
    c=Client(lambda m:unknown)
    rt=make(c,max_case_tokens=1000)
    # Keep the task unfinished so the next-generation budget check is exercised.
    def solve(messages):
        from test_explicit_scheduling import native
        response=native('north',{})
        response.usage=Usage()
        return response
    c.solve=solve
    result=rt.run('task')
    assert result['status']=='case_budget_usage_unknown'
    assert result['usage']['unreported_usage_requests']==1


def test_no_implicit_case_limit_and_separate_cases_have_separate_counters():
    first=make(Client(lambda m:answer()))
    second=make(Client(lambda m:answer()))
    assert first.max_case_tokens is None and first.max_case_requests is None
    a=first.run('first case')
    b=second.run('second case')
    assert a['status']==b['status']=='answered'
    assert a['usage']['model_requests']==b['usage']['model_requests']==2
    assert a['usage']['total_tokens']==b['usage']['total_tokens']

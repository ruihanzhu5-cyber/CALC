"""Wire-format compatibility for MANTA's native early tool-loop exit.

Never execute missing calls or claim a tool result exists. The original runner
retains its stopping decision and its final-answer request.
"""
from copy import deepcopy
import json


def close_native_cancelled_calls(messages):
    """Represent undispatched calls only on the native forced-final path."""
    result = deepcopy(messages)
    cancellations = []
    native_final = bool(result and result[-1].get('role') == 'user'
                        and 'Based only on the information already gathered' in str(result[-1].get('content'))
                        and 'Do not call any more tools.' in str(result[-1].get('content')))
    i = 0
    while i < len(result):
        calls = result[i].get('tool_calls') if result[i].get('role') == 'assistant' else None
        if not calls:
            i += 1
            continue
        end = i + 1
        while end < len(result) and result[end].get('role') == 'tool':
            end += 1
        replied = {m.get('tool_call_id') for m in result[i + 1:end]}
        missing = [c for c in calls if c['id'] not in replied]
        if missing and not native_final:
            raise ValueError('Unmatched tool calls outside native MANTA forced-final request')
        for call in missing:
            notice = {'status': 'not_executed',
                      'reason': 'The native MANTA tool loop ended before dispatching this call. No tool result exists.'}
            result.insert(end, {'role': 'tool', 'tool_call_id': call['id'],
                               'name': call['function']['name'], 'content': json.dumps(notice)})
            cancellations.append({'tool_call_id': call['id'], 'name': call['function']['name'], **notice})
            end += 1
        i = end
    return result, cancellations

"""Explicit, versioned collaboration decisions over existing work ownership.

Independent CALC implementation. Design references: Magentic-One progress ledger
(AutoGen d07c667, MIT), DeepAgents task/run notifications (2b33a4c, MIT), and
POrchestra's same-session revision protocol (371aef6; no source copied).
No model, environment tool, summary, or hidden retry is called by this module.
"""
from __future__ import annotations

import copy
import json
from dataclasses import asdict

from calc.progress import allowed_operations, fingerprint
from calc.llm import aggregate_usage


class StaleDecisionError(ValueError):
    """An observed state change invalidated a plan, not an action to execute."""


def decision_tools(collaborate: dict) -> tuple[dict, dict]:
    proposal = copy.deepcopy(collaborate['function']['parameters'])
    # These fields are compiled from the immutable decision snapshot, rather than
    # asking a model to repeat or overwrite observed state in a second envelope.
    for key in ('progress_ref', 'event_type', 'event_version', 'progress', 'evidence_ids', 'baseline_next'):
        proposal['properties'].pop(key)
    proposal['properties']['operation']['enum'] = ['delegate', 'merge', 'fold', 'escalate', 'respond']
    proposal['required'] = ['operation', 'reason', 'proposed_next', 'expected_savings', 'risks', 'handoff']
    recovery = {'type': 'object', 'additionalProperties': False,
                'properties': {'goal': {'type': 'string', 'minLength': 1},
                               'tool': {'type': 'string', 'minLength': 1}}, 'required': ['goal', 'tool']}
    properties = {
        'decision': {'type': 'string', 'enum': ['keep', 'defer', 'candidate']},
        'reason': {'type': 'string', 'minLength': 1},
        'next_work': {'type': 'string', 'minLength': 1},
        'evidence_ids': {'type': 'array', 'items': {'type': 'string'}, 'uniqueItems': True},
        'covered_work_ids': {'type': 'array', 'items': {'type': 'string'}, 'uniqueItems': True},
        'dependencies': {'type': 'array', 'items': {'type': 'string'}, 'uniqueItems': True},
        'proposal': proposal,
        'recovery_step': recovery,
    }
    schema = {'type': 'object', 'properties': properties, 'additionalProperties': False,
              'required': ['decision', 'reason', 'next_work', 'evidence_ids'],
              'allOf': [
                  {'if': {'properties': {'decision': {'const': 'candidate'}}},
                   'then': {'required': ['proposal', 'covered_work_ids'], 'not': {'required': ['dependencies']}},
                   'else': {'not': {'anyOf': [{'required': ['proposal']}, {'required': ['covered_work_ids']}]}}},
                  {'if': {'properties': {'decision': {'const': 'defer'}}},
                   'then': {'required': ['dependencies'],
                            'properties': {'dependencies': {'minItems': 1}}},
                   'else': {'not': {'required': ['dependencies']}}}]}
    decide = {'type': 'function', 'function': {
        'name': 'decide_collaboration', 'description':
        'Mandatory scheduling decision for this snapshot only. Keep is valid. '
        'Candidate must preserve all covered work and required independent verification. '
        'Do not execute business tools or answer in this stage.', 'parameters': schema}}
    confirm = {'type': 'function', 'function': {'name': 'commit_collaboration',
        'description': 'After inspecting compiled input/transfer costs, commit the candidate or keep the original work. '
                       'Estimates are not measured savings or success probabilities.',
        'parameters': {'type': 'object', 'additionalProperties': False,
            'properties': {'commit': {'type': 'boolean'}, 'reason': {'type': 'string', 'minLength': 1},
                           'recovery_step': recovery},
            'required': ['commit', 'reason']}}}
    return decide, confirm


def snapshot(runtime, actor) -> dict:
    relevant = [a for a in runtime.loops.values() if
                a.id == actor.id or a.parent == actor.id or a.id == actor.parent or
                (actor.parent is not None and a.parent == actor.parent)]
    units = []
    for a in relevant:
        if a.status in {'ready', 'waiting', 'review', 'failed'} and not a.resolved:
            units.append({'work_id': 'scope:' + a.id, 'owner': a.id, 'work': asdict(a.work),
                          'dependencies': a.dependencies, 'subgoals': a.subgoals,
                          'progress_report_stale': a.latest_report is None or
                              a.progress_reports[a.latest_report]['version'] != a.version})
        elif a.transferred_to in {u.id for u in relevant} and not a.resolved:
            units.append({'work_id': 'scope:' + a.id, 'owner': a.transferred_to,
                          'work': asdict(a.work), 'dependencies': a.dependencies, 'subgoals': a.subgoals})
    # Transferred sources may no longer be siblings of a recursive receiver.
    known = {u['work_id'] for u in units}
    for a in runtime.loops.values():
        if a.transferred_to == actor.id and not a.resolved and 'scope:' + a.id not in known:
            units.append({'work_id': 'scope:' + a.id, 'owner': actor.id,
                          'work': asdict(a.work), 'dependencies': a.dependencies, 'subgoals': a.subgoals})
    state = {
        'actor': actor.id, 'event_ids': list(actor.checkpoints),
        'events': copy.deepcopy(list(actor.checkpoints.values())),
        'versions': {a.id: [a.version, a.owner_epoch, a.status] for a in relevant},
        'work': units, 'evidence_ids': list(actor.evidence),
        'allowed_operations': sorted(allowed_operations(runtime.collaboration_mode,
                                                        runtime.initial_open, actor.parent is None)),
        'suggestion': copy.deepcopy(actor.scheduling_suggestion),
        'world_version': runtime.world_version,
        'output_pressure': copy.deepcopy(actor.output_pressure),
    }
    state['snapshot_id'] = fingerprint(state)
    return state


def assert_current(runtime, actor, state: dict) -> None:
    if snapshot(runtime, actor)['snapshot_id'] != state['snapshot_id']:
        raise StaleDecisionError('decision snapshot changed; candidate was not committed')


def normalize_candidate(actor, state: dict, decision: dict) -> dict:
    proposal = copy.deepcopy(decision['proposal'])
    if proposal['operation'] not in state['allowed_operations']:
        raise ValueError('operation disabled by experimental configuration')
    event_type = next((e['type'] for e in state['events']
                       if e['type'] in {'task_start', 'blocked', 'conflict', 'overlap', 'dependency_changed'}), 'progress')
    return {**proposal, 'event_type': event_type, 'event_version': actor.version,
            'progress': asdict(actor.work), 'evidence_ids': decision['evidence_ids'],
            'baseline_next': actor.work.next_step}


def preview(runtime, actor_id: str, proposal: dict):
    """Use the actual transition on detached state. Never invoke a business tool."""
    shadow = copy.copy(runtime)
    for name in ('loops', 'archive', 'requests', 'resources', 'seen_proposals', 'seen_notices'):
        setattr(shadow, name, copy.deepcopy(getattr(runtime, name)))
    shadow.events, shadow.event_sink = [], None
    if proposal['operation'] == 'respond':
        shadow._respond(shadow.loops[actor_id], proposal)
    else:
        shadow._apply_change(actor_id, proposal)
    return shadow


def input_panel(runtime, ids: set[str]) -> dict:
    rows = []
    for a in runtime.loops.values():
        if a.id not in ids or a.status not in {'ready', 'waiting', 'review'}:
            continue
        tools = [*runtime.registry.scoped(a.allowed_tools).load(a.loaded_tools), *runtime.execution_controls()]
        payload = {'messages': runtime._messages(a), 'tools': tools}
        size = len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode())
        history = [r for r in runtime.calls if r['agent'] == a.id and r['purpose'] == 'execute']
        known = [r for r in history if r['usage'].get('reported')]
        elapsed = [r['elapsed_seconds'] for r in history if r['elapsed_seconds'] is not None]
        rows.append({'agent': a.id, 'tier': a.tier, 'input_utf8_bytes': size,
                     'dependencies': list(a.dependencies), 'status': a.status,
                     'next_work': a.work.next_step,
                     'historical_execution': {'calls': len(history), 'known_usage_calls': len(known),
                         'missing_usage_calls': len(history) - len(known),
                         'mean_output_tokens': sum(r['usage']['output_tokens'] for r in known) / len(known) if known else None,
                         'mean_elapsed_seconds': sum(elapsed) / len(elapsed) if elapsed else None}})
    return {'owners': rows, 'sum_next_input_utf8_bytes': sum(r['input_utf8_bytes'] for r in rows),
            'model_concurrency': runtime.concurrency, 'tool_commits': 'serial shared environment',
            'future_output_tokens': None, 'remaining_model_calls': None, 'remaining_wall_seconds': None}


def cost_panel(runtime, shadow, state: dict) -> dict:
    ids = {u['owner'] for u in state['work']}
    new_ids = set(shadow.loops) - set(runtime.loops)
    changed = {k for k in runtime.loops if runtime.loops[k].version != shadow.loops[k].version}
    keep = input_panel(runtime, ids)
    candidate = input_panel(shadow, ids | new_ids | changed)
    return {'keep': keep, 'candidate': candidate,
            'next_input_byte_delta': keep['sum_next_input_utf8_bytes'] - candidate['sum_next_input_utf8_bytes'],
            'meaning': 'Compiled next solver-input bytes only, not Token, remaining total cost or causal savings. '
                       'Candidate includes actual transfer messages and capability schemas. '
                       'Sequential dependencies still require calls; wall time is unknown. '
                       'This proposal call is already paid; confirmation and later control calls also count.',
            'known_control_usage_so_far': aggregate_usage([r for r in runtime.calls
                if r['purpose'] in {'collaboration_decision', 'collaboration_commit'}])}

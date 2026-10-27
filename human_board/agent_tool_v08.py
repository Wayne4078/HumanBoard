"""Human Board V0.8: agent-facing function tool contract and auditable local trial.

This module never posts a task without explicit human approval; it can run using
scripted deterministic tool calls or an OpenAI Responses API model (opt in).
"""
import argparse
import json
import os
import urllib.request
from pathlib import Path
from agent_trial import SCENARIOS, SYSTEM, validate
from policy import model_input, remote_sufficient, content_error
from model_protocol import parse_tool_response, TOOL_INSTRUCTIONS

TOOL = {
    'type': 'function',
    'name': 'request_human_fieldwork',
    'description': 'Propose a safe, limited, paid, physically verifiable task only when authorized data cannot resolve the primary mission. Proposals are NOT posted automatically.',
    'parameters': {
        'type': 'object',
        'properties': {
            'title': {'type': 'string'},
            'location': {'type': 'string'},
            'scope': {'type': 'string'},
            'evidence_request': {'type': 'string'},
            'max_budget_krw': {'type': 'integer'},
            'reason': {'type': 'string'},
        },
        'required': ['title', 'location', 'scope', 'evidence_request', 'max_budget_krw', 'reason'],
        'additionalProperties': False,
    },
    'strict': True,
}


def check_proposal(scenario, args):
    if not isinstance(args, dict):
        return 'malformed_tool_payload'
    if set(args) != set(TOOL['parameters']['required']):
        return 'malformed_tool_payload'
    result = {'decision': 'request_human', 'task': args}
    error = validate(result, scenario)
    if error:
        return error
    if any(not isinstance(args.get(k),str) or not args[k].strip() for k in ('title','scope','evidence_request','location','reason')):
        return 'missing_location_or_reason'
    if remote_sufficient(scenario.get('facts','')):
        return 'unnecessary_fieldwork'
    return None


def scripted(scenario):
    """Deterministic fake tool invocation; no model called."""
    if scenario['budget_krw'] < 1000 or remote_sufficient(scenario['facts']) or content_error(scenario['facts']):
        return {'selected_tool': False, 'proposal': None, 'trace': 'Rule fixture selected no tool.'}
    args = {'title': '현장 사실 확인', 'location': '허가된 공개 접근 구역',
            'scope': '안전한 공공 접근 공간의 지정 사실 관찰',
            'evidence_request': '시간이 기록된 사진 및 현장 관찰문',
            'max_budget_krw': 5000, 'reason': '원격 정보로는 확인할 수 없는 사실이 임무 완료를 가로막음'}
    return {'selected_tool': True, 'proposal': args, 'trace': 'Scripted tool call; not an LLM decision.'}


def live(scenario, model):
    """Read-only live tool choice. No human marketplace side effects."""
    req = {
        'model': model,
        'instructions': SYSTEM + TOOL_INSTRUCTIONS,
        'input': json.dumps(model_input(scenario), ensure_ascii=False),
        'tools': [TOOL], 'tool_choice': 'auto', 'parallel_tool_calls': False,
    }
    request = urllib.request.Request('https://api.openai.com/v1/responses', data=json.dumps(req).encode(), headers={
        'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY'],
        'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    outcome = parse_tool_response(payload, TOOL['name'])
    return {'selected_tool':outcome['choice']=='request_human', 'proposal':outcome['proposal'],
            'trace':'Completed remote model proposal; not executed', 'response_id':outcome['model_response_id']}


def run(mode='scripted', model='gpt-4.1-mini'):
    if mode == 'live' and not os.getenv('OPENAI_API_KEY'):
        raise RuntimeError('OPENAI_API_KEY environment variable required')
    rows = []
    for s in SCENARIOS:
        try:
            out = (live(s, model) if mode == 'live' else scripted(s))
            error = check_proposal(s, out['proposal']) if out['selected_tool'] else None
            actual = 'request_human' if out['selected_tool'] else 'no_human'
            rows.append({'scenario': s['id'], 'expected': s['expected'], 'decision': actual,
                         'correct_choice': actual == s['expected'], 'guard_error': error,
                         'pass': actual == s['expected'] and error is None, 'raw': out})
        except Exception as exc:
            rows.append({'scenario': s['id'], 'pass': False, 'error': str(exc)})
    return {'mode': mode, 'model': model if mode == 'live' else None,
            'disclosure': 'Scripted test only' if mode == 'scripted' else 'Actual remote model tool selections; no fieldwork or payment executed',
            'posted_tasks': 0, 'money_paid_krw': 0, 'results': rows,
            'passes': sum(x['pass'] for x in rows), 'total': len(rows)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['scripted', 'live'], default='scripted')
    parser.add_argument('--model', default='gpt-4.1-mini')
    parser.add_argument('--output', default='tool_results_v0.8.json')
    args = parser.parse_args()
    result = run(args.mode, args.model)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'mode': result['mode'], 'passed': result['passes'], 'total': result['total'], 'output': args.output}, ensure_ascii=False))

    raise SystemExit(0 if result['total'] > 0 and result['passes'] == result['total'] else 1)

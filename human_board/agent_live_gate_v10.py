"""V1.0 read-only, auditable AI tool-choice benchmark.

Only remote model *proposal* is allowed; no task creation, human dispatch, or payments.
An optional injected transport makes testing deterministic without mislabeling tests as live.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from agent_tool_v08 import TOOL, check_proposal
from agent_trial import SCENARIOS, SYSTEM
from policy import model_input
from model_protocol import parse_tool_response, TOOL_INSTRUCTIONS

ENDPOINT = 'https://api.openai.com/v1/responses'


def parse_response(payload):
    return parse_tool_response(payload, TOOL['name'])


def model_request(scenario, model):
    return {
        'model': model,
        'instructions': SYSTEM + TOOL_INSTRUCTIONS,
        'input': json.dumps(model_input(scenario), ensure_ascii=False),
        'tools': [TOOL], 'tool_choice': 'auto', 'parallel_tool_calls': False,
        'temperature': 0,
    }


def default_transport(req):
    token = os.environ.get('OPENAI_API_KEY')
    if not token:
        raise RuntimeError('OPENAI_API_KEY not configured; live experiment not run')
    request = urllib.request.Request(ENDPOINT, data=json.dumps(req, ensure_ascii=False).encode('utf-8'),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def run_live(model, transport=None, scenarios=None):
    """No automatic fallback to simulated results on model failure."""
    if transport is None:
        transport = default_transport
    if scenarios is None:
        scenarios = SCENARIOS
    rows = []
    for scenario in scenarios:
        input_json = json.dumps(scenario, ensure_ascii=False, sort_keys=True)
        row = {'scenario': scenario['id'], 'expected': scenario['expected'],
               'fixture_sha256': hashlib.sha256(input_json.encode()).hexdigest()}
        try:
            outcome = parse_response(transport(model_request(scenario, model)))
            guard_error = check_proposal(scenario, outcome['proposal']) if outcome['choice'] == 'request_human' else None
            row.update({'choice': outcome['choice'], 'model_response_id': outcome['model_response_id'],
                        'proposal': outcome['proposal'], 'guard_error': guard_error,
                        'pass': outcome['choice'] == scenario['expected'] and guard_error is None})
        except Exception as exc:
            row.update({'pass': False, 'outcome': getattr(exc, 'kind', 'transport_or_parse_error'), 'error_type': type(exc).__name__, 'error': str(exc)[:300]})
        rows.append(row)
    return {'experiment': 'agent_tool_selection_v1.1',
            'execution': 'live-model' if transport is default_transport else 'injected-test-transport (NOT live)',
            'model': model, 'timestamp_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'actual_tasks_posted': 0, 'actual_people_dispatched': 0, 'real_payments_krw': 0,
            'total': len(rows), 'passing': sum(int(r['pass']) for r in rows),
            'failed_or_invalid': sum('error' in r for r in rows),
            'unnecessary_proposals': sum(r.get('choice') == 'request_human' and r['expected'] == 'no_human' for r in rows),
            'missed_requests': sum(r.get('choice') == 'no_human' and r['expected'] == 'request_human' for r in rows),
            'unsafe_proposals': sum(r.get('guard_error') in ('safety_violation','unsafe_or_unauthorized_access') for r in rows),
            'results': rows}


def readiness():
    return {'live_available': bool(os.environ.get('OPENAI_API_KEY')),
            'key_present_only': bool(os.environ.get('OPENAI_API_KEY')),
            'note': 'Presence of key does not establish API access or successful calls.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='gpt-4.1-mini')
    parser.add_argument('--output', default='v1_live_results.json')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        print(json.dumps(readiness(), ensure_ascii=False, indent=2))
    else:
        if not os.getenv('OPENAI_API_KEY'):
            parser.error('No API key. Live model trial NOT executed. Use --check for environment status.')
        report = run_live(args.model)
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({'passed': report['passing'], 'total': report['total'], 'output': args.output}, ensure_ascii=False))

        raise SystemExit(0 if report['total'] > 0 and report['passing'] == report['total'] else 1)

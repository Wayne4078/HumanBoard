import json
import unittest
from agent_live_gate_v10 import parse_response, run_live, readiness
from agent_trial import SCENARIOS, baseline


def fake_response(s):
    if baseline(s)['decision'] == 'no_human':
        return {'id': 'test-no-call', 'status':'completed', 'output': [{'type': 'message', 'status':'completed', 'content': [{'type': 'output_text', 'text': json.dumps({'decision':'no_human','reason':'Available data or constraints'})}]}]}
    args = {'title': '현장 검증', 'location': '허가된 공공 접근 장소',
            'scope': '공공장소 관찰', 'evidence_request': '사진과 현장 메모',
            'max_budget_krw': 5000, 'reason': '확정에 현장 확인 필요'}
    return {'id': 'test-call', 'status':'completed', 'output': [{'type': 'function_call', 'status':'completed', 'name': 'request_human_fieldwork', 'arguments': json.dumps(args, ensure_ascii=False)}]}


class LiveGateTest(unittest.TestCase):
    def test_no_tool(self):
        self.assertEqual(parse_response(fake_response(SCENARIOS[0]))['choice'], 'no_human')

    def test_malformed_arguments(self):
        with self.assertRaises(json.JSONDecodeError):
            parse_response({'status':'completed', 'output': [{'type': 'function_call', 'status':'completed', 'name': 'request_human_fieldwork', 'arguments': '{bad'}]})

    def test_multiple_calls_rejected(self):
        call = {'type':'function_call', 'status':'completed','name':'request_human_fieldwork','arguments':'{}'}
        with self.assertRaises(ValueError):
            parse_response({'status':'completed', 'output':[call,call]})

    def test_injected_is_not_live(self):
        index = iter(SCENARIOS)
        def injected(_request):
            return fake_response(next(index))
        result = run_live('fake-model', transport=injected)
        self.assertEqual(result['passing'], len(SCENARIOS))
        self.assertIn('NOT live', result['execution'])
        self.assertEqual(result['actual_tasks_posted'], 0)

    def test_budget_violation(self):
        scenario = SCENARIOS[0]
        def injected(_request):
            return {'status':'completed', 'output':[{'type':'function_call', 'status':'completed','name':'request_human_fieldwork','arguments':json.dumps({'title':'t','location':'loc','scope':'scope','evidence_request':'photo','max_budget_krw':99999,'reason':'reason'})}]}
        result=run_live('fake',injected,[scenario])
        self.assertFalse(result['results'][0]['pass'])

    def test_transport_error_not_simulated(self):
        def broken(_request):
            raise ConnectionError('test offline')
        result=run_live('fake',broken,[SCENARIOS[0]])
        self.assertEqual(result['passing'],0)
        self.assertEqual(result['results'][0]['error_type'],'ConnectionError')

if __name__ == '__main__':
    unittest.main()

"""All model entry points must use sanitized inputs and the same completion contract."""
import json
import unittest
from unittest.mock import patch
from agent_trial import SCENARIOS
import agent_trial
import agent_tool_v08
import agent_live_gate_v10
from model_protocol import parse_tool_response, ResponseError


def no_human():
    return dict(status='completed',output=[dict(type='message',status='completed',content=[
        dict(type='output_text',text=json.dumps(dict(decision='no_human',reason='Authorized data is sufficient')))])])


class ModelProtocol(unittest.TestCase):
    def test_failed_incomplete_queued_refused_and_malformed_never_score(self):
        variants=[dict(status=s,output=[]) for s in ('failed','incomplete','cancelled','queued','in_progress')]
        variants += [dict(output=[]), dict(status='completed',output=[]),
            dict(no_human(),error={'code':'error'}),dict(no_human(),incomplete_details={'reason':'max_output_tokens'}),
            dict(status='completed',output=[None]),
            dict(status='completed',output=[dict(type='function_call',status='completed',name='other',arguments='{}')]),
            dict(status='completed',output=[dict(type='message',status='completed',content=[dict(type='refusal',refusal='no')])])]
        for payload in variants:
            with self.subTest(payload=payload):
                report=agent_live_gate_v10.run_live('fake',lambda _:payload,[SCENARIOS[0]])
                self.assertEqual(report['passing'],0)
                self.assertEqual(report['failed_or_invalid'],1)
                self.assertNotIn('choice',report['results'][0])

    def test_valid_explicit_no_human_has_reason(self):
        result=parse_tool_response(no_human(),agent_tool_v08.TOOL['name'])
        self.assertEqual(result['choice'],'no_human'); self.assertTrue(result['reason'])
        report=agent_live_gate_v10.run_live('fake',lambda _:no_human(),[SCENARIOS[0]])
        self.assertEqual(report['passing'],1); self.assertIn('NOT live',report['execution'])

    def test_tool_not_completed_multiple_unknown_and_text_only_request_rejected(self):
        call=dict(type='function_call',status='completed',name=agent_tool_v08.TOOL['name'],arguments='{}')
        variants=[dict(status='completed',output=[dict(call,status='in_progress')]),
                  dict(status='completed',output=[call,call]),
                  dict(status='completed',output=[dict(call,arguments='[]')]),
                  dict(status='completed',output=[dict(call,arguments=None)])]
        n=no_human(); n['output'][0]['content'][0]['text']=json.dumps(dict(decision='request_human',reason='Need humans'))
        variants.append(n)
        for payload in variants:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError): parse_tool_response(payload,agent_tool_v08.TOOL['name'])

    def test_legacy_live_paths_cannot_leak_labels_or_metadata(self):
        scenario=dict(SCENARIOS[0],secret_expected='extra-label',metadata={'expected':'no_human'})
        seen=[]
        class Response:
            def __enter__(self): return self
            def __exit__(self,*_): pass
            def read(self): return json.dumps(no_human()).encode()
        def transport(request,**_):
            seen.append(json.loads(request.data)); return Response()
        with patch.dict('os.environ',{'OPENAI_API_KEY':'synthetic-not-real'}),patch('urllib.request.urlopen',transport):
            agent_trial.live(scenario,'fake')
            agent_tool_v08.live(scenario,'fake')
        seen.append(agent_live_gate_v10.model_request(scenario,'fake'))
        for request in seen:
            self.assertEqual(set(json.loads(request['input'])),{'mission','facts','budget_krw'})
            self.assertNotIn('online_sufficient',request['input'])
            self.assertNotIn('expected',request['input'])

    def test_label_oracle_cannot_read_expected_anymore(self):
        def oracle(req):
            s=json.loads(req['input']); return {'answer':s['expected']}
        result=agent_live_gate_v10.run_live('label-oracle',oracle)
        self.assertEqual(result['passing'],0)
        self.assertEqual(result['failed_or_invalid'],5)

if __name__=='__main__': unittest.main()

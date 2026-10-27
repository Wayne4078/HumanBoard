"""Security requirements, first run against unchanged V1.0; never exploit-success tests."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import server
from agent_trial import SCENARIOS
from agent_tool_v08 import check_proposal, scripted
from agent_live_gate_v10 import model_request, parse_response, run_live

class RedContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(server, 'DB', Path(self.tmp.name)/'test.sqlite3')
        self.patch.start()
    def tearDown(self):
        self.patch.stop(); self.tmp.cleanup()
    def test_anonymous_creation_is_rejected(self):
        p=dict(agent='ai',mission='m',title='t',location='l',scope='s',evidence_request='photo',budget=5000,human_authorized=True)
        self.assertEqual(server.do('create_task',p)[0],401)
    def test_anonymous_task_list_is_rejected(self):
        self.assertEqual(server.do('list_tasks',{})[0],401)
    def test_anonymous_audit_is_rejected(self):
        self.assertEqual(server.do('audit',{})[0],401)
    def test_model_input_excludes_expected(self):
        self.assertNotIn('expected',json.loads(model_request(SCENARIOS[0],'fake')['input']))
    def test_model_input_excludes_diagnostic_id(self):
        self.assertNotIn('id',json.loads(model_request(SCENARIOS[0],'fake')['input']))
    def test_failed_and_incomplete_responses_never_pass(self):
        for state in ('failed','incomplete'):
            with self.subTest(state=state):
                r=run_live('fake',lambda _:dict(status=state,output=[]),[SCENARIOS[0]])
                self.assertEqual(r['passing'],0)
    def test_empty_completed_output_is_not_valid_no_human(self):
        with self.assertRaises(ValueError): parse_response(dict(status='completed',output=[]))
    def test_unknown_function_is_not_valid_no_human(self):
        with self.assertRaises(ValueError):
            parse_response(dict(status='completed',output=[dict(type='function_call',name='unknown',arguments='{}')]))
    def test_refusal_is_not_valid_no_human(self):
        with self.assertRaises(ValueError):
            parse_response(dict(status='completed',output=[dict(type='message',status='completed',content=[dict(type='refusal',refusal='no')])]))
    def test_renamed_unsafe_scenario_is_blocked(self):
        s=copy.deepcopy(SCENARIOS[4]); s['id']='new_identifier'
        self.assertIsNotNone(check_proposal(s,scripted(SCENARIOS[1])['proposal']))

if __name__=='__main__': unittest.main()

import unittest
from agent_tool_v08 import run, check_proposal, scripted, TOOL
from agent_trial import SCENARIOS

class ToolProtocolTests(unittest.TestCase):
    def test_schema(self):
        self.assertEqual(TOOL['type'], 'function')
        self.assertFalse(TOOL['parameters']['additionalProperties'])
    def test_scripted_cases(self):
        report=run('scripted')
        self.assertEqual(report['passes'],report['total'])
        self.assertEqual(report['posted_tasks'],0)
    def test_invalid_budget(self):
        s=SCENARIOS[1]
        args=dict(scripted(s)['proposal'],max_budget_krw=999999)
        self.assertEqual(check_proposal(s,args),'budget_violation')
    def test_no_unnecessary_work(self):
        self.assertEqual(check_proposal(SCENARIOS[0], scripted(SCENARIOS[1])['proposal']), 'unnecessary_fieldwork')
    def test_no_risky_work(self):
        self.assertEqual(check_proposal(SCENARIOS[4], scripted(SCENARIOS[1])['proposal']), 'safety_violation')
    def test_null_input(self):
        self.assertEqual(check_proposal(SCENARIOS[1],None),'malformed_tool_payload')

if __name__ == '__main__':unittest.main()

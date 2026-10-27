import unittest
from agent_trial import run,SCENARIOS,validate
class AgentTrialTests(unittest.TestCase):
 def test_offline_baseline(self):
  r=run();self.assertEqual(r['pass_count'],5);self.assertEqual(r['total'],5)
 def test_budget_guard(self):
  r={'decision':'request_human','task':{'title':'a','scope':'b','evidence_request':'c','max_budget_krw':99999}}
  self.assertEqual(validate(r,SCENARIOS[1]),'budget_violation')
 def test_safety_guard(self):
  r={'decision':'request_human','task':{'title':'a','scope':'b','evidence_request':'c','max_budget_krw':3000}}
  self.assertEqual(validate(r,SCENARIOS[4]),'safety_violation')
if __name__=='__main__':unittest.main()

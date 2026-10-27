import unittest
from unittest.mock import patch
from agent_customer_v05 import evaluate,safety_gate,ALL
class CustomerTrialTests(unittest.TestCase):
 def test_offline(self):
  r=evaluate();self.assertEqual(r['total'],8);self.assertEqual(r['expected_matches'],8)
 def test_no_auto_publish(self):
  r=evaluate();self.assertFalse(r['posted_to_marketplace']);self.assertTrue(r['approval_required'])
 def test_unsafe_field_access_blocked(self):
  s=next(s for s in ALL if s['id']=='private_access')
  bad={'decision':'request_human','task':{'title':'사유지 촬영','scope':'촬영','evidence_request':'사진','max_budget_krw':3000}}
  self.assertEqual(safety_gate(bad,s),'unsafe_or_unauthorized_access')
 def test_zero_budget_blocked(self):
  s=next(s for s in ALL if s['id']=='no_money')
  bad={'decision':'request_human','task':{'title':'현장','scope':'확인','evidence_request':'사진','max_budget_krw':3000}}
  self.assertIn(safety_gate(bad,s),('budget_violation','no_budget'))
 def test_live_without_key_fails_explicitly(self):
  with patch.dict('os.environ',{'OPENAI_API_KEY':''}):
   with self.assertRaisesRegex(RuntimeError,'OPENAI_API_KEY'):evaluate('live')
if __name__=='__main__':unittest.main()

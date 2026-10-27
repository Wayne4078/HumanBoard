import unittest
from unittest.mock import patch
from agent_ab_v06 import run, SCENARIOS
class ABTest(unittest.TestCase):
 def test_paired(self):
  result=run()
  self.assertEqual(result['count'],len(SCENARIOS)*2)
  self.assertEqual(set(r['condition'] for r in result['records']),{'with_human_board','without_human_board'})
 def test_no_real_work(self):
  r=run();self.assertFalse(r['actual_job_posting']);self.assertFalse(r['actual_payments']);self.assertFalse(r['actual_human_evidence'])
 def test_without_tool_never_requests(self):
  for r in run()['records']:
   if r['condition']=='without_human_board':self.assertEqual(r['decision']['decision'],'no_human')
 def test_live_requires_key(self):
  with patch.dict('os.environ',{'OPENAI_API_KEY':''}):
   with self.assertRaisesRegex(RuntimeError,'OPENAI_API_KEY'):run('live')
if __name__=='__main__':unittest.main()

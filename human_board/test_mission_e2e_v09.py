import unittest
from mission_e2e_v09 import run

class SyntheticE2ETest(unittest.TestCase):
    def test_full_replay_and_guards(self):
        result=run()
        self.assertEqual(len(result['runs']),4)
        self.assertEqual(result['runs'][0]['outcome'],'accepted_simulation')
        self.assertEqual(result['runs'][0]['events'],['created','claimed','submitted','review_accepted'])
        self.assertFalse(result['runs'][0]['mission_feedback']['ground_truth_confirmed'])
        self.assertTrue(all(x['outcome']=='rejected_by_guard' for x in result['runs'][1:]))
        self.assertTrue(result['no_model_calls'])
        self.assertTrue(result['no_payments'])
if __name__=='__main__':unittest.main()

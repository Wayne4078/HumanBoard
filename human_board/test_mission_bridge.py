import os,tempfile,unittest
from pathlib import Path
from agent_trial import SCENARIOS
from mission_bridge import run_scenario
class MissionBridge(unittest.TestCase):
 def test_online_does_not_post(self):
  r=run_scenario(SCENARIOS[0]);self.assertEqual(r['decision'],'no_human');self.assertNotIn('task_id',r)
 def test_physical_returns_evidence(self):
  r=run_scenario(SCENARIOS[1]);self.assertEqual(r['mission_status'],'resumed_with_unverified_field_observation');self.assertIn('evidence',r['feedback_to_mission']);self.assertEqual(r['feedback_to_mission']['human_payment'],'NOT_PAID_SIMULATION')
 def test_unreliable_evidence_blocks_resume(self):
  r=run_scenario(SCENARIOS[2],reviewer_decision='needs_revision');self.assertEqual(r['mission_status'],'waiting_for_reliable_evidence')
 def test_no_budget_and_risk_rejected(self):
  for s in SCENARIOS[3:]:self.assertNotIn('task_id',run_scenario(s))
 def test_approval_required(self):
  r=run_scenario(SCENARIOS[1],approve=False);self.assertEqual(r['mission_status'],'waiting_for_human_approval');self.assertNotIn('task_id',r)
if __name__=='__main__':unittest.main()

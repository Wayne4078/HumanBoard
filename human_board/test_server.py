"""Original flow assertions with V1.1 identities, approvals and artifact contract.
The obsolete human_authorized flag, plaintext worker identity and evidence string
were replaced; successful lifecycle/ownership/payment assertions are retained.
"""
import unittest
from simulation import Sandbox

class Flows(unittest.TestCase):
    def test_full_flow_and_guards(self):
        with Sandbox() as b:
            self.assertEqual(b.mission()[0],201)
            p=b.draft()
            self.assertEqual(b.call('create_task',dict(proposal=p,idempotency_key='flow',approval_id='missing'))[0],403)
            status,r=b.order(p); self.assertEqual(status,201); tid=r['task_id']
            self.assertEqual(b.call('claim_task',dict(task_id=tid),'worker')[0],200)
            self.assertIn(b.call('claim_task',dict(task_id=tid),'worker2')[0],(404,409))
            self.assertIn(b.call('submit_evidence',dict(task_id=tid,evidence=b.evidence()),'worker2')[0],(403,404))
            self.assertEqual(b.call('submit_evidence',dict(task_id=tid,evidence=b.evidence()),'worker')[0],200)
            self.assertEqual(b.review(tid,'needs_revision')[0],200)
            self.assertEqual(b.call('submit_evidence',dict(task_id=tid,evidence=b.evidence('SYNTHETIC 추가 관찰 설명; 실현장 아님.')),'worker')[0],200)
            status,r=b.review(tid); self.assertEqual(status,200,r)
            self.assertEqual(r['payment'],'SIMULATED_NOT_PAID')
            self.assertEqual(b.call('get_task_status',dict(task_id=tid))[1]['status'],'accepted')
            self.assertGreater(len(b.call('audit',{},'admin')[1]['events']),1)

if __name__=='__main__': unittest.main()

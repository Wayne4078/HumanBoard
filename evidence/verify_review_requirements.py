"""Same secure expectations against V1.0 and V1.1, with setup-only API adapters.
Use HB_REVIEW_SOURCE to point to an extracted original archive. No external I/O.
Legacy adapters reproduce authorized setup, never change the security assertions.
"""
import contextlib
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

SOURCE=Path(os.environ.get('HB_REVIEW_SOURCE',Path(__file__).resolve().parents[1]/'human_board'))
sys.path.insert(0,str(SOURCE))
import server
from agent_trial import SCENARIOS
from agent_live_gate_v10 import model_request, run_live
from agent_tool_v08 import check_proposal, scripted
MODERN=hasattr(server,'proposal')


class ReviewRequirements(unittest.TestCase):
    def setUp(self):
        if MODERN:
            from simulation import Sandbox
            self.box=Sandbox(); self.box.mission()
        else:
            self.temp=tempfile.TemporaryDirectory()
            self.old_db=server.DB; server.DB=Path(self.temp.name)/'old.sqlite3'
    def tearDown(self):
        if MODERN: self.box.close()
        else: server.DB=self.old_db; self.temp.cleanup()
    def draft(self,budget=5000,**kw):
        if MODERN: return self.box.draft(budget=budget,**kw)
        return dict(agent='ai',mission='m',title='Observe public sign',location='Public place',
                    scope='Observe sign',evidence_request='Observation record',budget=budget,human_authorized=True,**kw)
    def order(self,p=None,key=None):
        p=p or self.draft()
        if MODERN: return self.box.order(p,key)
        if key: p={**p,'idempotency_key':key}
        return server.do('create_task',p)
    def create(self,p=None):
        code,r=self.order(p); self.assertEqual(code,201,r); return r['task_id']
    def call(self,action,p,who='ai'):
        return self.box.call(action,p,who) if MODERN else server.do(action,p)
    def submit(self,tid=None,body='Original observation record'):
        tid=tid or self.create()
        self.assertEqual(self.call('claim_task',dict(task_id=tid,worker='worker'),'worker')[0],200)
        evidence=self.box.evidence(body) if MODERN else body
        self.assertEqual(self.call('submit_evidence',dict(task_id=tid,worker='worker',evidence=evidence),'worker')[0],200)
        return tid
    def review(self,tid,decision='accepted',who='reviewer'):
        if MODERN: return self.box.review(tid,decision,who)
        return self.call('review_task',dict(task_id=tid,reviewer=who,decision=decision,reason='Manual synthetic check'),who)

    def test_F01_anonymous_create_forbidden(self):
        p=self.draft()
        if MODERN: p=dict(proposal=p,idempotency_key='anonymous',approval_id='forged')
        self.assertEqual(server.do('create_task',p)[0],401)

    def test_F02_concurrent_budget_never_exceeds_cap(self):
        for _ in range(4): self.create(self.draft(20000))
        gate=threading.Barrier(2)
        if MODERN:
            def send(_): gate.wait(timeout=5); return self.order(self.draft(20000))[0]
            with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(send,range(2)))
            from storage import connect
            c=connect(self.box.db)
        else:
            original_conn=server.conn
            class Cursor:
                def __init__(self,c): self.c=c
                def fetchone(self):
                    row=self.c.fetchone(); gate.wait(timeout=5); return row
            class Connection:
                def __init__(self): self.c=original_conn()
                def execute(self,sql,*args):
                    cur=self.c.execute(sql,*args)
                    return Cursor(cur) if 'SUM(budget)' in sql else cur
                def __getattr__(self,k): return getattr(self.c,k)
            with patch.object(server,'conn',Connection):
                with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(lambda _:self.order(self.draft(20000)),range(2)))
            c=original_conn()
        with contextlib.closing(c): total=c.execute('SELECT SUM(budget) FROM tasks').fetchone()[0]
        self.assertLessEqual(total,server.CAP)

    def test_F03_identical_retry_creates_one_task(self):
        p=self.draft()
        if MODERN:
            code,a=self.box.call('approve_task',dict(proposal=p,agent='ai'),'admin'); self.assertEqual(code,201)
            payload=dict(proposal=p,approval_id=a['approval_id'],idempotency_key='same-order')
            a=self.call('create_task',payload)[1]; b=self.call('create_task',payload)[1]
        else:
            a=self.order(p,'same-order')[1]; b=self.order(p,'same-order')[1]
        self.assertEqual(a['task_id'],b['task_id'])

    def test_F03_zero_mission_allocation_cannot_reserve(self):
        if MODERN:
            self.box.mission('zero',budget=0); p=self.box.draft(mission='zero')
        else:
            p=self.draft(); p.update(mission='zero',budget_krw=0)
        self.assertEqual(self.order(p)[0],409)

    def test_F04_renamed_unsafe_case_blocked(self):
        s=copy.deepcopy(SCENARIOS[4]); s['id']='unseen-unsafe'
        self.assertIsNotNone(check_proposal(s,scripted(SCENARIOS[1])['proposal']))

    def test_F05_expected_and_id_absent_from_model_input(self):
        p=json.loads(model_request(SCENARIOS[0],'fake')['input'])
        self.assertNotIn('expected',p); self.assertNotIn('id',p)

    def test_F06_failed_response_cannot_score_no_human(self):
        for status in ('failed','incomplete'):
            with self.subTest(status=status):
                r=run_live('fake',lambda _:dict(status=status,output=[]),[SCENARIOS[0]])
                self.assertEqual(r['passing'],0)

    def test_F07_worker_cannot_approve_own_submission(self):
        tid=self.submit()
        code,_=self.call('review_task',dict(task_id=tid,reviewer='worker',decision='accepted'),'worker')
        self.assertEqual(code,403)

    def test_F08_original_evidence_retrievable_after_revision(self):
        tid=self.submit(); self.assertEqual(self.review(tid,'needs_revision')[0],200)
        ev=self.box.evidence('Replacement observation record') if MODERN else 'Replacement observation record'
        self.assertEqual(self.call('submit_evidence',dict(task_id=tid,worker='worker',evidence=ev),'worker')[0],200)
        if MODERN:
            code,r=self.call('get_evidence',dict(task_id=tid,version=1),'reviewer')
            self.assertEqual(code,200)
            observed=r['evidence']['observation']
        else:
            observed=self.call('get_task_status',dict(task_id=tid))[1]['evidence']
        self.assertEqual(observed,'Original observation record')

    def test_F09_nulls_and_fractional_money_rejected(self):
        p=self.draft()
        for k in ('title','location','scope','evidence_request'): p[k]=None
        p['budget']=1000.99
        self.assertEqual(self.order(p)[0],400)

    def test_F09_invalid_worker_returns_controlled_4xx(self):
        tid=self.create()
        try: code,_=self.call('claim_task',dict(task_id=tid,worker={'id':'worker'}),'worker')
        except Exception as exc: self.fail('Uncontrolled error: '+type(exc).__name__)
        self.assertTrue(400 <= code < 500)

    def test_F10_dispute_can_be_reopened_by_admin(self):
        tid=self.submit(); self.assertEqual(self.review(tid,'disputed')[0],200)
        code,r=self.call('resolve_dispute',dict(task_id=tid,decision='needs_revision',reason='Reopen for new record'),'admin')
        self.assertEqual(code,200,r)

    def test_F11_cli_failure_has_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/'result.json'
            wrapper='''import runpy,sys
from unittest.mock import patch
sys.path.insert(0,sys.argv[1]); output=sys.argv[2]
sys.argv=['agent_live_gate_v10.py','--output',output]
with patch.dict('os.environ',{'OPENAI_API_KEY':'synthetic-not-real'}),patch('urllib.request.urlopen',side_effect=ConnectionError('synthetic outage')):
 runpy.run_module('agent_live_gate_v10',run_name='__main__')
'''
            p=subprocess.run([sys.executable,'-B','-c',wrapper,str(SOURCE),str(output)],capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0)
            self.assertEqual(json.loads(output.read_text())['passing'],0)

if __name__=='__main__': unittest.main(verbosity=2)

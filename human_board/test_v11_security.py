"""V1.1 security/concurrency HTTP integration tests. Synthetic data, no model calls."""
import base64
import copy
import http.client
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import server
from storage import connect, initialize, provision
from simulation import Sandbox


class Security(unittest.TestCase):
    def setUp(self):
        self.b = Sandbox()
        self.assertEqual(self.b.mission()[0],201)
        self.other = provision(self.b.db,'other',100000,{'other-ai':'ai_customer','other-admin':'admin','other-worker':'worker'})
        self.http = server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.http.db = self.b.db
        self.thread = threading.Thread(target=self.http.serve_forever,kwargs={'poll_interval':0.01},daemon=True)
        self.thread.start()
    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(); self.b.close()
    def req(self, action, p=None, who='ai', raw=None, headers=None):
        token = self.b.tokens.get(who,self.other.get(who)) if who else None
        h = {'Content-Type':'application/json'}
        if token: h['Authorization']='Bearer '+token
        if headers: h.update(headers)
        c = http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=8)
        try:
            data = raw if raw is not None else (json.dumps(p) if p is not None else None)
            c.request('POST' if p is not None or raw is not None else 'GET','/api/'+action,data,h)
            r=c.getresponse(); return r.status,json.loads(r.read())
        finally: c.close()
    def approval(self, draft=None, **kw):
        draft = draft or self.b.draft()
        status,r=self.req('approve_task',dict(proposal=draft,agent='ai',**kw),'admin')
        self.assertEqual(status,201,r)
        return dict(proposal=draft,approval_id=r['approval_id'],idempotency_key='key-'+r['approval_id'])
    def create(self,draft=None):
        code,r=self.req('create_task',self.approval(draft))
        self.assertEqual(code,201,r); return r['task_id']
    def submit(self,tid=None):
        tid=tid or self.create()
        self.assertEqual(self.req('claim_task',dict(task_id=tid),'worker')[0],200)
        code,r=self.req('submit_evidence',dict(task_id=tid,evidence=self.b.evidence()),'worker')
        self.assertEqual(code,200,r); return tid
    def review_body(self,tid,who='reviewer'):
        code,ev=self.req('tasks/'+tid+'/evidence',who=who); self.assertEqual(code,200,ev)
        sha=ev['evidence']['artifacts'][0]['sha256']
        return dict(task_id=tid,decision='accepted',reason='Manually checked synthetic record, no field truth claim',
                    inspection_receipt=ev['inspection_receipt'],
                    checks={c:dict(passed=True,note='Inspected artifact for criterion',artifact_sha256=sha) for c in self.b.draft()['criteria']})
    def ledger(self,scope='global'):
        c=connect(self.b.db)
        try: return dict(c.execute('SELECT * FROM budgets WHERE scope=?',(scope,)).fetchone())
        finally: c.close()

    def test_F01_anonymous_all_api_operations_rejected(self):
        tid=self.create()
        for path in ('tasks','tasks/'+tid,'audit','tasks/'+tid+'/evidence','budgets'):
            with self.subTest(path=path): self.assertEqual(self.req(path,who=None)[0],401)
        for action in ('create_task','approve_task','register_mission','claim_task','submit_evidence','review_task','cancel_task','resolve_dispute'):
            with self.subTest(action=action): self.assertEqual(self.req(action,{},None)[0],401)

    def test_F01_cross_org_read_write_and_audit_isolated(self):
        tid=self.create()
        self.assertEqual(self.req('tasks/'+tid,who='other-admin')[0],404)
        self.assertEqual(self.req('tasks',who='other-admin')[1]['tasks'],[])
        self.assertEqual(self.req('claim_task',dict(task_id=tid),'other-worker')[0],404)
        self.assertEqual(self.req('cancel_task',dict(task_id=tid,reason='attack'),'other-admin')[0],404)
        self.assertEqual(self.req('audit',who='other-admin')[1]['events'],[])
        self.assertEqual(self.req('audit?task_id='+tid,who='other-admin')[0],404)

    def test_F01_worker_impersonation_and_role_separation(self):
        tid=self.create()
        self.assertEqual(self.req('claim_task',dict(task_id=tid,worker='worker2'),'worker')[0],403)
        self.assertEqual(self.req('claim_task',dict(task_id=tid),'ai')[0],403)
        self.assertEqual(self.req('approve_task',dict(proposal=self.b.draft(),agent='ai'),'ai')[0],403)
        self.assertEqual(self.req('create_task',self.approval(),'worker')[0],403)
        self.assertEqual(self.req('audit',who='worker')[0],403)
        self.assertEqual(self.req('claim_task',dict(task_id=tid),'worker')[0],200)
        self.assertEqual(self.req('submit_evidence',dict(task_id=tid,worker='worker',evidence=self.b.evidence()),'worker2')[0],404)

    def test_F01_approval_binds_amount_scope_agent_and_expiry(self):
        original=self.approval()
        for field,value in [('budget',6000),('scope','Different work'),('title','Changed title'),('criteria',['different'])]:
            p=copy.deepcopy(original); p['proposal'][field]=value
            self.assertEqual(self.req('create_task',p)[0],403)
        with patch('server.time.time',return_value=0):
            # Existing approval should not be considered expired in the past.
            self.assertEqual(self.req('create_task',original)[0],201)
        self.assertEqual(self.req('create_task',{**original,'idempotency_key':'reuse'})[0],403)
        p=self.approval()
        c=connect(self.b.db); c.execute('UPDATE approvals SET expires=0 WHERE id=?',(p['approval_id'],)); c.close()
        self.assertEqual(self.req('create_task',p)[0],403)
        self.assertEqual(self.ledger()['reserved'],5000)

    def test_F01_revoked_token_and_caller_actor_cannot_override_identity(self):
        tid=self.create()
        c=connect(self.b.db); c.execute("UPDATE principals SET active=0 WHERE id='worker'"); c.close()
        self.assertEqual(self.req('claim_task',dict(task_id=tid),'worker')[0],401)
        events=self.req('audit',who='admin')[1]['events']
        self.assertEqual([e['actor'] for e in events if e['action']=='created'],['ai'])

    def test_F01_same_org_ai_object_permissions_and_approval_subject_binding(self):
        tid=self.create()
        self.assertEqual(self.req('tasks',who='ai2')[1]['tasks'],[])
        self.assertEqual(self.req('tasks/'+tid,who='ai2')[0],404)
        p=self.approval()
        self.assertEqual(self.req('create_task',p,'ai2')[0],403)
        self.assertEqual(self.req('create_task',p)[0],201)

    def test_F02_concurrent_global_reservations_are_atomic(self):
        for _ in range(4): self.create(self.b.draft(budget=20000))
        orders=[self.approval(self.b.draft(budget=20000)) for _ in range(8)]
        gate=threading.Barrier(len(orders))
        def send(p): gate.wait(timeout=5); return self.req('create_task',p)[0]
        with ThreadPoolExecutor(max_workers=8) as pool: codes=list(pool.map(send,orders))
        self.assertEqual(codes.count(201),1,codes)
        self.assertEqual(codes.count(409),7,codes)
        self.assertEqual(self.ledger()['reserved'],100000)
        self.assertEqual(len(self.req('tasks')[1]['tasks']),5)

    def test_F02_global_budget_shared_across_organizations(self):
        for _ in range(4): self.create(self.b.draft(budget=20000))
        other_draft=self.b.draft(budget=20000)
        self.assertEqual(self.req('register_mission',dict(mission='m',budget=100000,location='SIMULATED_PUBLIC_AREA',fieldwork_required=True,authorization_reference='other synthetic authorization'),'other-admin')[0],201)
        code,approved=self.req('approve_task',dict(proposal=other_draft,agent='other-ai'),'other-admin')
        self.assertEqual(code,201)
        other_order=dict(proposal=other_draft,approval_id=approved['approval_id'],idempotency_key='other-order')
        orders=[(self.approval(self.b.draft(budget=20000)),'ai'),(other_order,'other-ai')]
        gate=threading.Barrier(2)
        def send(item):
            gate.wait(timeout=5); return self.req('create_task',item[0],item[1])[0]
        with ThreadPoolExecutor(max_workers=2) as pool: codes=list(pool.map(send,orders))
        self.assertEqual(sorted(codes),[201,409])
        self.assertEqual(self.ledger()['reserved'],100000)
        self.assertEqual(self.ledger('org:synthetic')['reserved']+self.ledger('org:other')['reserved'],100000)

    def test_F02_transaction_failure_rolls_back_approval_and_all_ledgers(self):
        p=self.approval()
        original=server.log
        def fail_on_create(c,actor,action,*args,**kwargs):
            if action=='created': raise sqlite3.IntegrityError('synthetic audit failure')
            return original(c,actor,action,*args,**kwargs)
        with patch('server.log',fail_on_create): self.assertEqual(self.req('create_task',p)[0],409)
        self.assertEqual(self.ledger()['reserved'],0)
        self.assertEqual(self.req('tasks')[1]['tasks'],[])
        self.assertEqual(self.req('create_task',p)[0],201)

    def test_F03_concurrent_same_key_posts_once(self):
        p=self.approval()
        gate=threading.Barrier(6)
        def send(_): gate.wait(timeout=5); return self.req('create_task',p)
        with ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(send,range(6)))
        self.assertEqual(sum(code==201 for code,_ in results),1,results)
        self.assertTrue(all(code in (200,201) for code,_ in results))
        self.assertEqual(len({body['task_id'] for _,body in results}),1)
        self.assertEqual(self.ledger()['reserved'],5000)
        p['proposal']['budget']=6000
        self.assertEqual(self.req('create_task',p)[0],409)

    def test_F03_org_and_mission_caps_and_rollback(self):
        c=connect(self.b.db); c.execute("UPDATE budgets SET limit_krw=6000 WHERE scope='org:synthetic'"); c.close()
        self.create()
        self.assertEqual(self.req('create_task',self.approval())[0],409)
        self.assertEqual(self.ledger()['reserved'],5000)
        self.assertEqual(self.req('register_mission',dict(mission='zero',budget=0,location='SIMULATED_PUBLIC_AREA',fieldwork_required=True,authorization_reference='zero allocation'),'admin')[0],201)
        self.assertEqual(self.req('create_task',self.approval(self.b.draft(mission='zero')))[0],409)
        self.assertEqual(self.ledger()['reserved'],5000)
        self.assertEqual(self.req('approve_task',dict(proposal=self.b.draft(mission='unknown'),agent='ai'),'admin')[0],403)

    def test_F03_mission_limit_independent_of_org_limit(self):
        self.assertEqual(self.b.mission('limited',budget=6000)[0],201)
        self.create(self.b.draft(mission='limited'))
        self.assertEqual(self.req('create_task',self.approval(self.b.draft(mission='limited')))[0],409)
        self.assertEqual(self.ledger()['reserved'],5000)
        self.create()  # A separate authorized mission can still use org capacity.
        self.assertEqual(self.ledger()['reserved'],10000)

    def test_F03_budget_query_uses_canonical_unicode_mission_scopes(self):
        self.assertEqual(self.b.mission('관광 임무')[0],201)
        self.create(self.b.draft(mission='관광 임무'))
        code,r=self.req('budgets',who='admin'); self.assertEqual(code,200,r)
        self.assertEqual(len(r['budgets']),3)
        self.assertEqual(sum(x['reserved'] for x in r['budgets']),10000)

    def test_F03_lock_contention_controlled_retry(self):
        p=self.approval()
        # Exercise real SQLite lock timeout without stalling the suite for five seconds.
        c=connect(self.b.db); c.execute('BEGIN IMMEDIATE')
        original=server.connect
        def short_timeout(path):
            result=original(path); result.execute('PRAGMA busy_timeout=10'); return result
        try:
            with patch('server.connect',short_timeout): self.assertEqual(self.req('create_task',p)[0],503)
        finally: c.rollback(); c.close()
        self.assertEqual(self.req('create_task',p)[0],201)
        self.assertEqual(self.ledger()['reserved'],5000)

    def test_F04_risky_content_flags_and_unnecessary_missions_fail_closed(self):
        for update in [dict(scope='Enter unauthorized private facility'),dict(title='위험 시설 구조적 안전 평가')]:
            self.assertEqual(self.req('approve_task',dict(proposal=self.b.draft(**update),agent='ai'),'admin')[0],403)
        for key,value in [('access','unknown'),('hazardous',True),('expertise_required',True),('personal_data',True),('remote_alternative_checked',False)]:
            p=self.b.draft(); p['policy'][key]=value
            self.assertEqual(self.req('approve_task',dict(proposal=p,agent='ai'),'admin')[0],403)
        p=self.b.draft(); del p['policy']['access_reference']
        self.assertEqual(self.req('approve_task',dict(proposal=p,agent='ai'),'admin')[0],400)
        self.assertEqual(self.b.mission('remote',required=False)[0],201)
        self.assertEqual(self.req('approve_task',dict(proposal=self.b.draft(mission='remote'),agent='ai'),'admin')[0],403)
        self.assertEqual(self.req('approve_task',dict(proposal=self.b.draft(location='Other place'),agent='ai'),'admin')[0],403)

    def test_F07_no_self_review_no_uninspected_or_unjustified_acceptance(self):
        tid=self.submit()
        basic=dict(task_id=tid,decision='accepted',reason='attempt',checks={})
        self.assertEqual(self.req('review_task',basic,'worker')[0],403)
        self.assertEqual(self.req('review_task',basic,'admin')[0],403)
        self.assertEqual(self.req('review_task',basic,'ai')[0],403)
        self.assertEqual(self.req('review_task',basic,'reviewer')[0],400)
        body=self.review_body(tid)
        for update in [dict(reason=''),dict(checks={}),dict(inspection_receipt='forged')]:
            self.assertIn(self.req('review_task',{**body,**update},'reviewer')[0],(400,409))
        other=copy.deepcopy(body); other['checks'][next(iter(other['checks']))]['artifact_sha256']='fake'
        self.assertEqual(self.req('review_task',other,'reviewer')[0],400)
        code,r=self.req('review_task',body,'reviewer')
        self.assertEqual(code,200,r); self.assertEqual(r['review_method'],'MANUAL_REVIEW')
        self.assertFalse(r['ground_truth_confirmed']); self.assertEqual(r['payment'],'SIMULATED_NOT_PAID')
        self.assertEqual(self.ledger()['reserved'],0); self.assertEqual(self.ledger()['committed'],5000)
        self.assertEqual(self.req('review_task',body,'reviewer')[0],409)
        self.assertEqual(self.req('cancel_task',dict(task_id=tid,reason='release accepted'),'admin')[0],409)

    def test_F07_evidence_requires_artifact_time_and_location(self):
        tid=self.create(); self.req('claim_task',dict(task_id=tid),'worker')
        for evidence in ['x',None,{},dict(self.b.evidence(),artifacts=[]),dict(self.b.evidence(),observed_at='unknown'),dict(self.b.evidence(),location='other')]:
            self.assertEqual(self.req('submit_evidence',dict(task_id=tid,evidence=evidence),'worker')[0],400)
        ev=self.b.evidence(); ev['artifacts'][0]['content_base64']='not base64'
        self.assertEqual(self.req('submit_evidence',dict(task_id=tid,evidence=ev),'worker')[0],400)
        ev=self.b.evidence(); ev['artifacts'][0]['media_type']='image/png'
        self.assertEqual(self.req('submit_evidence',dict(task_id=tid,evidence=ev),'worker')[0],400)
        self.assertEqual(self.req('submit_evidence',dict(task_id=tid,evidence=self.b.evidence()),'worker')[0],200)

    def test_F08_versions_preserved_and_stale_or_foreign_inspection_rejected(self):
        tid=self.submit()
        original=self.req('tasks/'+tid+'/evidence?version=1',who='reviewer')[1]
        body=self.review_body(tid)
        self.assertEqual(self.req('review_task',body,'reviewer2')[0],409)
        rev=dict(body,decision='needs_revision',checks={})
        self.assertEqual(self.req('review_task',rev,'reviewer')[0],200)
        self.assertEqual(self.req('submit_evidence',dict(task_id=tid,evidence=self.b.evidence('SYNTHETIC replacement observation, not field truth.')),'worker')[0],200)
        self.assertEqual(self.req('review_task',body,'reviewer')[0],409)
        old=self.req('tasks/'+tid+'/evidence?version=1',who='reviewer')[1]
        new=self.req('tasks/'+tid+'/evidence?version=2',who='reviewer')[1]
        self.assertEqual(old['evidence'],original['evidence']); self.assertEqual(old['sha256'],original['sha256'])
        self.assertNotEqual(old['sha256'],new['sha256'])
        body['inspection_receipt']=old['inspection_receipt']
        self.assertEqual(self.req('review_task',body,'reviewer')[0],409)
        self.assertEqual(self.req('review_task',self.review_body(tid),'reviewer')[0],200)
        events=self.req('audit?task_id='+tid,who='admin')[1]['events']
        versions=[json.loads(e['detail'])['version'] for e in events if e['action']=='submitted']
        self.assertEqual(versions,[1,2])

    def test_F08_audit_pagination_no_history_truncation(self):
        for _ in range(3): self.create()
        all_events=self.req('audit',who='admin')[1]['events']
        after=0; seen=[]
        for _ in range(20):
            page=self.req('audit?limit=2&after='+str(after),who='admin')[1]
            if not page['events']: break
            seen.extend(page['events']); after=page['next_after']
        self.assertEqual(seen,all_events)

    def test_F09_strict_string_and_integer_types(self):
        for field in ('mission','title','location','scope','evidence_request'):
            for invalid in (None,{},[],True,' '):
                p=self.b.draft(**{field:invalid})
                self.assertEqual(self.req('approve_task',dict(proposal=p,agent='ai'),'admin')[0],400,(field,invalid))
        for invalid in (True,False,1000.99,'5000',None,-1,20001):
            self.assertEqual(self.req('approve_task',dict(proposal=self.b.draft(budget=invalid),agent='ai'),'admin')[0],400)
        tid=self.create()
        self.assertEqual(self.req('claim_task',dict(task_id=tid,worker={'id':'worker'}),'worker')[0],403)
        self.assertEqual(self.req('tasks')[0],200)

    def test_F09_malformed_http_is_controlled(self):
        for raw in ('null','[]','{bad','{"x":1,"x":2}','{"x":NaN}'):
            self.assertEqual(self.req('create_task',raw=raw)[0],400)
        self.assertEqual(self.req('create_task',raw='{}',headers={'Content-Length':'-1'})[0],400)
        self.assertEqual(self.req('create_task',raw='x'*70000)[0],413)
        self.assertEqual(self.req('create_task',raw='{}',headers={'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.req('tasks')[0],200)

    def test_F10_dispute_reopen_resubmit_review_and_cancel(self):
        tid=self.submit(); body=self.review_body(tid)
        self.assertEqual(self.req('review_task',dict(body,decision='disputed',checks={}), 'reviewer')[0],200)
        self.assertEqual(self.ledger()['reserved'],5000)
        self.assertEqual(self.req('resolve_dispute',dict(task_id=tid,decision='accepted',reason='bypass'),'admin')[0],400)
        self.assertEqual(self.req('resolve_dispute',dict(task_id=tid,decision='needs_revision',reason='Reopen with new record'),'worker')[0],403)
        self.assertEqual(self.req('resolve_dispute',dict(task_id=tid,decision='needs_revision',reason='Reopen with new record'),'admin')[0],200)
        self.assertEqual(self.req('submit_evidence',dict(task_id=tid,evidence=self.b.evidence()),'worker')[0],200)
        self.assertEqual(self.req('review_task',self.review_body(tid),'reviewer')[0],200)
        tid2=self.submit(); body=self.review_body(tid2)
        self.req('review_task',dict(body,decision='disputed',checks={}), 'reviewer')
        self.assertEqual(self.req('resolve_dispute',dict(task_id=tid2,decision='cancelled',reason='Cancel synthetic work'),'admin')[0],200)
        self.assertEqual(self.ledger()['reserved'],0); self.assertEqual(self.ledger()['committed'],5000)

    def test_F10_cancel_releases_once_and_retry_never_recreates(self):
        p=self.approval(); tid=self.req('create_task',p)[1]['task_id']
        self.assertEqual(self.req('cancel_task',dict(task_id=tid,reason='Synthetic cancellation'),'admin')[0],200)
        self.assertEqual(self.req('cancel_task',dict(task_id=tid,reason='duplicate'),'admin')[0],409)
        code,r=self.req('create_task',p); self.assertEqual(code,200); self.assertEqual(r['status'],'cancelled')
        self.assertEqual(self.ledger()['reserved'],0)


class RuntimeContracts(unittest.TestCase):
    def test_legacy_database_not_silently_migrated(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'legacy.db'; c=sqlite3.connect(path)
            c.execute('CREATE TABLE tasks(id TEXT)'); c.commit(); c.close()
            before=path.read_bytes()
            with self.assertRaisesRegex(RuntimeError,'Legacy'): initialize(path)
            self.assertEqual(path.read_bytes(),before)

    def test_F11_cli_nonzero_when_all_requests_fail_and_report_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/'report.json'
            wrapper='''import runpy,sys
from unittest.mock import patch
sys.argv=['agent_live_gate_v10.py','--output',sys.argv[1]]
with patch.dict('os.environ',{'OPENAI_API_KEY':'synthetic-not-a-real-credential'}), patch('urllib.request.urlopen',side_effect=ConnectionError('synthetic outage')):
 runpy.run_module('agent_live_gate_v10',run_name='__main__')
'''
            p=subprocess.run([sys.executable,'-B','-c',wrapper,str(output)],cwd=Path(__file__).parent,capture_output=True,text=True)
            self.assertEqual(p.returncode,1,p.stderr)
            r=json.loads(output.read_text()); self.assertEqual(r['passing'],0); self.assertEqual(r['total'],5)
            self.assertTrue(all(x['error_type']=='ConnectionError' for x in r['results']))

if __name__=='__main__': unittest.main()

"""Review-only exploit reproductions. PASS means the described defect reproduced.
No external network, model calls, payments, or product source modifications.
"""
import contextlib
import copy
import http.client
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'human_board'
sys.path.insert(0, str(SOURCE))
import server
from agent_trial import SCENARIOS
from agent_tool_v08 import check_proposal, scripted
from agent_live_gate_v10 import model_request, run_live

class QuietHandler(server.Handler):
    def log_message(self, *_): pass
class QuietHTTPServer(server.ThreadingHTTPServer):
    def handle_error(self, *_): pass

class Reproductions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = server.DB
        server.DB = Path(self.tmp.name) / 'review.sqlite3'
        self.http = QuietHTTPServer(('127.0.0.1', 0), QuietHandler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join()
        server.DB = self.old_db
        self.tmp.cleanup()
    def request(self, action, payload=None):
        c = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        try:
            c.request('GET' if payload is None else 'POST', '/api/' + action,
                      body=None if payload is None else json.dumps(payload),
                      headers={} if payload is None else {'Content-Type':'application/json'})
            r = c.getresponse()
            return r.status, json.loads(r.read())
        finally: c.close()
    def payload(self, **kw):
        return dict(agent='agency-A', mission='mission-A', title='Inspect public sign',
                    location='Public place', scope='Observe sign', evidence_request='Dated photo',
                    budget=5000, human_authorized=True, **kw)
    def create(self, payload=None):
        status, body = self.request('create_task', payload or self.payload())
        self.assertEqual(status, 201, body)
        return body['task_id']
    def submitted(self):
        tid = self.create()
        self.assertEqual(self.request('claim_task', {'task_id':tid,'worker':'worker-A'})[0],200)
        self.assertEqual(self.request('submit_evidence', {'task_id':tid,'worker':'worker-A','evidence':'x'})[0],200)
        return tid

    def test_01_anonymous_can_create_impersonate_and_read_all(self):
        tid = self.create() # No Authorization/cookie/approval token supplied.
        self.assertEqual(self.request('claim_task',{'task_id':tid,'worker':'victim'})[0],200)
        self.assertEqual(self.request('submit_evidence',{'task_id':tid,'worker':'victim','evidence':'forged observation'})[0],200)
        status, detail = self.request('tasks/'+tid)
        self.assertEqual(status,200); self.assertEqual(detail['evidence'],'forged observation')
        self.assertEqual(self.request('audit')[0],200)
        print('E01: anonymous create/worker impersonation/detail/audit access all succeeded')

    def test_02_worker_can_self_accept_meaningless_evidence(self):
        tid = self.submitted()
        status, review = self.request('review_task',{'task_id':tid,'reviewer':'worker-A','decision':'accepted'})
        self.assertEqual(status,200)
        self.assertEqual(self.request('tasks/'+tid)[1]['status'],'accepted')
        self.assertEqual(review['payment'],'SIMULATED_NOT_PAID')
        print('E02: evidence="x", no reason, same worker/reviewer -> accepted (NO actual payment)')

    def test_03_concurrent_creates_exceed_global_cap(self):
        for _ in range(4):
            p=self.payload(); p['budget']=20000; self.create(p)
        barrier=threading.Barrier(2)
        original_conn=server.conn
        class Cursor:
            def __init__(self,cursor): self.cursor=cursor
            def fetchone(self):
                row=self.cursor.fetchone()
                barrier.wait(timeout=5) # Both real SUM reads finish before either INSERT.
                return row
        class Connection:
            def __init__(self): self.real=original_conn()
            def execute(self,sql,*args):
                cursor=self.real.execute(sql,*args)
                return Cursor(cursor) if 'SUM(budget)' in sql else cursor
            def __getattr__(self,k): return getattr(self.real,k)
        def create(_):
            p=self.payload(); p['budget']=20000
            return server.do('create_task',p)[0]
        with patch.object(server,'conn',Connection):
            with ThreadPoolExecutor(max_workers=2) as pool: codes=list(pool.map(create,range(2)))
        with contextlib.closing(original_conn()) as c:
            total=c.execute('SELECT SUM(budget) FROM tasks').fetchone()[0]
        self.assertEqual(codes,[201,201]); self.assertEqual(total,120000)
        print('E03: deterministic interleaving after SUM; approvals=',codes,'reserved=',total,'cap=',server.CAP)

    def test_04_retry_posts_duplicate_and_reserves_twice(self):
        p=self.payload(); p['idempotency_key']='one-logical-order'
        a=self.create(p); b=self.create(p)
        self.assertNotEqual(a,b)
        tasks=self.request('tasks')[1]['tasks']
        self.assertEqual(sum(t['budget'] for t in tasks),10000)
        print('E04: identical retry/idempotency key -> two tasks, 10000 reserved for 5000 order')

    def test_05_no_server_mission_budget_binding(self):
        # The known fixture's budget is zero. API never looks up a mission authority/budget.
        p=self.payload(); p['mission']='no_money'; p['budget']=20000; p['budget_krw']=0
        tid=self.create(p)
        self.assertEqual(self.request('tasks/'+tid)[1]['budget'],20000)
        print('E05: mission=no_money with declared budget_krw=0 -> 20000 task created; no mission ledger')

    def test_06_new_unsafe_case_bypasses_guard_and_server(self):
        s=copy.deepcopy(SCENARIOS[4]); s['id']='unseen_unsafe_case'
        args=copy.deepcopy(scripted(SCENARIOS[1])['proposal'])
        args.update(title='Dangerous facility inspection', scope='Enter unauthorized private facility',location='Unsafe private facility')
        self.assertIsNone(check_proposal(s,args))
        p=self.payload(); p.update(title=args['title'],scope=args['scope'],location=args['location'])
        self.create(p)
        print('E06: same high-risk facts, different id -> guard passes; dangerous task also accepted over HTTP')

    def test_07_expected_labels_are_sent_to_model(self):
        observed=[]
        def oracle(req):
            s=json.loads(req['input']); observed.append(s['expected'])
            if s['expected']=='no_human': return {'status':'completed','output':[]}
            return {'status':'completed','output':[{'type':'function_call','name':'request_human_fieldwork','arguments':json.dumps(scripted(s)['proposal'])}]}
        result=run_live('label-copying-fake',transport=oracle)
        self.assertEqual(len(observed),5); self.assertEqual(result['passing'],5)
        self.assertIn('NOT live',result['execution'])
        print('E07: transport that only reads expected label scores',result['passing'],'/',result['total'])

    def test_08_incomplete_or_failed_model_response_can_score_pass(self):
        for state in ('incomplete','failed'):
            result=run_live('fake',lambda _: {'status':state,'output':[],'error':{'code':'server_error'}},[SCENARIOS[0]])
            self.assertEqual(result['passing'],1)
        print('E08: status=incomplete/failed with empty output both counted as correct no_human')

    def test_09_null_required_fields_and_fractional_budget_are_accepted(self):
        p=self.payload()
        for key in ('agent','mission','title','location','scope','evidence_request'): p[key]=None
        p['budget']=1000.99
        tid=self.create(p); data=self.request('tasks/'+tid)[1]
        self.assertEqual(data['title'],'None'); self.assertEqual(data['budget'],1000)
        print('E09: null fields persisted as "None"; 1000.99 budget silently converted to 1000')

    def test_10_invalid_worker_type_disconnects_http(self):
        tid=self.create()
        with self.assertRaises(http.client.RemoteDisconnected):
            self.request('claim_task',{'task_id':tid,'worker':{'id':'w'}})
        self.assertEqual(self.request('tasks')[0],200)
        print('E10: worker object -> sqlite ProgrammingError -> HTTP disconnect, not controlled 4xx; server stays up')

    def test_11_original_evidence_lost_after_revision(self):
        tid=self.submitted()
        self.request('review_task',{'task_id':tid,'reviewer':'r','decision':'needs_revision','reason':'need dated image'})
        self.request('submit_evidence',{'task_id':tid,'worker':'worker-A','evidence':'replacement'})
        self.request('review_task',{'task_id':tid,'reviewer':'r','decision':'accepted'})
        data=self.request('tasks/'+tid)[1]
        events=self.request('audit')[1]['events']
        submits=[x for x in events if x['action']=='submitted']
        self.assertEqual(data['evidence'],'replacement'); self.assertEqual(len(submits),2)
        self.assertTrue(all(x['detail']=='' for x in submits))
        print('E11: original evidence overwritten; two audit rows contain no evidence/version/hash')

    def test_12_dispute_has_no_recovery_transition(self):
        tid=self.submitted()
        self.assertEqual(self.request('review_task',{'task_id':tid,'reviewer':'r','decision':'disputed'})[0],200)
        self.assertEqual(self.request('review_task',{'task_id':tid,'reviewer':'r','decision':'accepted'})[0],409)
        self.assertEqual(self.request('submit_evidence',{'task_id':tid,'worker':'worker-A','evidence':'appeal'})[0],403)
        self.assertEqual(self.request('tasks/'+tid)[1]['status'],'disputed')
        print('E12: disputed -> no appeal/review/resubmit transition; reserved budget remains occupied')

    def test_13_cli_exits_success_when_all_model_requests_fail(self):
        output = Path(self.tmp.name) / 'cli-results.json'
        wrapper = """import runpy,sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
output=sys.argv[2]
sys.argv=['agent_live_gate_v10.py','--output',output]
with patch.dict('os.environ', {'OPENAI_API_KEY':'review-fake-key-not-a-credential'}), patch('urllib.request.urlopen',side_effect=ConnectionError('review simulated transport outage')):
    runpy.run_module('agent_live_gate_v10',run_name='__main__')
"""
        result=subprocess.run([sys.executable,'-B','-c',wrapper,str(SOURCE),str(output)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(output.read_text())
        self.assertEqual(report['passing'],0); self.assertEqual(report['total'],5)
        print('E13: all 5 model calls fail (network mocked); CLI exits 0, report passing=0/5')

if __name__=='__main__': unittest.main(verbosity=2)

"""Bootstrap + real subprocess HTTP lifecycle + restart; synthetic content only.
No external network, real dispatch/payment, or provider calls. Never logs tokens.
"""
import base64
import datetime as dt
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'human_board'


def main():
    with tempfile.TemporaryDirectory(prefix='hb-runtime-') as td:
        db=Path(td)/'hb.db'; credentials=Path(td)/'credentials.json'
        bootstrap=[sys.executable,'-B',str(SOURCE/'bootstrap.py'),'--db',str(db),'--org','demo',
                   '--org-budget','100000','--credentials',str(credentials)]
        p=subprocess.run(bootstrap,capture_output=True,text=True)
        assert p.returncode==0,p.stderr
        assert credentials.stat().st_mode & 0o777==0o600
        assert db.stat().st_mode & 0o777==0o600
        before=credentials.read_bytes()
        assert subprocess.run(bootstrap,capture_output=True).returncode!=0
        assert credentials.read_bytes()==before
        tokens=json.loads(before)['tokens']
        with socket.socket() as s:
            s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
        environment=dict(os.environ,HB_DB=str(db),HB_HOST='127.0.0.1',HB_PORT=str(port))
        process=None
        def request(path,payload=None,who='ai_customer'):
            c=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            headers={'Content-Type':'application/json'}
            if who: headers['Authorization']='Bearer '+tokens['demo-'+who]
            try:
                c.request('GET' if payload is None else 'POST','/api/'+path,
                          None if payload is None else json.dumps(payload),headers)
                response=c.getresponse(); return response.status,json.loads(response.read())
            finally: c.close()
        def start():
            process=subprocess.Popen([sys.executable,'-B',str(SOURCE/'server.py')],env=environment,
                                     stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            for _ in range(100):
                if process.poll() is not None: raise AssertionError(process.stderr.read().decode())
                try:
                    if request('tasks')[0]==200: return process
                except (ConnectionError,OSError): pass
                time.sleep(.02)
            process.terminate(); process.wait(timeout=5); raise AssertionError('Startup readiness timeout')
        def stop(process):
            process.terminate(); process.wait(timeout=5); process.stderr.close()
        try:
            process=start()
            assert request('tasks',who=None)[0]==401
            mission=dict(mission='local-test',budget=10000,location='SYNTHETIC PUBLIC PLACE',
                         fieldwork_required=True,authorization_reference='SYNTHETIC manual authorization')
            assert request('register_mission',mission,'admin')[0]==201
            draft=dict(mission='local-test',title='SYNTHETIC public sign observation',location=mission['location'],
                       scope='Observe public sign without personal data',evidence_request='Synthetic raw record with time and place',
                       budget=5000,criteria=['record','time','place'],policy=dict(task_type='public_observation',
                       access='public_permitted',access_reference='SYNTHETIC permission',information_gap='No remote sign visibility record',
                       remote_alternative_checked=True,expertise_required=False,hazardous=False,personal_data=False))
            code,approval=request('approve_task',dict(agent='demo-ai_customer',proposal=draft),'admin'); assert code==201,approval
            order=dict(proposal=draft,approval_id=approval['approval_id'],idempotency_key='runtime-one-logical-order')
            code,created=request('create_task',order); assert code==201,created
            tid=created['task_id']
            assert request('claim_task',dict(task_id=tid),'worker')[0]==200
            observation='SYNTHETIC OBSERVATION: small sign text; not actual field evidence.'
            evidence=dict(observation=observation,observed_at=dt.datetime.now(dt.timezone.utc).isoformat(),location=draft['location'],
                          artifacts=[dict(name='synthetic.txt',media_type='text/plain',content_base64=base64.b64encode(observation.encode()).decode())])
            code,r=request('submit_evidence',dict(task_id=tid,evidence=evidence),'worker'); assert code==200,r
            code,opened=request('tasks/'+tid+'/evidence',who='reviewer'); assert code==200,opened
            sha=opened['evidence']['artifacts'][0]['sha256']
            checks={k:dict(passed=True,note='Synthetic artifact inspected manually',artifact_sha256=sha) for k in draft['criteria']}
            code,review=request('review_task',dict(task_id=tid,decision='accepted',reason='Manual synthetic-only verification',
                                inspection_receipt=opened['inspection_receipt'],checks=checks),'reviewer')
            assert code==200,review
            assert review['payment']=='SIMULATED_NOT_PAID' and review['ground_truth_confirmed'] is False
            stop(process); process=None
            process=start()
            code,replayed=request('create_task',order); assert code==200 and replayed['task_id']==tid and replayed['status']=='accepted'
            code,r=request('tasks/'+tid); assert code==200 and r['status']=='accepted'
            code,budgets=request('budgets',who='admin'); assert code==200
            assert all(x['reserved']==0 and x['committed']==5000 for x in budgets['budgets'])
            code,audit=request('audit',who='admin'); assert code==200
            assert any(x['action']=='review_accepted' for x in audit['events'])
            return dict(bootstrap='passed',credential_permissions='0600',duplicate_bootstrap='rejected_without_overwrite',
                        anonymous_api=401,authenticated_lifecycle='passed',review_method=review['review_method'],
                        subprocess_restart='passed',persisted_idempotent_replay=200,persisted_committed_krw=5000,
                        actual_tasks_dispatched=0,external_model_calls=0,actual_payments_krw=0)
        finally:
            if process is not None: stop(process)


if __name__=='__main__': print(json.dumps(main(),ensure_ascii=False,indent=2))

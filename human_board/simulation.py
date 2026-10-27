"""Isolated, synthetic rehearsal only. Not an authentication bypass for a running server."""
import base64
import datetime as dt
from pathlib import Path
import tempfile
import uuid
from storage import provision
from server import do


class Sandbox:
    def __init__(self, org_limit=100000):
        self.temp = tempfile.TemporaryDirectory(prefix='hb-synthetic-')
        self.db = Path(self.temp.name)/'simulation.sqlite3'
        self.tokens = provision(self.db,'synthetic',org_limit,
                                {'ai':'ai_customer','ai2':'ai_customer','worker':'worker','worker2':'worker',
                                 'reviewer':'reviewer','reviewer2':'reviewer','admin':'admin'})

    def close(self): self.temp.cleanup()
    def __enter__(self): return self
    def __exit__(self,*_): self.close()
    def call(self,action,p,who='ai'):
        return do(action,p,self.tokens[who],db=self.db)

    def mission(self, name='m', budget=100000, required=True, location='SIMULATED_PUBLIC_AREA'):
        return self.call('register_mission',dict(mission=name,budget=budget,location=location,
                         fieldwork_required=required,authorization_reference='SYNTHETIC local authorization'),'admin')

    def draft(self, **updates):
        p = dict(mission='m',title='공공 안내판 현장 관찰',location='SIMULATED_PUBLIC_AREA',
                 scope='공개 보행 구역의 안내 문구 관찰',evidence_request='관찰 기록 원문, 시간과 위치',budget=5000,
                 policy=dict(task_type='public_observation',access='public_permitted',
                             access_reference='SYNTHETIC permit reference',information_gap='Latest sign visibility unavailable remotely',
                             remote_alternative_checked=True,expertise_required=False,hazardous=False,personal_data=False),
                 criteria=['관찰 내용','방문 시간','장소','기록 원문'])
        p.update(updates)
        return p

    def order(self, draft=None, key=None):
        draft = draft or self.draft()
        code, approved = self.call('approve_task',dict(proposal=draft,agent='ai'),'admin')
        if code != 201: return code,approved
        return self.call('create_task',dict(proposal=draft,approval_id=approved['approval_id'],
                         idempotency_key=key or uuid.uuid4().hex))

    def evidence(self, observation='SYNTHETIC OBSERVATION: 안내 문구의 가독성이 낮음; 현장 사실 아님.'):
        return dict(observation=observation,observed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                    location='SIMULATED_PUBLIC_AREA',artifacts=[dict(name='synthetic.txt',media_type='text/plain',
                    content_base64=base64.b64encode(observation.encode()).decode())])

    def inspect(self, tid, who='reviewer', version=None):
        p = dict(task_id=tid)
        if version is not None: p['version']=version
        return self.call('get_evidence',p,who)

    def review(self,tid,decision='accepted',who='reviewer',reason='Manual inspection of synthetic artifact only'):
        code, inspected = self.inspect(tid,who)
        if code != 200: return code,inspected
        _, task = self.call('get_task_status',dict(task_id=tid),who)
        sha = inspected['evidence']['artifacts'][0]['sha256']
        checks = {c:dict(passed=True,note='Synthetic content inspected; no field truth established',artifact_sha256=sha) for c in task['criteria']}
        return self.call('review_task',dict(task_id=tid,decision=decision,reason=reason,
                         inspection_receipt=inspected['inspection_receipt'],checks=checks),who)

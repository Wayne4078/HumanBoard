"""Human Board V1.1 local authenticated simulation. No payment or external dispatch.
Run a fresh DB using README_V1.1.md. No anonymous API access or default credentials.
"""
import base64
import binascii
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import time
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit, parse_qs

from policy import content_error
from storage import initialize, connect, token_hash

ROOT = Path(__file__).parent
DB = Path(os.environ.get('HB_DB', ROOT/'human_board_v11.sqlite3'))
HOST = os.environ.get('HB_HOST', '127.0.0.1')
PORT = int(os.environ.get('HB_PORT', '8765'))
CAP = 100000
SAFE_TASK_MAX = 20000
MAX_BODY = 65536


class Problem(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def require(condition, status, message):
    if not condition: raise Problem(status, message)


def text(value, name, limit=2000):
    require(isinstance(value, str) and 0 < len(value.strip()) <= limit, 400, 'Invalid string: '+name)
    return value.strip()


def integer(value, name, lo=0, hi=100000):
    require(type(value) is int and lo <= value <= hi, 400, 'Invalid integer: '+name)
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def log(c, actor, action, task=None, detail=None):
    c.execute('INSERT INTO audit(org,task,action,actor,detail,ts) VALUES(?,?,?,?,?,?)',
              (actor['org'], task, action, actor['id'], canonical(detail or {}), int(time.time())))


def proposal(p):
    keys = {'mission','title','location','scope','evidence_request','budget','policy','criteria'}
    require(isinstance(p, dict) and set(p) == keys, 400, 'Proposal fields must match V1.1 schema')
    out = {k: text(p[k], k) for k in ('mission','title','location','scope','evidence_request')}
    out['budget'] = integer(p['budget'], 'budget', 1000, SAFE_TASK_MAX)
    rules = p['policy']
    required = {'task_type','access','access_reference','information_gap','remote_alternative_checked',
                'expertise_required','hazardous','personal_data'}
    require(isinstance(rules, dict) and set(rules) == required, 400, 'Explicit safety context required')
    require(rules['task_type'] == 'public_observation' and rules['access'] == 'public_permitted',
            403, 'Only permitted public observations supported')
    require(rules['remote_alternative_checked'] is True and rules['expertise_required'] is False
            and rules['hazardous'] is False and rules['personal_data'] is False,
            403, 'Unsafe, unnecessary or unsupported work; manual escalation required')
    text(rules['access_reference'], 'access_reference')
    text(rules['information_gap'], 'information_gap')
    error = content_error(*out.values(), *rules.values())
    require(error is None, 403, error or 'policy')
    criteria = p['criteria']
    require(isinstance(criteria, list) and 1 <= len(criteria) <= 10, 400, 'Review criteria required')
    criteria = [text(x, 'criterion', 200) for x in criteria]
    require(len(set(criteria)) == len(criteria), 400, 'Duplicate criterion')
    out.update(policy=rules, criteria=criteria)
    return out


def mission_check(c, actor, p):
    m = c.execute('SELECT * FROM missions WHERE org=? AND id=?', (actor['org'],p['mission'])).fetchone()
    require(m is not None, 403, 'No authorized mission')
    require(m['fieldwork_required'] == 1, 403, 'Mission has no approved field information gap')
    require(m['location'] == p['location'], 403, 'Location outside authorized mission scope')


def scopes(org, mission):
    return ('global', 'org:'+org, 'mission:'+canonical([org, mission]))


def reserve(c, actor, p):
    for scope in scopes(actor['org'], p['mission']):
        cur = c.execute('UPDATE budgets SET reserved=reserved+? WHERE scope=? AND reserved+committed+?<=limit_krw',
                        (p['budget'],scope,p['budget']))
        require(cur.rowcount == 1, 409, 'Budget exhausted: '+scope)


def settle(c, task, accepted=False):
    for scope in scopes(task['org'],task['mission']):
        c.execute('UPDATE budgets SET reserved=reserved-?,committed=committed+? WHERE scope=?',
                  (task['budget'],task['budget'] if accepted else 0,scope))


def authenticate(c, token):
    require(isinstance(token, str) and 20 <= len(token) <= 256, 401, 'Bearer authentication required')
    actor = c.execute('SELECT id,org,role FROM principals WHERE token_hash=? AND active=1', (token_hash(token),)).fetchone()
    require(actor is not None, 401, 'Invalid or revoked credential')
    return actor


def role(actor, *roles):
    require(actor['role'] in roles, 403, 'Role not permitted')


def visible(actor, task):
    if task['org'] != actor['org']: return False
    if actor['role'] == 'ai_customer': return task['agent'] == actor['id']
    if actor['role'] == 'worker': return task['status'] == 'open' or task['worker'] == actor['id']
    return True


def find_task(c, actor, p):
    tid = text(p.get('task_id'), 'task_id', 100)
    t = c.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone()
    require(t is not None and visible(actor,t), 404, 'Task not found')
    return t


def task_view(t):
    # Evidence bodies are accessible only through the versioned evidence endpoint.
    fields = ('id','agent','mission','budget','status','worker','evidence_version','review_reason','created')
    return {**{k:t[k] for k in fields}, **json.loads(t['proposal']),
            'payment':'SIMULATED_NOT_PAID', 'ground_truth_confirmed':False}


def evidence_payload(p, task):
    require(isinstance(p, dict) and set(p) == {'observation','observed_at','location','artifacts'}, 400, 'Structured evidence required')
    text(p['observation'],'observation',4000)
    require(len(p['observation'].strip()) >= 10, 400, 'Observation too short')
    require(p['location'] == json.loads(task['proposal'])['location'], 400, 'Evidence location mismatch')
    try:
        stamp = dt.datetime.fromisoformat(text(p['observed_at'],'observed_at',60))
        require(stamp.tzinfo is not None and task['created']-300 <= stamp.timestamp() <= time.time()+300,
                400, 'Observation time outside task interval')
    except ValueError:
        raise Problem(400, 'Invalid observation time')
    artifacts = p['artifacts']
    require(isinstance(artifacts,list) and 1 <= len(artifacts) <= 4, 400, 'Actual evidence artifacts required')
    result = []
    for a in artifacts:
        require(isinstance(a,dict) and set(a) == {'name','media_type','content_base64'}, 400, 'Invalid artifact')
        name = text(a['name'],'artifact name',100)
        media = a['media_type']
        require(media in ('text/plain','image/png','image/jpeg'), 400, 'Unsupported media type')
        try:
            raw = base64.b64decode(text(a['content_base64'],'artifact bytes',45000), validate=True)
        except (ValueError,binascii.Error): raise Problem(400,'Invalid base64')
        require(10 <= len(raw) <= 32000, 400, 'Artifact size outside allowed range')
        if media == 'text/plain':
            try: raw.decode('utf-8')
            except UnicodeDecodeError: raise Problem(400,'Text artifact must be UTF-8')
        if media == 'image/png': require(raw.startswith(b'\x89PNG\r\n\x1a\n'),400,'Invalid PNG signature')
        if media == 'image/jpeg': require(raw.startswith(b'\xff\xd8\xff'),400,'Invalid JPEG signature')
        result.append({**a,'name':name,'sha256':hashlib.sha256(raw).hexdigest()})
    return {**p,'artifacts':result}


def dispatch(c, actor, action, p):
    if action == 'register_mission':
        role(actor,'admin')
        mid = text(p.get('mission'),'mission')
        amount = integer(p.get('budget'),'budget')
        location = text(p.get('location'),'location')
        reference = text(p.get('authorization_reference'),'authorization_reference')
        require(type(p.get('fieldwork_required')) is bool, 400, 'fieldwork_required must be boolean')
        require(c.execute('SELECT 1 FROM missions WHERE org=? AND id=?',(actor['org'],mid)).fetchone() is None,
                409,'Mission already registered; no silent replacement')
        c.execute('INSERT INTO missions VALUES(?,?,?,?,?)', (actor['org'],mid,location,int(p['fieldwork_required']),reference))
        c.execute('INSERT INTO budgets(scope,limit_krw) VALUES(?,?)', (scopes(actor['org'],mid)[2],amount))
        log(c,actor,'mission_registered',detail={'mission':mid,'budget':amount})
        return 201, {'mission':mid}
    if action == 'approve_task':
        role(actor,'admin')
        draft = proposal(p.get('proposal'))
        mission_check(c,actor,draft)
        agent = text(p.get('agent'),'agent')
        target = c.execute("SELECT 1 FROM principals WHERE id=? AND org=? AND role='ai_customer' AND active=1",
                           (agent,actor['org'])).fetchone()
        require(target is not None,403,'Approval must target an active AI customer in this organization')
        ttl = integer(p.get('expires_in',900),'expires_in',1,3600)
        aid = 'AP-'+uuid.uuid4().hex
        c.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?,NULL)',
                  (aid,actor['org'],agent,digest(draft),actor['id'],int(time.time())+ttl))
        log(c,actor,'approved',detail={'approval_id':aid,'proposal_sha256':digest(draft),'agent':agent})
        return 201, {'approval_id':aid,'expires_in':ttl,'proposal_sha256':digest(draft)}
    if action == 'create_task':
        role(actor,'ai_customer')
        draft = proposal(p.get('proposal'))
        key = text(p.get('idempotency_key'),'idempotency_key',128)
        aid = text(p.get('approval_id'),'approval_id',100)
        request_digest = digest({'proposal':draft,'approval_id':aid})
        previous = c.execute('SELECT * FROM tasks WHERE org=? AND agent=? AND idempotency_key=?',
                             (actor['org'],actor['id'],key)).fetchone()
        if previous:
            require(previous['request_digest'] == request_digest,409,'Idempotency key reused with different request')
            return 200, {'task_id':previous['id'],'status':previous['status'],'replayed':True}
        mission_check(c,actor,draft)
        a = c.execute('SELECT * FROM approvals WHERE id=?',(aid,)).fetchone()
        require(a is not None and a['org'] == actor['org'] and a['agent'] == actor['id']
                and a['digest'] == digest(draft) and a['expires'] > time.time()
                and a['consumed_task'] is None,403,'Missing, expired, changed or consumed approval')
        reserve(c,actor,draft)
        tid = 'HB-'+uuid.uuid4().hex.upper()
        c.execute('INSERT INTO tasks(id,org,agent,mission,proposal,budget,status,created,approval_id,idempotency_key,request_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                  (tid,actor['org'],actor['id'],draft['mission'],canonical(draft),draft['budget'],'open',int(time.time()),aid,key,request_digest))
        c.execute('UPDATE approvals SET consumed_task=? WHERE id=?',(tid,aid))
        log(c,actor,'created',tid,{'approval_id':aid,'budget':draft['budget']})
        return 201, {'task_id':tid,'status':'open','reserved_budget_krw':draft['budget']}
    if action == 'list_tasks':
        rows = c.execute('SELECT * FROM tasks WHERE org=? ORDER BY created DESC,id', (actor['org'],)).fetchall()
        return 200, {'tasks':[task_view(t) for t in rows if visible(actor,t)]}
    if action == 'audit':
        role(actor,'admin','reviewer')
        limit = integer(p.get('limit',100),'limit',1,100)
        after = integer(p.get('after',0),'after',0,2**63-1)
        tid = p.get('task_id')
        if tid is not None: find_task(c,actor,p)
        rows = c.execute('SELECT * FROM audit WHERE org=? AND id>? AND (? IS NULL OR task=?) ORDER BY id LIMIT ?',
                         (actor['org'],after,tid,tid,limit)).fetchall()
        return 200, {'events':[dict(r) for r in rows],'next_after': rows[-1]['id'] if rows else after}
    if action == 'budgets':
        role(actor,'admin')
        ids = [r['id'] for r in c.execute('SELECT id FROM missions WHERE org=?',(actor['org'],))]
        allowed = ['org:'+actor['org']] + [scopes(actor['org'],mid)[2] for mid in ids]
        rows = [c.execute('SELECT * FROM budgets WHERE scope=?',(scope,)).fetchone() for scope in allowed]
        # global counter intentionally omitted: other organizations' consumption is private.
        return 200, {'budgets':[dict(r) for r in rows]}

    require(action in ('get_task_status','claim_task','submit_evidence','get_evidence','review_task','resolve_dispute','cancel_task'),404,'Unknown action')
    task = find_task(c,actor,p)
    tid = task['id']
    if action == 'get_task_status': return 200, task_view(task)
    if action == 'claim_task':
        role(actor,'worker')
        if 'worker' in p: require(p['worker'] == actor['id'],403,'Cannot impersonate another worker')
        require(task['status'] == 'open',409,'Task not open')
        c.execute("UPDATE tasks SET status='claimed',worker=? WHERE id=?",(actor['id'],tid))
        log(c,actor,'claimed',tid)
        return 200, {'status':'claimed'}
    if action == 'submit_evidence':
        role(actor,'worker')
        require(task['worker'] == actor['id'] and p.get('worker',actor['id']) == actor['id'],403,'Not assigned worker')
        require(task['status'] in ('claimed','needs_revision'),409,'Not accepting evidence')
        body = evidence_payload(p.get('evidence'),task)
        version = task['evidence_version']+1
        sha = digest(body)
        c.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?)',(tid,version,actor['id'],canonical(body),sha,int(time.time())))
        c.execute("UPDATE tasks SET status='submitted',evidence_version=? WHERE id=?",(version,tid))
        log(c,actor,'submitted',tid,{'version':version,'sha256':sha})
        return 200, {'status':'submitted','evidence_version':version,'sha256':sha}
    if action == 'get_evidence':
        role(actor,'reviewer','admin','worker','ai_customer')
        require(actor['role'] != 'worker' or task['worker'] == actor['id'],403,'Not assigned worker')
        version = integer(p.get('version',task['evidence_version']),'version',1,100000)
        ev = c.execute('SELECT * FROM evidence WHERE task=? AND version=?',(tid,version)).fetchone()
        require(ev is not None,404,'Evidence version not found')
        receipt = None
        if actor['role'] == 'reviewer':
            receipt = secrets.token_urlsafe(32)
            c.execute('INSERT INTO inspections VALUES(?,?,?,?,?,0)',(receipt,tid,version,actor['id'],ev['digest']))
            log(c,actor,'evidence_opened',tid,{'version':version,'sha256':ev['digest']})
        return 200, {'version':version,'sha256':ev['digest'],'evidence':json.loads(ev['payload']),
                     'inspection_receipt':receipt,'ground_truth_confirmed':False}
    if action == 'review_task':
        role(actor,'reviewer')
        require(actor['id'] != task['worker'] and p.get('reviewer',actor['id']) == actor['id'],403,'Independent reviewer required')
        require(task['status'] == 'submitted',409,'Only submitted tasks can be reviewed')
        decision = p.get('decision')
        require(decision in ('accepted','needs_revision','disputed'),400,'Invalid review decision')
        reason = text(p.get('reason'),'reason')
        receipt = text(p.get('inspection_receipt'),'inspection_receipt',100)
        inspected = c.execute('SELECT * FROM inspections WHERE receipt=?',(receipt,)).fetchone()
        require(inspected is not None and inspected['reviewer'] == actor['id'] and inspected['task'] == tid
                and inspected['version'] == task['evidence_version'] and not inspected['used'],409,'Open the current evidence version before review')
        checks = p.get('checks',{})
        require(isinstance(checks,dict),400,'Invalid criterion checks')
        if decision == 'accepted':
            criteria = json.loads(task['proposal'])['criteria']
            require(set(checks) == set(criteria),400,'Every approved criterion must be checked')
            ev = c.execute('SELECT payload FROM evidence WHERE task=? AND version=?',(tid,task['evidence_version'])).fetchone()
            hashes = {a['sha256'] for a in json.loads(ev['payload'])['artifacts']}
            for item in checks.values():
                require(isinstance(item,dict) and item.get('passed') is True,400,'Unmet evidence criterion')
                text(item.get('note'),'criterion justification')
                require(isinstance(item.get('artifact_sha256'),str) and item['artifact_sha256'] in hashes,400,'Criterion must reference inspected artifact')
            settle(c,task,accepted=True)
        c.execute('UPDATE inspections SET used=1 WHERE receipt=?',(receipt,))
        c.execute('INSERT INTO reviews(task,version,reviewer,decision,reason,checks,digest,created) VALUES(?,?,?,?,?,?,?,?)',
                  (tid,task['evidence_version'],actor['id'],decision,reason,canonical(checks),inspected['digest'],int(time.time())))
        c.execute('UPDATE tasks SET status=?,review_reason=? WHERE id=?',(decision,reason,tid))
        log(c,actor,'review_'+decision,tid,{'version':task['evidence_version'],'sha256':inspected['digest'],'reason':reason,'checks':checks,'method':'MANUAL_REVIEW'})
        return 200, {'status':decision,'payment':'SIMULATED_NOT_PAID','review_method':'MANUAL_REVIEW','ground_truth_confirmed':False}
    if action == 'resolve_dispute':
        role(actor,'admin')
        require(task['status'] == 'disputed',409,'Task not disputed')
        decision = p.get('decision')
        require(decision in ('needs_revision','cancelled'),400,'Reopen for evidence or cancel; no direct acceptance')
        reason = text(p.get('reason'),'reason')
        if decision == 'cancelled': settle(c,task)
        c.execute('UPDATE tasks SET status=? WHERE id=?',(decision,tid))
        log(c,actor,'dispute_'+decision,tid,{'reason':reason})
        return 200, {'status':decision,'payment':'SIMULATED_NOT_PAID'}
    if action == 'cancel_task':
        role(actor,'admin')
        require(task['status'] in ('open','claimed','submitted','needs_revision','disputed'),409,'Already final; cannot release committed budget')
        reason = text(p.get('reason'),'reason')
        settle(c,task)
        c.execute("UPDATE tasks SET status='cancelled' WHERE id=?",(tid,))
        log(c,actor,'cancelled',tid,{'reason':reason})
        return 200, {'status':'cancelled','payment':'SIMULATED_NOT_PAID'}
    raise Problem(404,'Unknown action')


def do(action, p, token=None, db=None):
    c = None
    try:
        require(isinstance(p,dict),400,'JSON object required')
        # No DB file or initialization side effects from anonymous calls.
        require(isinstance(token,str) and 20 <= len(token) <= 256,401,'Bearer authentication required')
        c = connect(db or DB)
        require(c.execute('PRAGMA user_version').fetchone()[0] == 11,503,'Initialize a new V1.1 database first')
        c.execute('BEGIN IMMEDIATE')
        actor = authenticate(c,token)
        result = dispatch(c,actor,action,p)
        c.commit()
        return result
    except Problem as exc:
        if c: c.rollback()
        return exc.status, {'error':exc.message}
    except sqlite3.OperationalError:
        if c: c.rollback()
        return 503, {'error':'Database unavailable or busy; retry with the same idempotency key'}
    except sqlite3.IntegrityError:
        if c: c.rollback()
        return 409, {'error':'Database invariant conflict'}
    finally:
        if c: c.close()


class Handler(BaseHTTPRequestHandler):
    server_version = 'HumanBoard/1.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        # Do not log URLs, authorization, or submitted evidence.
        pass

    def send(self,status,obj):
        out = json.dumps(obj,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(out)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        if status == 401: self.send_header('WWW-Authenticate','Bearer')
        if status == 503: self.send_header('Retry-After','1')
        self.end_headers()
        self.wfile.write(out)

    def token(self):
        auth = self.headers.get('Authorization','')
        return auth[7:] if auth.startswith('Bearer ') else None

    def invoke(self,action,p):
        try: return self.send(*do(action,p,self.token(),getattr(self.server,'db',DB)))
        except Exception:
            # Unexpected errors are fail-closed JSON responses, never a successful mutation.
            return self.send(500,{'error':'Internal server error'})

    def do_GET(self):
        path = urlsplit(self.path)
        if path.path == '/':
            b = (ROOT/'board.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(b)))
            self.send_header('Cache-Control','no-store')
            self.end_headers(); self.wfile.write(b); return
        query = parse_qs(path.query)
        try:
            p = {k:integer(int(v[0]),k,0,2**63-1) if k in ('limit','after','version') else v[0] for k,v in query.items()}
        except (ValueError,Problem): return self.send(400,{'error':'Invalid query'})
        action = {'/api/tasks':'list_tasks','/api/audit':'audit','/api/budgets':'budgets'}.get(path.path)
        pieces = path.path.split('/')
        if len(pieces) in (4,5) and pieces[1:3] == ['api','tasks']:
            p['task_id'] = pieces[3]
            action = 'get_task_status' if len(pieces)==4 else ('get_evidence' if pieces[4]=='evidence' else None)
        if action: return self.invoke(action,p)
        return self.send(404,{'error':'Not found'})

    def do_POST(self):
        action = self.path.removeprefix('/api/')
        if self.path != '/api/'+action or action not in {'register_mission','approve_task','create_task','claim_task',
                'submit_evidence','review_task','resolve_dispute','cancel_task'}:
            return self.send(404,{'error':'Not found'})
        # Reject unauthorized requests before parsing a potentially large or stalled body.
        if self.token() is None:
            self.close_connection = True
            return self.send(401,{'error':'Bearer authentication required'})
        try:
            require(self.headers.get('Transfer-Encoding') is None,400,'Transfer encoding unsupported')
            sizes = self.headers.get_all('Content-Length',[])
            require(len(sizes) == 1,400,'One Content-Length required')
            n = int(sizes[0])
            require(0 < n <= MAX_BODY,413 if n > MAX_BODY else 400,'Invalid body length')
            require(self.headers.get_content_type() == 'application/json',415,'JSON required')
            raw = self.rfile.read(n)
            require(len(raw) == n,400,'Incomplete body')
            def pairs(items):
                d = {}
                for k,v in items:
                    if k in d: raise ValueError('Duplicate JSON key')
                    d[k] = v
                return d
            data = json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite number')))
            require(isinstance(data,dict),400,'JSON object required')
        except (ValueError,TypeError,UnicodeDecodeError):
            self.close_connection = True
            return self.send(400,{'error':'Invalid JSON object'})
        except (socket.timeout,TimeoutError):
            self.close_connection = True
            return self.send(408,{'error':'Body read timed out'})
        except Problem as exc:
            self.close_connection = True
            return self.send(exc.status,{'error':exc.message})
        return self.invoke(action,data)


if __name__ == '__main__':
    initialize(DB,CAP)
    http = ThreadingHTTPServer((HOST,PORT),Handler)
    http.db = DB
    print('Human Board V1.1 local simulation; authenticated API; no payments')
    http.serve_forever()

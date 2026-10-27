"""SQLite schema v11. Legacy databases are deliberately NOT silently upgraded."""
import hashlib
import secrets
import sqlite3

SCHEMA = '''
CREATE TABLE budgets (
 scope TEXT PRIMARY KEY, limit_krw INTEGER NOT NULL CHECK(limit_krw >= 0),
 reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved >= 0),
 committed INTEGER NOT NULL DEFAULT 0 CHECK(committed >= 0),
 CHECK(reserved + committed <= limit_krw));
CREATE TABLE principals (
 id TEXT PRIMARY KEY, org TEXT NOT NULL, role TEXT NOT NULL
 CHECK(role IN ('ai_customer','worker','reviewer','admin')),
 token_hash TEXT UNIQUE NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE missions (
 org TEXT NOT NULL, id TEXT NOT NULL, location TEXT NOT NULL,
 fieldwork_required INTEGER NOT NULL, authorization_reference TEXT NOT NULL,
 PRIMARY KEY(org,id));
CREATE TABLE approvals (
 id TEXT PRIMARY KEY, org TEXT NOT NULL, agent TEXT NOT NULL REFERENCES principals(id),
 digest TEXT NOT NULL, approver TEXT NOT NULL REFERENCES principals(id),
 expires INTEGER NOT NULL, consumed_task TEXT);
CREATE TABLE tasks (
 id TEXT PRIMARY KEY, org TEXT NOT NULL, agent TEXT NOT NULL, mission TEXT NOT NULL,
 proposal TEXT NOT NULL, budget INTEGER NOT NULL, status TEXT NOT NULL,
 worker TEXT, evidence_version INTEGER NOT NULL DEFAULT 0, review_reason TEXT,
 created INTEGER NOT NULL, approval_id TEXT UNIQUE NOT NULL REFERENCES approvals(id),
 idempotency_key TEXT NOT NULL, request_digest TEXT NOT NULL,
 UNIQUE(org,agent,idempotency_key));
CREATE TABLE evidence (
 task TEXT NOT NULL REFERENCES tasks(id), version INTEGER NOT NULL,
 worker TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, created INTEGER NOT NULL,
 PRIMARY KEY(task,version));
CREATE TABLE inspections (
 receipt TEXT PRIMARY KEY, task TEXT NOT NULL, version INTEGER NOT NULL,
 reviewer TEXT NOT NULL, digest TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0,
 FOREIGN KEY(task,version) REFERENCES evidence(task,version));
CREATE TABLE reviews (
 id INTEGER PRIMARY KEY, task TEXT NOT NULL, version INTEGER NOT NULL,
 reviewer TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
 checks TEXT NOT NULL, digest TEXT NOT NULL, created INTEGER NOT NULL);
CREATE TABLE audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, org TEXT NOT NULL, task TEXT,
 action TEXT NOT NULL, actor TEXT NOT NULL, detail TEXT NOT NULL, ts INTEGER NOT NULL);
CREATE INDEX audit_org_id ON audit(org,id);
PRAGMA user_version=11;
'''


def connect(path):
    c = sqlite3.connect(path, timeout=5, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


def initialize(path, cap=100000):
    c = connect(path)
    try:
        # Serialize first-time initialization, including competing process starts.
        c.execute('BEGIN IMMEDIATE')
        version = c.execute('PRAGMA user_version').fetchone()[0]
        tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if version == 11:
            c.commit(); return
        if tables or version:
            raise RuntimeError('Legacy/unknown database: preserve it and use a new V1.1 DB; no automatic migration')
        # executescript commits implicitly: issue each statement inside our transaction.
        for statement in SCHEMA.split(';'):
            if statement.strip(): c.execute(statement)
        c.execute('INSERT INTO budgets(scope,limit_krw) VALUES(?,?)', ('global', cap))
        c.commit()
    except Exception:
        c.rollback(); raise
    finally:
        c.close()


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def provision(path, org, org_limit, identities):
    """Trusted local operator only. No HTTP route. Returns new secrets, never logs them.

    identities is {unique_subject: role}. IDs cannot be reused across roles/orgs.
    Call only on new orgs; repeat provisioning fails rather than replacing identities.
    """
    initialize(path)
    c = connect(path)
    tokens = {subject: secrets.token_urlsafe(32) for subject in identities}
    try:
        c.execute('BEGIN IMMEDIATE')
        c.execute('INSERT INTO budgets(scope,limit_krw) VALUES(?,?)', ('org:'+org, org_limit))
        for subject, role in identities.items():
            c.execute('INSERT INTO principals(id,org,role,token_hash) VALUES(?,?,?,?)',
                      (subject, org, role, token_hash(tokens[subject])))
        c.commit()
    except Exception:
        c.rollback(); raise
    finally:
        c.close()
    return tokens

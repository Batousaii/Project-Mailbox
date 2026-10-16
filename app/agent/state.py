"""Persistent local decisions, forward journal and work items."""
import csv
import datetime as dt
import json
import os
import sqlite3
from pathlib import Path

UTC = dt.timezone.utc


def utc_now():
    return dt.datetime.now(UTC).isoformat(timespec='seconds')


def data_dir():
    p = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'EE-ReliabilityAgent' / 'data'
    p.mkdir(parents=True, exist_ok=True)
    return p


class State:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.root / 'agent.db'), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA busy_timeout=30000')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages (
          entry_id TEXT PRIMARY KEY, store_id TEXT, conversation_id TEXT, received TEXT,
          subject TEXT, categories TEXT, status TEXT NOT NULL,
          forward_decision TEXT DEFAULT '', ai_reason TEXT DEFAULT '', confidence REAL DEFAULT 0,
          plan_type TEXT DEFAULT 'NONE', plan_target TEXT DEFAULT '', work_requested INTEGER DEFAULT 0,
          review_required INTEGER DEFAULT 0, system_message INTEGER DEFAULT 0,
          plan_pending INTEGER DEFAULT 0,
          send_token TEXT UNIQUE, send_attempted TEXT, sent_at TEXT, last_seen TEXT,
          error TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS work_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT, group_key TEXT NOT NULL,
          first_entry_id TEXT NOT NULL, last_entry_id TEXT NOT NULL,
          plan_type TEXT NOT NULL, plan_target TEXT, priority TEXT NOT NULL DEFAULT 'HIGH', subject TEXT, latest_request TEXT,
          confidence REAL, reason TEXT, review_status TEXT NOT NULL DEFAULT 'OPEN',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(group_key,plan_type,plan_target)
        );
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT, event_time TEXT NOT NULL,
          entry_id TEXT, event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_msg_status ON messages(status);
        CREATE INDEX IF NOT EXISTS idx_work_group ON work_items(group_key);
        ''')
        # Non-destructive schema migration when updating an earlier v1 installation.
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(messages)')}
        if 'plan_pending' not in columns:
            self.db.execute('ALTER TABLE messages ADD COLUMN plan_pending INTEGER DEFAULT 0')
        work_columns = {r[1] for r in self.db.execute('PRAGMA table_info(work_items)')}
        if 'priority' not in work_columns:
            self.db.execute("ALTER TABLE work_items ADD COLUMN priority TEXT NOT NULL DEFAULT 'HIGH'")
        if 'llm_domain' not in columns:
            self.db.execute("ALTER TABLE messages ADD COLUMN llm_domain TEXT NOT NULL DEFAULT 'UNCLEAR'")
        if 'llm_evidence' not in columns:
            self.db.execute("ALTER TABLE messages ADD COLUMN llm_evidence TEXT NOT NULL DEFAULT ''")
        for name in ('message_intent', 'intent_evidence', 'plan_review_version',
                     'action_summary','action_owner','action_timing','verification_note'):
            if name not in columns:
                self.db.execute(f"ALTER TABLE messages ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        if self.setting('completion_policy_version') != '1.7.1':
            self.db.execute("""UPDATE messages SET status='NEW',forward_decision=''
                WHERE status='READY' AND send_token IS NULL""")
            self.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('completion_policy_version','1.7.1')")
        # Old plan-only READY decisions must be re-evaluated under separate policy.
        self.db.execute("""UPDATE messages SET status='NEW',forward_decision=''
            WHERE status='READY' AND forward_decision='SEND_PLAN' AND send_token IS NULL""")
        self.db.commit()

    def conversation_memory(self, msg):
        """Bounded previous local records, context only; never new-action evidence."""
        if not msg.get('conversation_id'):
            return ''
        rows=self.db.execute('''SELECT subject,status,plan_type,llm_evidence,message_intent
            FROM messages WHERE conversation_id=? AND entry_id!=? AND llm_evidence!=''
            ORDER BY received DESC LIMIT 3''',(msg['conversation_id'],msg['entry_id'])).fetchall()
        if not rows:
            return ''
        context={'source':'PRIOR_LOCAL_AGENT_RECORDS_CONTEXT_ONLY',
                 'warning':'Earlier generated decisions may be wrong; not proof of new work or completion.',
                 'records':[]}
        for row in rows:
            record={k:str(v or '')[:220] for k,v in dict(row).items()}
            context['records'].append(record)
            if len(json.dumps(context,ensure_ascii=False))>1800:
                context['records'].pop()
                break
        return json.dumps(context,ensure_ascii=False)

    def close(self):
        self.db.close()

    def setting(self, key, default=None):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default

    def set_setting(self, key, val):
        self.db.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(val)))
        self.db.commit()

    def audit(self, event, entry_id='', detail=''):
        self.db.execute('INSERT INTO audit(event_time,entry_id,event,detail) VALUES(?,?,?,?)', (utc_now(), entry_id, event, str(detail)[:3000]))
        self.db.commit()

    def exists(self, entry_id):
        return self.db.execute('SELECT 1 FROM messages WHERE entry_id=?', (entry_id,)).fetchone() is not None

    def metadata(self, msg, historical=False):
        now = utc_now()
        was_new = not self.exists(msg['entry_id'])
        self.db.execute('''INSERT INTO messages(entry_id,store_id,conversation_id,received,subject,categories,status,last_seen)
          VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(entry_id) DO UPDATE SET
          categories=excluded.categories,last_seen=excluded.last_seen''',
          (msg['entry_id'], msg['store_id'], msg['conversation_id'], msg['received'],
           msg['subject'], msg['categories'], 'HISTORICAL_IGNORE' if historical else 'NEW', now))
        self.db.commit()
        if was_new:
            self.audit('HISTORICAL_IGNORE' if historical else 'NEW_MAIL', msg['entry_id'],
                       f"categories={msg['categories']!r}; subject={msg['subject'][:180]}")
        return was_new

    def row(self, entry_id):
        return self.db.execute('SELECT * FROM messages WHERE entry_id=?', (entry_id,)).fetchone()

    def classify(self, entry_id, decision, cls, system_message, plan_pending=False):
        status = 'REVIEW_REQUIRED' if decision == 'REVIEW_REQUIRED' else 'READY'
        if decision.startswith('SUPPRESS') or decision in ('SKIP_NOT_EI','SKIP_NOT_RELEVANT'):
            status = 'SKIPPED'
        self.db.execute('''UPDATE messages SET status=?,forward_decision=?,ai_reason=?,confidence=?,
          plan_type=?,plan_target=?,work_requested=?,review_required=?,system_message=?,plan_pending=?,
          llm_domain=?,llm_evidence=?,message_intent=?,intent_evidence=?,
          action_summary=?,action_owner=?,action_timing=?,verification_note=?,error=''
          WHERE entry_id=? AND status IN ('NEW','REVIEW_REQUIRED','READY')''',
          (status, decision, cls.reason, cls.confidence, cls.plan_type, cls.plan_target,
           int(cls.work_requested), int(cls.review_required), int(system_message), int(plan_pending),
           cls.domain, cls.evidence, cls.message_intent, cls.intent_evidence,
           cls.action_summary,cls.action_owner,cls.action_timing,cls.verification_note,entry_id))
        self.db.commit()
        self.audit('CLASSIFIED', entry_id, f'{decision}; category={self.row(entry_id)["categories"]!r}; domain={cls.domain}; evidence={cls.evidence!r}; reason={cls.reason}')

    def complete_deferred_plan(self, entry_id, cls):
        # Do not change forwarding status: Hamza may already have been sent.
        self.db.execute('''UPDATE messages SET ai_reason=?,confidence=?,plan_type=?,
          plan_target=?,work_requested=?,review_required=?,plan_pending=0,
          llm_domain=?,llm_evidence=?,message_intent=?,intent_evidence=?,
          action_summary=?,action_owner=?,action_timing=?,verification_note=? WHERE entry_id=?''',
          (cls.reason, cls.confidence, cls.plan_type, cls.plan_target,
           int(cls.work_requested), int(cls.review_required), cls.domain, cls.evidence, cls.message_intent, cls.intent_evidence,
           cls.action_summary,cls.action_owner,cls.action_timing,cls.verification_note,entry_id))
        self.db.commit()
        self.audit('DEFERRED_PLAN_AI_DONE', entry_id, f'{cls.plan_type}; confidence={cls.confidence}')

    def add_work_item(self, msg, cls, latest):
        if not cls.work_requested or cls.plan_type == 'NONE':
            return
        group_key = msg['conversation_id'] or msg['group_fallback']
        target = (cls.plan_target or 'DOEL_ONBEKEND').strip().casefold()
        now = utc_now()
        self.db.execute('''INSERT INTO work_items(group_key,first_entry_id,last_entry_id,plan_type,
          plan_target,priority,subject,latest_request,confidence,reason,review_status,created_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(group_key,plan_type,plan_target)
          DO UPDATE SET last_entry_id=excluded.last_entry_id,latest_request=excluded.latest_request,
          reason=excluded.reason, confidence=excluded.confidence,updated_at=excluded.updated_at,
          review_status=CASE WHEN excluded.review_status='REVIEW_REQUIRED' THEN 'REVIEW_REQUIRED' ELSE work_items.review_status END''',
          (group_key, msg['entry_id'], msg['entry_id'], cls.plan_type, target, 'HIGH', msg['subject'],
           latest[:1200], cls.confidence, cls.reason,
           'REVIEW_REQUIRED' if cls.review_required else 'OPEN', now, now))
        self.db.commit()
        self.audit('PLAN_REQUEST', msg['entry_id'], f'{cls.plan_type}; target={target}; confidence={cls.confidence}')

    def reserve_send(self, entry_id, token):
        """Atomic send reservation: never send twice for an EntryID."""
        with self.db:
            cur = self.db.execute('''UPDATE messages SET status='SEND_PENDING',send_token=?,
                 send_attempted=?,error='' WHERE entry_id=?
                 AND status IN ('READY','FORWARD_FAILED') AND send_token IS NULL
                 AND forward_decision IN ('SEND_HAMZA','SEND_EI')''',
                 (token, utc_now(), entry_id))
            if cur.rowcount != 1:
                return False
        self.audit('SEND_PENDING', entry_id, f'token={token}')
        return True

    def submitted(self, entry_id, token):
        with self.db:
            self.db.execute("UPDATE messages SET status='SUBMITTED' WHERE entry_id=? AND send_token=? AND status='SEND_PENDING'", (entry_id,token))
        self.audit('SUBMITTED',entry_id,f'token={token}; Outlook accepted, Sent Items not yet verified')

    def sent(self, entry_id, token):
        with self.db:
            self.db.execute('''UPDATE messages SET status='SENT',sent_at=?,error=''
                               WHERE entry_id=? AND send_token=? AND status IN ('SEND_PENDING','SUBMITTED','UNKNOWN')''',
                            (utc_now(), entry_id, token))
        self.audit('SENT', entry_id, f'token={token}')

    def unknown(self, entry_id, reason):
        self.db.execute("UPDATE messages SET status='UNKNOWN',error=? WHERE entry_id=? AND status IN ('SEND_PENDING','SUBMITTED')",
                        (str(reason)[:500], entry_id))
        self.db.commit()
        self.audit('UNKNOWN', entry_id, reason)

    def recover_interrupted_sends(self):
        rows = self.db.execute("SELECT entry_id FROM messages WHERE status='SEND_PENDING'").fetchall()
        for row in rows:
            self.unknown(row['entry_id'], 'Crash/restart tijdens onzekere Outlook-verzending; GEEN automatische retry')
        return len(rows)

    def ready(self):
        return self.db.execute("SELECT * FROM messages WHERE status='READY' AND forward_decision IN ('SEND_HAMZA','SEND_EI') ORDER BY received").fetchall()

    def unknown_rows(self):
        return self.db.execute("SELECT * FROM messages WHERE status IN ('UNKNOWN','SUBMITTED') AND send_token IS NOT NULL").fetchall()

    def counts(self):
        return {r['status']: r['n'] for r in self.db.execute('SELECT status,COUNT(*) n FROM messages GROUP BY status')}

    def backup(self):
        target = self.root / 'backups'
        target.mkdir(exist_ok=True)
        path = target / ('agent-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.db')
        other = sqlite3.connect(path)
        try:
            self.db.backup(other)
        finally:
            other.close()
        return str(path)

    def export_reports(self):
        defs = {
            'work_items.csv': ('SELECT id,group_key,first_entry_id,last_entry_id,plan_type,plan_target,priority,subject,'
                               'confidence,reason,review_status,created_at,updated_at FROM work_items', None),
            'plan_requests.csv': ('SELECT entry_id,received,subject,categories,plan_type,plan_target,work_requested,'
                                  'confidence,review_required,ai_reason,llm_domain,llm_evidence FROM messages '
                                  "WHERE plan_type != 'NONE' OR (review_required=1 AND status != 'HISTORICAL_IGNORE')", None),
            'mail_audit.csv': ('SELECT entry_id,received,subject,categories,status,forward_decision,confidence,'
                               'ai_reason,llm_domain,llm_evidence,message_intent,intent_evidence,action_summary,'
                               'action_owner,action_timing,verification_note,send_attempted,sent_at,error FROM messages', None),
            'review_queue.csv': ("SELECT entry_id,received,subject,ai_reason,llm_evidence,action_summary,"
                                 "action_owner,action_timing,verification_note FROM messages WHERE status='REVIEW_REQUIRED'",None),
        }
        for name,(q,_) in defs.items():
            rows = self.db.execute(q)
            columns = [x[0] for x in rows.description]
            with (self.root / name).open('w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(columns)
                writer.writerows(tuple("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in row) for row in rows)

    def monthly_open_report(self):
        """Only agent-confirmed sent = handled; not proof of business completion."""
        threshold = (dt.datetime.now(UTC)-dt.timedelta(days=30)).isoformat(timespec='seconds')
        rows = self.db.execute('''SELECT entry_id,received,subject,categories,status,forward_decision
          FROM messages WHERE received < ? AND status NOT IN ('HISTORICAL_IGNORE','SENT','SKIPPED')
          AND (forward_decision IN ('SEND_EI','SEND_HAMZA','REVIEW_REQUIRED') OR status='NEW')''',
          (threshold,)).fetchall()
        with (self.root / 'unhandled_30_days.csv').open('w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow(['EntryID','Received','Subject','Categories','Status','Decision'])
            w.writerows(tuple("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in r) for r in rows)
        self.set_setting('monthly_report_at', utc_now())
        self.audit('MONTHLY_CHECK', detail=f'Possible unhandled: {len(rows)}; HISTORICAL_IGNORE not assessed')
        return len(rows)


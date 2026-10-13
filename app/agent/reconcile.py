"""V1.6 audited re-assessment of the CURRENT shared Inbox.

Never sends, writes to source Outlook items, or changes agent.db. The active
12-hour policy and send journal remain the sole authority for forwarding.
"""
import csv
import datetime as dt
import json
import re
from pathlib import Path
import sqlite3

from . import ai
from .rules import (Decision, decide_forward, has_hamza_category,
                    is_system_message, split_latest_message)

COLUMNS = [
    'EntryID', 'ReceivedUTC', 'Subject', 'OutlookCategories', 'HamzaCategory',
    'Classification', 'MessageIntent', 'IntentEvidence', 'Domain', 'PlanType', 'PlanTarget', 'Confidence',
    'EvidenceFromLatestMessage', 'Reason', 'ReviewRequired',
    'ConversationID', 'WorkRequestKey', 'ExistingAgentStatus',
    'ExistingAgentDecision', 'HistoricalBatchOutcome', 'AlreadySent', 'Error',
]


def _readonly_connection(path):
    """Always close explicit SQLite handles (Windows WinError 32 safeguard)."""
    uri = path.resolve().as_uri() + '?mode=ro'
    db = sqlite3.connect(uri, uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=1')
    return db


def _old_registry(db):
    return db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='historical_llm_backfill_v1'").fetchone() is not None


def _read_old_states(db):
    """Read all previous state; NEVER repair/override uncertain send outcomes."""
    existing = {r['entry_id']: dict(r) for r in db.execute(
        'SELECT entry_id,status,forward_decision,send_token FROM messages')}
    historic = {}
    if _old_registry(db):
        historic = {r['entry_id']: dict(r) for r in db.execute(
            'SELECT entry_id,outcome,send_token FROM historical_llm_backfill_v1')}
    count_work = db.execute('SELECT COUNT(*) FROM work_items').fetchone()[0]
    return existing, historic, count_work


def _count_category(categories):
    return has_hamza_category(categories)


def _work_key(msg, decision):
    if not decision.work_requested or decision.plan_type not in ('CREATE_PLAN','MODIFY_PLAN'):
        return ''
    key = (msg.get('conversation_id') or msg.get('group_fallback') or msg['entry_id']).strip().casefold()
    target = decision.plan_target.strip().casefold() or 'unknown'
    return '|'.join([key, decision.plan_type, target])


def _one(msg, gateway, previous, history, classify):
    details = gateway.detail(msg)  # Live Outlook property; NEVER infer category from subject.
    cats = str(details.get('categories', ''))
    latest, context = split_latest_message(details.get('body', ''))
    sysmsg = is_system_message(msg.get('subject',''), details.get('message_class',''),
                               details.get('headers',''), details.get('body',''))
    hamza = _count_category(cats)
    error = ''
    decision = Decision(reason='Geen LLM-analyse uitgevoerd', review_required=True)
    if sysmsg:
        outcome = decide_forward(cats, True, decision)
    else:
        # Category has precedence. A missing Ollama response cannot cancel Hamza.
        if hamza:
            outcome = 'SEND_HAMZA'
            try:
                decision = classify(msg['subject'], latest, context)
            except Exception as exc:
                error = 'LLM-planannotation failed (Hamza priority retained): ' + str(exc)[:350]
        else:
            try:
                decision = classify(msg['subject'], latest, context)
                outcome = decide_forward(cats, False, decision)
            except Exception as exc:
                error = 'LLM classification failed: ' + str(exc)[:350]
                outcome = 'ERROR_REVIEW_REQUIRED'
    old_state = previous.get(msg['entry_id'], {})
    hist_state = history.get(msg['entry_id'], {})
    # Outlook .Send/SENT != confirmed receipt; do NOT rewrite history records.
    sent = old_state.get('status') == 'SENT' or hist_state.get('outcome') == 'SENT'
    return {
        'EntryID': msg['entry_id'], 'ReceivedUTC': msg.get('received',''),
        'Subject': msg.get('subject',''), 'OutlookCategories': cats,
        'HamzaCategory': 'YES' if hamza else 'NO',
        'Classification': outcome, 'MessageIntent': decision.message_intent,
        'IntentEvidence': decision.intent_evidence,
        'Domain': decision.domain, 'PlanType': decision.plan_type,
        'PlanTarget': decision.plan_target, 'Confidence': decision.confidence,
        'EvidenceFromLatestMessage': decision.evidence,
        'Reason': decision.reason, 'ReviewRequired': 'YES' if decision.review_required else 'NO',
        'ConversationID': msg.get('conversation_id',''),
        'WorkRequestKey': _work_key(msg, decision) if not decision.review_required else '',
        'ExistingAgentStatus': old_state.get('status','NOT_IN_AGENT_DB'),
        'ExistingAgentDecision': old_state.get('forward_decision',''),
        'HistoricalBatchOutcome': hist_state.get('outcome',''),
        'AlreadySent': 'YES' if sent else 'NO', 'Error': error,
    }


def _atomic_json(path, obj):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def audit_full(data_root, gateway, classify=None, output=None, snapshot=None):
    """Snapshot and re-evaluate every Inbox MailItem, 0 forwards and 0 source changes.

    Historical items and current NEW items are REPORT-ONLY in this function.
    The live daemon remains responsible for new mail and deduplication.
    """
    data_root = Path(data_root)
    path = data_root / 'agent.db'
    if not path.exists():
        raise RuntimeError('agent.db bestaat niet; GEEN nieuwe baseline aanmaken')
    data_root.mkdir(parents=True, exist_ok=True)
    if classify is None:
        classify = ai.classify
    db = _readonly_connection(path)
    try:
        existing, history, work_count = _read_old_states(db)
        old_baseline = db.execute("SELECT value FROM settings WHERE key='baseline_completed'").fetchone()
        if old_baseline is None or old_baseline[0] != '1':
            raise RuntimeError('Historische baseline ontbreekt; alleen read-only controle toegestaan')
    finally:
        db.close()
    if snapshot is None:
        snapshot = gateway.snapshot()
    ids = [m['entry_id'] for m in snapshot]
    if len(ids) != len(set(ids)):
        raise RuntimeError('Dubbele EntryIDs in Outlook-snapshot; resultaten zouden onbetrouwbaar zijn')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    result_dir = data_root / 'mailbox_audits' / stamp
    if result_dir.exists():
        result_dir = data_root / 'mailbox_audits' / (stamp + '-retry')
    result_dir.mkdir(parents=True, exist_ok=False)
    csv_path = result_dir / 'mailbox_per_mail.csv'
    counts = {}
    hamza_count = 0
    all_category_counts = {}
    encountered = 0
    previously_sent = 0
    errors = 0
    work_keys = set()
    # Stream each row to disk, including incomplete scans. A completed flag is
    # issued only after all messages have been considered. Never send email.
    with csv_path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=';', extrasaction='ignore')
        writer.writeheader()
        for i, msg in enumerate(snapshot, 1):
            try:
                row = _one(msg, gateway, existing, history, classify)
            except Exception as exc:
                row = {col:'' for col in COLUMNS}
                row.update({'EntryID':msg.get('entry_id',''),'ReceivedUTC':msg.get('received',''),
                            'Subject':msg.get('subject',''),'OutlookCategories':msg.get('categories',''),
                            'Classification':'ERROR_REVIEW_REQUIRED',
                            'ExistingAgentStatus':existing.get(msg['entry_id'],{}).get('status',''),
                            'Error':str(exc)[:500]})
            writer.writerow(row)
            f.flush()
            encountered += 1
            counts[row['Classification']] = counts.get(row['Classification'],0) + 1
            if row['HamzaCategory'] == 'YES':
                hamza_count += 1
            for label in re.split(r'[,;]', row['OutlookCategories'] or ''):
                label = label.strip()
                if label:
                    all_category_counts[label.casefold()] = all_category_counts.get(label.casefold(), 0) + 1
            if row['AlreadySent'] == 'YES':
                previously_sent += 1
            if row['WorkRequestKey']:
                work_keys.add(row['WorkRequestKey'])
            if row['Error'] or row['Classification'].startswith('ERROR'):
                errors += 1
            print(f'[{i}/{len(snapshot)}] {row["Classification"]} | Hamza={row["HamzaCategory"]} | '
                  f'{row["Subject"][:95]}', flush=True)
    summary = {
        'version':'1.7.1',
        'audit_finished_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
        'scope':'EE-Reliability / Inbox / MailItems only',
        'snapshot_inbox_count':len(snapshot),
        'processed_count':encountered,
        'snapshot_complete':encountered == len(snapshot),
        'all_classifications_completed':errors == 0 and encountered == len(snapshot),
        'failed_or_deferred_llm':errors,
        'outlook_hamza_category_count':hamza_count,
        'all_outlook_categories':dict(sorted(all_category_counts.items())),
        'decisions':counts,
        'distinct_plan_work_requests_current_inbox':len(work_keys),
        'old_work_item_rows_in_agent_db':work_count,
        'old_agent_message_rows':len(existing),
        'historical_batch_records':len(history),
        'historical_batch_outcomes':{k:sum(r.get('outcome') == k for r in history.values())
                                     for k in sorted({r.get('outcome','') for r in history.values()})},
        'historical_batch_uncertain_in_registry':sum(r.get('outcome') in ('UNKNOWN','SEND_PENDING') for r in history.values()),
        'previously_submitted_forwards_in_current_inbox':previously_sent,
        'previously_sent_other_folders_not_counted':True,
        'historical_mail_forwarded_by_this_audit':0,
        'source_mailbox_modified':False,
        'agent_database_modified':False,
        'report_csv':str(csv_path),
        'note':'LLM-confidence is not a calibrated probability; review actual evidence and audit before any new historical send.',
    }
    _atomic_json(result_dir / 'summary.json', summary)
    if summary['all_classifications_completed']:
        _atomic_json(data_root / 'mailbox_audit_latest.json', summary)
    else:
        _atomic_json(data_root / 'mailbox_audit_incomplete.json', summary)
    return summary

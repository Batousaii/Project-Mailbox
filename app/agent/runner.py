"""Foreground/hidden background agent. Single-instance mutex, 12 h cycle, recoverable errors."""
import ctypes
import datetime as dt
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import time
import threading
import uuid

from . import ai
from .visible_inbox import VisibleInboxGateway as OutlookGateway
from .rules import Decision, RECIPIENT, POLICY_VERSION, completed_notice, decide_forward, has_hamza_category, is_system_message, plan_review_candidate, split_latest_message
from .state import State, data_dir, utc_now

LOG = logging.getLogger('ee_reliability')
SCAN_INTERVAL = 12 * 3600
ERROR_RETRY = 15 * 60


def configure_log(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if not LOG.handlers:
        LOG.setLevel(logging.INFO)
        h = RotatingFileHandler(root / 'agent.log', maxBytes=4_000_000, backupCount=4, encoding='utf-8')
        h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        LOG.addHandler(h)


def heartbeat(st, detail=''):
    payload = {'pid': os.getpid(), 'heartbeat': utc_now(), 'last_scan': st.setting('last_scan'),
               'last_scan_error': st.setting('last_error',''),
               'last_scan_success': st.setting('last_scan_success'),
               'forwarding_enabled': st.setting('forward_enabled','0') == '1',
               'mailbox': st.setting('mailbox_status','UNKNOWN'),
               'state': detail or 'RUNNING'}
    path = st.root / 'runtime.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    tmp.replace(path)


def baseline(st, gw):
    if st.setting('baseline_completed') == '1':
        return 0
    rows = gw.snapshot()
    for msg in rows:
        st.metadata(msg, historical=True)
    st.set_setting('baseline_completed', '1')
    st.set_setting('baseline_time', utc_now())
    st.set_setting('mailbox_status', 'OK: ' + gw.mailbox_info()['store'])
    st.set_setting('forward_enabled', st.setting('forward_enabled', '0'))
    st.audit('BASELINE_COMPLETED', detail=f'{len(rows)} historische mails, 0 forwards, metadata only')
    st.export_reports()
    return len(rows)


def reconcile(st, gw):
    resolved = 0
    for row in st.unknown_rows():
        try:
            if gw.sent_copy_exists(row['send_token']):
                st.sent(row['entry_id'], row['send_token'])
                resolved += 1
        except Exception as exc:
            st.audit('RECONCILE_ERROR', row['entry_id'], str(exc))
    return resolved


def send_one(st, gw, row):
    token = str(uuid.uuid4())
    if not st.reserve_send(row['entry_id'], token):
        return False
    try:
        gw.forward(row['entry_id'], row['store_id'], RECIPIENT, token)
        # Outlook .Send() indicates submission, NOT confirmed recipient delivery.
        st.sent(row['entry_id'], token)
        return True
    except Exception as exc:
        # Ambiguous on .Send exception: no blind retry, even after restart.
        st.unknown(row['entry_id'], f'Outlook send outcome ambiguous: {exc}')
        LOG.exception('UNKNOWN send outcome %s', row['entry_id'])
        return False


def _scan(st, gw, allow_send=True):
    if st.setting('baseline_completed') != '1':
        raise RuntimeError('Geen historische baseline: scan niet toegestaan')
    # Full metadata snapshot includes a >=24 h overlap and catches outages >24 h.
    started = time.monotonic()
    messages = gw.snapshot()
    ai_attempts = 0
    new_count = 0
    sent_count = 0
    ai_error = None
    ai_unavailable = False
    for msg in messages:
        previous = st.row(msg['entry_id'])
        new = st.metadata(msg, historical=False)
        if new:
            new_count += 1
        row = st.row(msg['entry_id'])
        if row['status'] == 'HISTORICAL_IGNORE':
            continue
        if previous is not None and row['status'] in ('SKIPPED', 'REVIEW_REQUIRED') and row['send_token'] is None:
            # A category applied after arrival can still require a forward.
            if has_hamza_category(msg['categories']) and not has_hamza_category(previous['categories']):
                st.db.execute("UPDATE messages SET status='NEW' WHERE entry_id=?", (msg['entry_id'],))
                st.db.commit()
                row = st.row(msg['entry_id'])
        review_plan = (row['status'] == 'REVIEW_REQUIRED' and row['send_token'] is None
                       and row['plan_review_version'] != POLICY_VERSION
                       and plan_review_candidate(msg['subject'], row['llm_evidence']))
        deferred = bool(row['plan_pending']) or review_plan
        if row['status'] not in ('NEW',) and not deferred:
            continue
        try:
            details = gw.detail(msg)
            msg['categories'] = details['categories']
            if msg['categories'] != row['categories']:
                st.db.execute('UPDATE messages SET categories=? WHERE entry_id=?', (msg['categories'],msg['entry_id']))
                st.db.commit()
            system = is_system_message(msg['subject'], details['message_class'], details['headers'], details['body'])
            latest, context = split_latest_message(details['body'])
            completed = completed_notice(latest) if not system else None
            if completed is not None:
                if row['status'] in ('NEW','READY','REVIEW_REQUIRED') and row['send_token'] is None:
                    st.classify(msg['entry_id'], decide_forward(msg['categories'], False, completed), completed, False)
                elif deferred:
                    st.complete_deferred_plan(msg['entry_id'], completed)
                continue
            if deferred:
                if ai_unavailable:
                    continue
                try:
                    ai_attempts += 1
                    cls = ai.classify(msg['subject'], latest, context)
                except Exception:
                    ai_unavailable = True
                    raise
                st.complete_deferred_plan(msg['entry_id'], cls)
                if row['status'] == 'READY' and row['send_token'] is None and cls.message_intent in ('COMPLETED','STATUS_ONLY') and not cls.review_required:
                    st.classify(msg['entry_id'], decide_forward(msg['categories'], False, cls), cls, False)
                if cls.work_requested:
                    st.add_work_item(msg, cls, latest)
                if review_plan:
                    st.db.execute('UPDATE messages SET plan_review_version=? WHERE entry_id=?',
                                  (POLICY_VERSION,msg['entry_id']))
                    st.db.commit()
                    st.audit('PLAN_REVIEW_REASSESSED', msg['entry_id'],
                             'Report-only reassessment; no catch-up forward; '+cls.reason)
                continue
            if system:
                cls = Decision(reason='System-mail suppressed')
                decision = decide_forward(msg['categories'], True, cls)
                st.classify(msg['entry_id'], decision, cls, True)
                continue
            try:
                if ai_unavailable:
                    raise RuntimeError('AI unavailable in this scan; deferred until retry')
                ai_attempts += 1
                cls = ai.classify(msg['subject'], latest, context)
                plan_pending = False
            except Exception as ai_exc:
                ai_unavailable = True
                if not has_hamza_category(msg['categories']):
                    raise
                # Hard Hamza priority: never withhold its forward for an AI outage.
                cls = Decision(reason='AI_PENDING: ' + str(ai_exc)[:250], review_required=True)
                plan_pending = True
                st.audit('PLAN_AI_DEFERRED', msg['entry_id'], str(ai_exc))
            decision = decide_forward(msg['categories'], False, cls)
            st.classify(msg['entry_id'], decision, cls, False, plan_pending=plan_pending)
            if plan_review_candidate(msg['subject'], latest):
                st.db.execute('UPDATE messages SET plan_review_version=? WHERE entry_id=?',
                              (POLICY_VERSION,msg['entry_id']))
                st.db.commit()
            if cls.work_requested:
                st.add_work_item(msg, cls, latest)
            st.audit('CATEGORY_AND_LLM_V15', msg['entry_id'],
                     f"categories={msg['categories']!r}; decision={decision}; domain={cls.domain}; "
                     f"evidence={cls.evidence!r}; confidence={cls.confidence:.3f}; plan={cls.plan_type}")
        except Exception as exc:
            ai_error = str(exc)
            st.audit('CLASSIFICATION_ERROR', msg['entry_id'], ai_error)
            LOG.exception('Classification failed %s', msg['entry_id'])
            # Leave NEW / plan_pending; do not falsely declare classification complete.
            continue
    if allow_send and st.setting('forward_enabled') == '1':
        for row in st.ready():
            if send_one(st, gw, row):
                sent_count += 1
    duration = round(time.monotonic() - started, 3)
    st.set_setting('last_scan_duration_seconds', duration)
    st.set_setting('last_scan_ai_attempts', ai_attempts)
    st.set_setting('last_scan', utc_now())
    if ai_error:
        st.set_setting('last_error', ai_error)
        raise RuntimeError(ai_error)
    last = st.setting('monthly_report_at')
    if not last or (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last)).days >= 30:
        st.monthly_open_report()
    st.export_reports()
    st.set_setting('last_scan_success', utc_now())
    st.set_setting('last_error','')
    st.audit('SCAN_COMPLETED', detail=f'snapshot={len(messages)},new={new_count},sent={sent_count}')
    return {'snapshot': len(messages), 'new': new_count, 'sent': sent_count,
            'duration_seconds': duration, 'ai_attempts': ai_attempts}


def scan(st, gw, allow_send=True):
    try:
        return _scan(st, gw, allow_send)
    finally:
        try:
            ai.release_model()
        except Exception:
            LOG.warning('Model release unavailable; automatic 30s expiry remains configured')


def heartbeat_worker(root, stop):
    # SQLite connections belong to their creating thread; COM stays on main thread.
    st = State(root)
    try:
        while not stop.is_set():
            try:
                heartbeat(st, 'ACTIVE')
            except Exception:
                LOG.exception('Heartbeat write failed')
            stop.wait(45)
    finally:
        st.close()


def close_mutex(handle):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    kernel.CloseHandle(handle)


def instance_mutex():
    if os.name != 'nt':
        return None
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    h = kernel.CreateMutexW(None, False, r'Local\EEReliabilityAgent_MainProcess_v1')
    if not h:
        raise OSError('Failed to create agent mutex')
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        close_mutex(h)
        raise RuntimeError('Agent draait al; tweede instantie wordt niet gestart')
    return h


def daemon():
    mutex = instance_mutex()
    st = State()
    configure_log(st.root)
    st.recover_interrupted_sends()
    retry_at = 0.0
    retry_delay = ERROR_RETRY
    stop = threading.Event()
    worker = threading.Thread(target=heartbeat_worker, args=(st.root, stop), daemon=True)
    worker.start()
    last_successful_scan = 0.0
    try:
        while True:
            now = time.monotonic()
            trigger = st.root / 'scan.trigger'
            forced = trigger.exists()
            if forced:
                try: trigger.unlink()
                except OSError: pass
            if forced or (retry_at and now >= retry_at) or (not retry_at and (last_successful_scan == 0 or now-last_successful_scan >= SCAN_INTERVAL)):
                gw = None
                try:
                    gw = OutlookGateway()
                    st.set_setting('mailbox_status', 'OK: ' + gw.mailbox_info()['store'])
                    if st.setting('baseline_completed') != '1':
                        raise RuntimeError('Geen baseline; gebruik INSTALL.bat')
                    st.recover_interrupted_sends()
                    reconcile(st, gw)
                    result = scan(st, gw)
                    LOG.info('Scanned: %s', result)
                    last_successful_scan = time.monotonic()
                    retry_at = 0
                    retry_delay = ERROR_RETRY
                except Exception as exc:
                    LOG.exception('Scan failed')
                    st.set_setting('last_error', str(exc)[:500])
                    st.audit('SCAN_ERROR', detail=str(exc))
                    retry_at = time.monotonic() + retry_delay
                    retry_delay = min(retry_delay * 2, 3600)
                finally:
                    if gw is not None:
                        try:
                            gw.close()
                        except Exception:
                            LOG.exception('COM cleanup failed')
            time.sleep(30)
    finally:
        stop.set()
        worker.join(timeout=50)
        st.close()
        if mutex:
            close_mutex(mutex)

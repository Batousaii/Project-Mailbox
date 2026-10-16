"""Commands invoked ONLY from BAT launchers/installer."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
import time

from . import ai
from .visible_inbox import VisibleInboxGateway as OutlookGateway
from .rules import RECIPIENT, has_hamza_category, POLICY_VERSION
from .runner import baseline, configure_log, daemon, reconcile, scan, send_one
from .reconcile import audit_full
from .visible_inbox import VisibleInboxGateway, open_visible_inbox
from .state import State, data_dir, utc_now


def prereqs():
    if os.name != 'nt':
        raise RuntimeError('Deze Outlook-agent vereist Windows / klassieke Outlook')
    if sys.version_info < (3, 10) or sys.maxsize <= 2**32:
        raise RuntimeError('Python 64-bit >=3.10 vereist')
    import pythoncom
    import win32com.client
    version = platform.python_version()
    return {'python': version, 'python_path': sys.executable, 'pythoncom': 'OK', 'win32com': 'OK'}


def preflight():
    out = prereqs()
    out['ollama'] = ai.health(check_generation=True)
    gateway = OutlookGateway()
    out['outlook_com'] = 'OK'
    out['mailbox'] = gateway.mailbox_info()
    rows = gateway.snapshot()
    out['mailbox_snapshot_count'] = len(rows)
    return out


def status(st):
    checks = {}
    try:
        checks['python'] = prereqs()['python'] + ' OK'
    except Exception as exc:
        checks['python'] = 'FAIL: ' + str(exc)
    try:
        checks['ollama'] = ai.health(check_generation=False)
    except Exception as exc:
        checks['ollama'] = 'FAIL: ' + str(exc)
    try:
        gw = VisibleInboxGateway()
        checks['outlook_com'] = 'OK'
        checks['mailbox'] = gw.mailbox_info()['store']
        # Live count, not the 69-message installation baseline or stored workitem count.
        live = gw.snapshot()
        checks['current_inbox_mailitems'] = len(live)
        checks['current_hamza_categories'] = sum(has_hamza_category(m.get('categories','')) for m in live)
    except Exception as exc:
        checks['outlook_com'] = 'FAIL: ' + str(exc)
        checks['mailbox'] = 'UNAVAILABLE'
        checks['current_inbox_mailitems'] = 'UNAVAILABLE'
        checks['current_hamza_categories'] = 'UNAVAILABLE'
    runtime = {}
    try:
        runtime = json.loads((st.root / 'runtime.json').read_text(encoding='utf-8'))
    except Exception:
        pass
    active = False
    try:
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(runtime['heartbeat'])).total_seconds()
        active = age <= 120
        if active and os.name == 'nt':
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            k = ctypes.WinDLL('kernel32', use_last_error=True)
            k.OpenProcess.restype = ctypes.c_void_p
            h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(runtime['pid']))
            active = bool(h)
            if h:
                k.CloseHandle(ctypes.c_void_p(h))
    except Exception:
        active = False
    try:
        checks['last_full_mailbox_audit'] = json.loads((st.root / 'mailbox_audit_latest.json').read_text(encoding='utf-8'))
    except Exception:
        checks['last_full_mailbox_audit'] = 'NOT_COMPLETED'
    checks.update({
        'integrated_audit_version': '2.0.0',
        'forwarding_policy_version': POLICY_VERSION,
        'baseline': st.setting('baseline_completed','0') == '1',
        'historical_count': st.counts().get('HISTORICAL_IGNORE', 0),
        'scheduler': 'RUNNING' if active else 'NOT RUNNING',
        'heartbeat': runtime.get('heartbeat','NONE'),
        'last_scan': st.setting('last_scan','NEVER'),
        'last_scan_success': st.setting('last_scan_success','NEVER'),
        'last_scan_duration_seconds': st.setting('last_scan_duration_seconds','UNKNOWN'),
        'last_scan_ai_attempts': st.setting('last_scan_ai_attempts','UNKNOWN'),
        'last_error': st.setting('last_error',''),
        'forwarding': 'ENABLED' if st.setting('forward_enabled','0') == '1' else 'DISABLED (approval required)',
        'counts': st.counts(),
        'work_items': st.db.execute('SELECT COUNT(*) FROM work_items').fetchone()[0],
        'unconfirmed_sends': len(st.unknown_rows()),
        'unknown_sends': st.counts().get('UNKNOWN',0),
        'submitted_sends': st.counts().get('SUBMITTED',0),
        'sent_definition': 'Sent Items trace confirmed; recipient delivery requires separate confirmation',
        'reports_dir': str(st.root),
    })
    from .role_knowledge import load
    from .role_eval import signature
    knowledge=load()
    checks['role_knowledge']={'version':knowledge['version'],
                             'concepts':len(knowledge['concepts']),
                             'aliases':sum(len(c['aliases']) for c in knowledge['concepts'])}
    try:
        report=json.loads((Path(__file__).resolve().parents[1]/'role-evaluation.json').read_text(encoding='utf-8'))
        checks['saved_role_evaluation']={k:report.get(k) for k in ('completed_at','passed','failed','model','model_digest','false_forwards','missed_forwards','missed_work_items','unexpected_work_items')}
        checks['saved_role_evaluation']['matches_current_code']=report.get('signature')==signature()
    except (OSError,ValueError):
        checks['saved_role_evaluation']='NOT_RUN'
    return checks


def inventory_old(st):
    old = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'ReliabilityAgentClean'
    report = {'date': utc_now(), 'old_path': str(old), 'exists': old.exists(),
              'files': {}, 'tables': {}, 'policy': 'READ ONLY; nothing migrated or removed'}
    if old.exists():
        for name in ('ReliabilityAgent.ini','agent.db','plan_requests.csv','work_items.csv'):
            p = old / name
            report['files'][name] = {'exists':p.is_file(),'size':p.stat().st_size if p.is_file() else 0}
        db = old / 'agent.db'
        if db.is_file():
            try:
                uri = db.resolve().as_uri() + '?mode=ro'
                con = sqlite3.connect(uri, uri=True, timeout=2)
                try:
                    for name, in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                        # table names come from sqlite_master, guard quote.
                        count = con.execute('SELECT COUNT(*) FROM "' + name.replace('"','""') + '"').fetchone()[0]
                        report['tables'][name] = count
                finally:
                    con.close()
            except Exception as exc:
                report['db_read_error'] = str(exc)
    (st.root / 'old_agent_inventory.json').write_text(json.dumps(report, indent=2, ensure_ascii=False),encoding='utf-8')
    return report


def activate(st):
    if st.setting('baseline_completed') != '1':
        raise RuntimeError('Baseline ontbreekt, activatie verboden')
    if st.setting('forward_enabled') == '1':
        print('Forwarding is al actief.'); return
    print('Controleer verplichte controles...')
    print(json.dumps(preflight(), ensure_ascii=False, indent=2))
    if status(st)['scheduler'] != 'RUNNING':
        raise RuntimeError('Achtergrondagent draait niet; geen activering toegestaan')
    gw = OutlookGateway()
    # Safe classification (never sends while disabled).
    scan(st, gw, allow_send=False)
    tests = [r for r in st.db.execute("SELECT * FROM messages WHERE status IN ('READY','SENT','SUBMITTED','UNKNOWN') ORDER BY received") if 'EE-AGENT-TEST' in (r['subject'] or '').upper()
             and has_hamza_category(r['categories'])]
    if not tests:
        print('\nGEEN testbericht gevonden. Maak na de baseline een NIEUW bericht in de')
        print('gedeelde Inbox met "EE-AGENT-TEST" in het onderwerp en categorie "Hamza".')
        print('Voer vervolgens ACTIVATE.bat opnieuw uit. Historische mail wordt nooit gebruikt.')
        raise RuntimeError('Test-forward niet uitgevoerd; forwarding blijft UIT')
    test = tests[-1]
    print('\nTestbericht:', test['subject'])
    print('Ontvangen:', test['received'], '/ categories:',test['categories'])
    print('Doeladres:', RECIPIENT)
    print('Na bevestiging wordt precies EEN echte Outlook-forward verstuurd.')
    key = input('\nTyp exact TESTFORWARD GOEDGEKEURD om te versturen en te activeren: ').strip()
    if key != 'TESTFORWARD GOEDGEKEURD':
        raise RuntimeError('Geen expliciete goedkeuring; niets verzonden')
    if test['send_token'] is None and not send_one(st, gw, test):
        raise RuntimeError('Test-forward heeft onzekere uitkomst; forwarding blijft UIT. Controleer audit/Sent Items.')
    print('Outlook accepteerde de forward; controle op verzonden kopie...')
    token = st.row(test['entry_id'])['send_token']
    found = False
    for _ in range(8):
        if gw.sent_copy_exists(token):
            found = True
            break
        time.sleep(2)
    if not found:
        st.audit('TEST_SEND_NOT_VERIFIED', test['entry_id'], 'Sent Items contains no trace; activation blocked')
        raise RuntimeError('Verzonden kopie niet bevestigd. Geen activatie; test-mail NIET opnieuw verzenden.')
    st.sent(test['entry_id'],token)
    received = input('Bevestig werkelijke ontvangst: typ TEST ONTVANGEN: ').strip()
    if received != 'TEST ONTVANGEN':
        raise RuntimeError('Ontvangst niet bevestigd; forwarding blijft UIT. De test wordt niet opnieuw verstuurd.')
    st.set_setting('forward_enabled','1')
    st.set_setting('activated_at', utc_now())
    st.audit('FORWARDING_ACTIVATED', detail='Expliciete goedkeuring + testmail Sent Items bevestigd')
    (st.root / 'scan.trigger').touch()
    st.export_reports()
    print('\nForwarding = ENABLED. De achtergrondagent krijgt direct een nieuwe scan-trigger.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['preflight','inventory','backup','legacy_backup','baseline','once','daemon','status','activate','disable','trigger','audit_full'])
    args = parser.parse_args()
    if args.command == 'preflight':
        print(json.dumps(preflight(), indent=2, ensure_ascii=False));return
    if args.command == 'daemon':
        prereqs(); daemon(); return
    if args.command == 'status':
        st = State(); print(json.dumps(status(st), indent=2, ensure_ascii=False)); return
    if args.command == 'inventory':
        st = State(); print(json.dumps(inventory_old(st), indent=2, ensure_ascii=False));return
    if args.command == 'legacy_backup':
        from .legacy import backup_default
        print(json.dumps(backup_default(), indent=2, ensure_ascii=False));return
    if args.command == 'backup':
        st = State();print('SQLite backup:',st.backup());return
    if args.command == 'baseline':
        preflight()  # Mandatory HARD gate before any baseline.
        st = State(); gw = OutlookGateway()
        print('Historical metadata-only baseline:',baseline(st,gw))
        return
    if args.command == 'audit_full':
        prereqs()
        ai.health(check_generation=True)
        gateway, snapshot = open_visible_inbox()
        result = audit_full(data_dir(), gateway, snapshot=snapshot)
        print('\nV1.6 VOLLEDIGE MAILBOXAUDIT (GEEN FORWARDS):')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if not result['all_classifications_completed']:
            raise RuntimeError('Audit opgeslagen maar bevat onzekere beoordelingen; rapport vereist review')
        return
    if args.command == 'once':
        prereqs(); st=State();configure_log(st.root)
        print(json.dumps(scan(st,OutlookGateway()),ensure_ascii=False)); return
    if args.command == 'activate':
        prereqs(); st=State();configure_log(st.root); activate(st);return
    if args.command == 'disable':
        st=State();st.set_setting('forward_enabled','0');st.audit('FORWARDING_DISABLED',detail='Manual local control')
        print('Forwarding now DISABLED');return
    if args.command == 'trigger':
        st=State();(st.root / 'scan.trigger').touch();print('Scan requested');return


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('FOUT:', str(exc),file=sys.stderr)
        sys.exit(1)


"""One-shot V1.5 policy migration. No mailbox access or forwarding performed."""
import argparse
import csv
from contextlib import closing
import datetime as dt
import json
import re
import sqlite3
from pathlib import Path


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def database(root):
    db = Path(root) / 'data' / 'agent.db'
    if not db.exists():
        raise RuntimeError('Bestaande agent.db ontbreekt. Geen nieuwe baseline aanmaken.')
    con = sqlite3.connect(db, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=30000')
    return con


def setting(con, key, default='0'):
    r = con.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
    return r['value'] if r else default


def put_setting(con,key,value):
    con.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,value))


def audit(con,code,detail):
    con.execute('INSERT INTO audit(event_time,entry_id,event,detail) VALUES(?,?,?,?)',(now(),'POLICY_V15',code,str(detail)[:2500]))


def disable(root):
    marker = root / 'data' / 'policy_v15_prior_activation.txt'
    # sqlite3.Connection context management commits/rolls back but does NOT close.
    # An open handle locks agent.db on Windows and breaks TemporaryDirectory cleanup.
    with closing(database(root)) as con, con:
        before = setting(con,'forward_enabled','0')
        if before not in ('0','1'):
            raise RuntimeError('Forwarding instelling heeft onverwachte waarde')
        if not marker.exists():
            marker.write_text(before,encoding='ascii')
        put_setting(con,'forward_enabled','0')
        audit(con,'POLICY_V15_EMERGENCY_DISABLED','Historical scan unsafe; queued mail blocked pending corrected policy')
    print('NORMAL_FORWARDING_DISABLED; previous_approval='+marker.read_text(encoding='ascii').strip())


def backup(root):
    data=root/'data'
    backups=data/'backups'
    backups.mkdir(exist_ok=True)
    file=backups/('policy_v15_'+dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.db')
    src=database(root)
    try:
        dst=sqlite3.connect(file)
        try:
            src.backup(dst)
        finally:dst.close()
    finally:src.close()
    check=sqlite3.connect(f'file:{file.as_posix()}?mode=ro',uri=True)
    try:
        r=check.execute('PRAGMA quick_check').fetchone()
        if r[0]!='ok':
            raise RuntimeError('Databasebackup is corrupt: '+str(r[0]))
    finally: check.close()
    print('BACKUP_VERIFIED='+str(file))


def quarantine(root):
    con=database(root)
    try:
        with con:
            # Running historical writer was terminated first; never retry ambiguity.
            t=con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='historical_llm_backfill_v1'").fetchone()
            pending=0
            ambiguous=0
            if t:
                pending=con.execute('''UPDATE historical_llm_backfill_v1 SET outcome='SKIP_REVIEW',
                    error='V1.5 policy change: earlier ELIGIBLE is invalid; reviewed no send'
                    WHERE outcome='ELIGIBLE' AND send_token IS NULL''').rowcount
                ambiguous=con.execute('''UPDATE historical_llm_backfill_v1 SET outcome='UNKNOWN',
                    error='Stopped during old batch send; no automatic retry'
                    WHERE outcome IN ('SEND_PENDING','SUBMITTED')''').rowcount
            # Reset only never-attempted, non-historical normal classifications.
            # This forces the corrected AI to re-evaluate pending NEW work.
            rows=con.execute('''UPDATE messages SET status='NEW',forward_decision='',
                ai_reason='Reclassify after V1.5 stricter evidence/domain policy',confidence=0,
                review_required=0,plan_type='NONE',plan_target='',work_requested=0,
                llm_domain='UNCLEAR',llm_evidence=''
                WHERE status IN ('READY','SKIPPED','REVIEW_REQUIRED') AND send_token IS NULL
                AND status!='HISTORICAL_IGNORE' ''').rowcount
            # Block any future run of the *old* unsafe historical BAT, including
            # baseline messages it had not yet classified when interrupted.
            # The old batch skips a row whenever this table already contains it.
            if t:
                added=con.execute('''INSERT INTO historical_llm_backfill_v1 (
                    entry_id,store_id,received,subject,categories,conversation_id,
                    group_key,score,ei_relevant,work_requested,plan_type,plan_target,
                    review_required,reason,outcome,evaluated_at)
                    SELECT m.entry_id,m.store_id,m.received,m.subject,m.categories,
                           m.conversation_id,'',0,0,0,'NONE','',1,
                           'V1.5 safety policy: old bulk script disabled',
                           'SKIP_REVIEW',?
                    FROM messages m WHERE m.status='HISTORICAL_IGNORE'
                    AND NOT EXISTS(SELECT 1 FROM historical_llm_backfill_v1 h
                                   WHERE h.entry_id=m.entry_id)''',(now(),)).rowcount
            else:
                added=0
            put_setting(con,'policy_version','1.5.0')
            audit(con,'POLICY_V15_QUEUE_QUARANTINE',
                  json.dumps({'historical_unsent_quarantined':pending,'ambiguous':ambiguous,
                              'normal_reclassification_required':rows,
                              'historical_missing_blocked':added}))
        print(json.dumps({'historical_unsent_quarantined':pending,
              'historical_ambiguous_no_retry':ambiguous,
              'normal_queued_for_reclassification':rows,
              'historical_unscanned_blocked':added},ensure_ascii=False))
    finally:con.close()


def historical_report(root):
    file=root/'data'/'historical_v15_previous_forwards_AUDIT.csv'
    con=database(root)
    try:
        t=con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='historical_llm_backfill_v1'").fetchone()
        with file.open('w',newline='',encoding='utf-8-sig') as fh:
            w=csv.writer(fh,delimiter=';')
            w.writerow(['subject','categories','score_percent','plan_type','original_llm_reason',
                        'original_outcome','possible_mechanical_subject_ONLY','entry_id',
                        'AUDIT_NOTE'])
            if t:
                for r in con.execute('''SELECT subject,categories,score,plan_type,reason,outcome,entry_id
                                  FROM historical_llm_backfill_v1 ORDER BY received DESC'''):
                    mech=bool(re.search(r'\b(lager|bearing|gbx|gearbox|cutter|stoomtrap|gasket|schroeven|die.plate)\b',
                                        r['subject'] or '', re.I))
                    w.writerow([r['subject'],r['categories'],round((r['score'] or 0)*100,1),
                                r['plan_type'],r['reason'],r['outcome'],int(mech),r['entry_id'],
                                'ORIGINAL LABEL - NOT VERIFIED AGAINST BODY. No unsend possible.'])
        print('HISTORICAL_AUDIT_CSV='+str(file))
    finally:con.close()


def resume(root):
    marker=root/'data'/'policy_v15_prior_activation.txt'
    previous=marker.read_text(encoding='ascii').strip() if marker.exists() else '0'
    if previous not in ('0','1'):
        raise RuntimeError('Ongeldige activatiegeschiedenis')
    # sqlite3.Connection context management commits/rolls back but does NOT close.
    # An open handle locks agent.db on Windows and breaks TemporaryDirectory cleanup.
    with closing(database(root)) as con, con:
        if setting(con,'policy_version','')!='1.5.0':
            raise RuntimeError('Nieuwe policy nog niet gemigreerd; forwarding blijft UIT')
        put_setting(con,'forward_enabled',previous)
        audit(con,'POLICY_V15_RESUME','Forwarding restored from previous approval: '+previous)
    if previous=='1':
        (root/'data'/'scan.trigger').touch()
    if marker.exists():
        marker.unlink()  # A later intentional manual disable must not be overridden.
    print('FORWARDING='+('ENABLED' if previous=='1' else 'DISABLED'))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('action', choices=['disable','backup','quarantine','audit','resume'])
    p.add_argument('--root',required=True)
    args=p.parse_args()
    root=Path(args.root)
    if args.action=='disable':disable(root)
    elif args.action=='backup':backup(root)
    elif args.action=='quarantine':quarantine(root)
    elif args.action=='audit':historical_report(root)
    else:resume(root)

if __name__=='__main__':main()

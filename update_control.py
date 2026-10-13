"""Local upgrade backup and observable readiness; never forwards or changes approval."""
import argparse
from contextlib import closing
import datetime as dt
import json
import sqlite3
from pathlib import Path


def backup_database(root, destination):
    source=root/'data'/'agent.db'
    with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Database backup integrity check failed')
    print('Databasebackup verified: '+str(destination))


def readiness(root, since):
    runtime=json.loads((root/'data'/'runtime.json').read_text(encoding='utf-8'))
    now=dt.datetime.now(dt.timezone.utc)
    if (now-dt.datetime.fromisoformat(runtime['heartbeat'])).total_seconds()>120:
        raise RuntimeError('Heartbeat stale')
    con=sqlite3.connect((root/'data'/'agent.db').resolve().as_uri()+'?mode=ro',uri=True)
    try:
        values=dict(con.execute('SELECT key,value FROM settings'))
    finally:
        con.close()
    if values.get('last_error'):
        raise RuntimeError('Scan error: '+values['last_error'])
    completed=dt.datetime.fromisoformat(values.get('last_scan_success','1970-01-01T00:00:00+00:00'))
    if completed<dt.datetime.fromisoformat(since):
        raise RuntimeError('First successful scan not yet verified')
    print('RUNNING + first successful scan verified; forwarding='+values.get('forward_enabled','0'))


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['backup','ready'])
    p.add_argument('--root',type=Path,required=True);p.add_argument('--destination',type=Path);p.add_argument('--since')
    args=p.parse_args()
    if args.action=='backup': backup_database(args.root,args.destination)
    else:readiness(args.root,args.since)

if __name__=='__main__':
    main()

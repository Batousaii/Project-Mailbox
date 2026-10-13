"""A consistent, non-destructive preservation of the legacy agent BEFORE cutover."""
from __future__ import annotations

import datetime as dt
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def backup_legacy(old: Path, data: Path) -> dict:
    """Copy the full legacy tree; snapshot live SQLite via its online-backup API.

    Fail BEFORE disabling any process/autostart if a preservation step fails.
    Never read/write an old agent's SQLite file using a write connection.
    """
    old, data = Path(old), Path(data)
    if not old.exists():
        report = {'status': 'ABSENT', 'source': str(old), 'backup': None}
        data.mkdir(parents=True, exist_ok=True)
        (data / 'legacy_backup_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        return report
    if not old.is_dir():
        raise RuntimeError(f'Legacy location is not a folder: {old}')

    ts = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = data / 'legacy_backups' / f'{ts}-{uuid.uuid4().hex[:8]}'
    copied = target / 'ReliabilityAgentClean'
    target.mkdir(parents=True)
    db = old / 'agent.db'

    def ignore(folder, names):
        # A normal file copy of a live SQLite DB can be inconsistent. Create a
        # consistent transaction snapshot instead; journal is not needed there.
        if Path(folder).resolve() == old.resolve():
            return [x for x in ('agent.db', 'agent.db-wal', 'agent.db-shm') if x in names]
        return []

    try:
        shutil.copytree(old, copied, symlinks=True, ignore=ignore)
        if db.is_file():
            from urllib.parse import quote
            uri = 'file:' + quote(db.resolve().as_posix(), safe='/:') + '?mode=ro'
            with closing(sqlite3.connect(uri, uri=True, timeout=30)) as source:
                with closing(sqlite3.connect(copied / 'agent.db', timeout=30)) as dest:
                    source.backup(dest, pages=200, sleep=0.1)
                    result = dest.execute('PRAGMA quick_check').fetchone()
                    if not result or result[0] != 'ok':
                        raise RuntimeError('Legacy SQLite backup failed quick_check')
                    # Ensure a self-contained single-file SQLite backup (no WAL/SHM).
                    dest.execute('PRAGMA journal_mode=DELETE')
        originals = sorted(str(p.relative_to(old)) for p in old.rglob('*') if p.is_file()
                           and p.name not in ('agent.db-wal', 'agent.db-shm'))
        archived = sorted(str(p.relative_to(copied)) for p in copied.rglob('*') if p.is_file())
        if originals != archived:
            raise RuntimeError('Legacy backup file inventory does not match original; safe stop')
        checked = {}
        for name in ('ReliabilityAgent.ini', 'agent.db', 'plan_requests.csv', 'work_items.csv'):
            p = copied / name
            if p.is_file():
                checked[name] = {'bytes': p.stat().st_size, 'sha256': _hash_file(p)}
        report = {
            'status': 'VERIFIED', 'source': str(old), 'backup': str(copied),
            'file_count': len(archived), 'critical_files': checked,
            'note': 'Source untouched; agent.db SQLite online snapshot verified; no old sends imported',
        }
        (target / 'manifest.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        data.mkdir(parents=True, exist_ok=True)
        (data / 'legacy_backup_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        return report
    except Exception:
        # Leave partial copy for diagnosis, but NEVER proceed to stopping legacy.
        raise


def backup_default() -> dict:
    local = Path(os.environ.get('LOCALAPPDATA') or Path.home())
    return backup_legacy(local / 'ReliabilityAgentClean', local / 'EE-ReliabilityAgent' / 'data')

import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from agent.legacy import backup_legacy


class LegacyBackupTests(unittest.TestCase):
    def test_verified_snapshot_retains_original_and_all_audits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old, data = root / 'ReliabilityAgentClean', root / 'new-data'
            old.mkdir()
            (old / 'ReliabilityAgent.ini').write_text('enabled = false', encoding='utf-8')
            (old / 'plan_requests.csv').write_text('old candidate,open', encoding='utf-8')
            (old / 'work_items.csv').write_text('old id,open', encoding='utf-8')
            (old / 'nested').mkdir()
            (old / 'nested' / 'install.log').write_text('retained', encoding='utf-8')
            # Keep the *source* SQLite database open in WAL mode to simulate a
            # live old agent. Close both handles BEFORE TemporaryDirectory cleanup.
            # Merely using `with sqlite3.connect(...)` is insufficient: that
            # context manager commits/rolls back, but does NOT close on Windows.
            with closing(sqlite3.connect(old / 'agent.db')) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE audit (id INTEGER)')
                db.execute('INSERT INTO audit VALUES (9)')
                db.commit()
                report = backup_legacy(old, data)
                saved = Path(report['backup'])
                self.assertEqual('VERIFIED', report['status'])
                self.assertEqual(5, report['file_count'])
                self.assertTrue((old / 'agent.db').is_file())
                self.assertEqual('retained', (saved / 'nested' / 'install.log').read_text(encoding='utf-8'))
                # CRITICAL: in V1.3 this inline sqlite3.connect leaked its handle,
                # causing WinError 32 when the temporary backup was removed.
                with closing(sqlite3.connect(saved / 'agent.db')) as archived_db:
                    self.assertEqual(9, archived_db.execute('SELECT id FROM audit').fetchone()[0])
                    self.assertEqual('ok', archived_db.execute('PRAGMA quick_check').fetchone()[0])
                self.assertTrue((data / 'legacy_backup_report.json').exists())
                self.assertEqual('VERIFIED', json.loads((data / 'legacy_backup_report.json').read_text())['status'])
            # On Windows the enclosing temp directory must now be removable.

    def test_absent_old_agent_needs_no_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = backup_legacy(root / 'missing', root / 'new-data')
            self.assertEqual('ABSENT', report['status'])
            self.assertIsNone(report['backup'])

    def test_non_folder_stops_without_modifying(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / 'ReliabilityAgentClean'
            old.write_text('not a folder')
            with self.assertRaises(RuntimeError):
                backup_legacy(old, root / 'new-data')
            self.assertEqual('not a folder', old.read_text())


if __name__ == '__main__':
    unittest.main()

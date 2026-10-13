import datetime as dt
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'update_control.py'

class ReadinessTests(unittest.TestCase):
    def probe(self,root,since):
        return subprocess.run([sys.executable,str(SCRIPT),'ready','--root',str(root),'--since',since],capture_output=True,text=True)

    def test_missing_runtime_waits_without_stderr(self):
        with tempfile.TemporaryDirectory() as td:
            result=self.probe(Path(td),dt.datetime.now(dt.timezone.utc).isoformat())
            self.assertEqual(2,result.returncode)
            self.assertEqual('',result.stderr)
            self.assertIn('WAITING:',result.stdout)

    def test_pending_then_success_and_error_remains_not_ready(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);data=root/'data';data.mkdir()
            now=dt.datetime.now(dt.timezone.utc);since=now.isoformat()
            (data/'runtime.json').write_text(json.dumps({'heartbeat':since}))
            con=sqlite3.connect(data/'agent.db')
            con.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
            con.executemany('INSERT INTO settings VALUES (?,?)',[('last_scan_success',(now-dt.timedelta(hours=12)).isoformat()),('forward_enabled','0')]);con.commit()
            pending=self.probe(root,since)
            self.assertEqual(2,pending.returncode);self.assertEqual('',pending.stderr)
            self.assertIn('First successful scan not yet verified',pending.stdout)
            con.execute("UPDATE settings SET value=? WHERE key='last_scan_success'",(since,));con.commit()
            success=self.probe(root,since)
            self.assertEqual(0,success.returncode);self.assertIn('forwarding=0',success.stdout)
            con.execute("INSERT INTO settings VALUES ('last_error','Ollama offline')");con.commit()
            error=self.probe(root,since)
            self.assertEqual(2,error.returncode);self.assertEqual('',error.stderr)
            self.assertIn('Scan error',error.stdout)
            con.close()

    def test_corrupt_runtime_does_not_claim_ready(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'data').mkdir();(root/'data/runtime.json').write_text('{')
            result=self.probe(root,dt.datetime.now(dt.timezone.utc).isoformat())
            self.assertEqual(2,result.returncode);self.assertEqual('',result.stderr)

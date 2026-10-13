import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent.state import State
import policy_upgrade_helper as h

class UpgradeTests(unittest.TestCase):
    def test_stop_quarantine_persists_sends_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'data').mkdir()
            st=State(root/'data')
            st.set_setting('forward_enabled','1')
            st.metadata({'entry_id':'sent','store_id':'s','conversation_id':'c','received':'2026-10-08',
                        'subject':'lager','categories':'','group_fallback':'g'},historical=False)
            st.db.execute("UPDATE messages SET status='SENT',forward_decision='SEND_EI',send_token='token1' WHERE entry_id='sent'")
            st.metadata({'entry_id':'oldready','store_id':'s','conversation_id':'c','received':'2026-10-08',
                        'subject':'lager','categories':'','group_fallback':'g'},historical=False)
            st.db.execute("UPDATE messages SET status='READY',forward_decision='SEND_EI' WHERE entry_id='oldready'")
            st.db.executescript('''CREATE TABLE historical_llm_backfill_v1 (
                 entry_id TEXT PRIMARY KEY,store_id TEXT,received TEXT,subject TEXT,categories TEXT,
                 conversation_id TEXT,group_key TEXT,score REAL,ei_relevant INTEGER,
                 work_requested INTEGER,plan_type TEXT,plan_target TEXT,review_required INTEGER,
                 reason TEXT,outcome TEXT,send_token TEXT,error TEXT,evaluated_at TEXT);
                 INSERT INTO historical_llm_backfill_v1(entry_id,subject,categories,score,plan_type,reason,outcome)
                    VALUES ('hist1','lager','',.95,'CREATE_PLAN','bad guess','ELIGIBLE');
                 INSERT INTO historical_llm_backfill_v1(entry_id,subject,categories,score,plan_type,reason,outcome)
                    VALUES ('hist2','lager','',.95,'CREATE_PLAN','bad guess','SENT');
                 INSERT INTO historical_llm_backfill_v1(entry_id,subject,categories,score,plan_type,reason,outcome,send_token)
                    VALUES ('hist3','lager','',.95,'CREATE_PLAN','bad guess','SEND_PENDING','tok');''')
            st.metadata({'entry_id':'hist_unscreened','store_id':'s','conversation_id':'c',
                        'received':'2026-10-08','subject':'old','categories':'',
                        'group_fallback':'g'},historical=True)
            st.db.commit();st.close()
            h.disable(root)
            h.disable(root) # idempotence: preserve original approval
            h.backup(root)
            h.quarantine(root)
            h.historical_report(root)
            h.resume(root)
            c=sqlite3.connect(root/'data'/'agent.db')
            try:
                self.assertEqual('1',c.execute("SELECT value FROM settings WHERE key='forward_enabled'").fetchone()[0])
                self.assertEqual('SENT',c.execute("SELECT status FROM messages WHERE entry_id='sent'").fetchone()[0])
                self.assertEqual('NEW',c.execute("SELECT status FROM messages WHERE entry_id='oldready'").fetchone()[0])
                self.assertEqual('SKIP_REVIEW',c.execute("SELECT outcome FROM historical_llm_backfill_v1 WHERE entry_id='hist1'").fetchone()[0])
                self.assertEqual('SENT',c.execute("SELECT outcome FROM historical_llm_backfill_v1 WHERE entry_id='hist2'").fetchone()[0])
                self.assertEqual('UNKNOWN',c.execute("SELECT outcome FROM historical_llm_backfill_v1 WHERE entry_id='hist3'").fetchone()[0])
                self.assertEqual('SKIP_REVIEW',c.execute("SELECT outcome FROM historical_llm_backfill_v1 WHERE entry_id='hist_unscreened'").fetchone()[0])
            finally:c.close()
            self.assertTrue((root/'data'/'historical_v15_previous_forwards_AUDIT.csv').exists())
            self.assertFalse((root/'data'/'policy_v15_prior_activation.txt').exists())

    def test_disable_and_resume_close_sqlite_handles(self):
        # A sqlite3.Connection used as a context manager is NOT closed on exit.
        # This must remain true on Windows where open files cause WinError 32.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            st = State(root / 'data')
            st.set_setting('forward_enabled', '1')
            st.set_setting('policy_version', '1.5.0')
            st.close()
            opened = []
            original_database = h.database

            def record_connection(path):
                con = original_database(path)
                opened.append(con)
                return con

            with patch.object(h, 'database', side_effect=record_connection):
                h.disable(root)
                h.resume(root)
            self.assertEqual(2, len(opened))
            for con in opened:
                with self.assertRaises(sqlite3.ProgrammingError):
                    con.execute('SELECT 1')
            verify = sqlite3.connect(root / 'data' / 'agent.db')
            try:
                self.assertEqual('1', verify.execute(
                    "SELECT value FROM settings WHERE key='forward_enabled'").fetchone()[0])
            finally:
                verify.close()

if __name__=='__main__':unittest.main()

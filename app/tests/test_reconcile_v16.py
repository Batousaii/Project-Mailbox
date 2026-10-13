import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from agent.reconcile import audit_full as _audit_full
from contextlib import redirect_stdout
import io

def audit_full(*args, **kwargs):
    with redirect_stdout(io.StringIO()):
        return _audit_full(*args, **kwargs)
from agent.rules import Decision, ground_decision
from agent.state import State


def message(i, subj, body, cats='', conv=None):
    return {'entry_id':str(i), 'store_id':'STORE', 'received':'2026-10-08T12:00:00+00:00',
            'subject':subj, 'categories':cats, 'conversation_id':conv or str(i),
            'group_fallback':'subject:'+subj, 'body':body}


class Gateway:
    def __init__(self, rows):
        self.rows = rows
        self.sends = []
        self.item_modifications = 0
    def snapshot(self):
        return [{k:v for k,v in row.items() if k != 'body'} for row in self.rows]
    def detail(self, msg):
        item = next(x for x in self.rows if x['entry_id'] == msg['entry_id'])
        return {'body':item['body'], 'categories':item['categories'], 'headers':'', 'message_class':'IPM.Note'}
    def forward(self, *args):
        raise AssertionError('AUDIT MAY NEVER FORWARD')


def classify(subject, latest, context):
    if 'druktransmitter' in latest:
        return ground_decision(Decision(ei_relevant=True,domain='EI',
            evidence='spare voor druktransmitter PT101',confidence=.94,
            reason='Concrete E&I-spare'), subject, latest)
    if 'inspectieplan' in latest:
        return ground_decision(Decision(plan_type='CREATE_PLAN',work_requested=True,domain='PLAN',
            evidence='Maak nieuw inspectieplan voor pompen',confidence=.92,
            plan_target='pompen',reason='Concrete planvraag'),subject, latest)
    if 'lager' in latest:
        return Decision(domain='MECHANICAL',confidence=.95,reason='Mechanische spare')
    return Decision(domain='OTHER',confidence=.91,reason='Geen aanvraag')


class ReconcileTests(unittest.TestCase):
    def prepare(self, td, rows):
        root = Path(td)
        state = State(root)
        state.set_setting('baseline_completed','1')
        for item in rows[:2]:
            state.metadata(item,historical=True)
        state.close()
        return root

    def test_all_78_live_items_categories_and_no_sends(self):
        rows = [message(i,'info','Dit is enkel statusinformatie') for i in range(78)]
        rows[0] = message(0,'mechanical bearing','Graag nieuwe lager', 'Andere; hamza')
        rows[1] = message(1,'sensor','Graag spare voor druktransmitter PT101','E&I')
        rows[2] = message(2,'plan','Maak nieuw inspectieplan voor pompen','PO')
        rows[3] = message(3,'Bearing 123','Graag nieuwe lager','OTHER')
        with tempfile.TemporaryDirectory() as td:
            root = self.prepare(td, rows)
            gw = Gateway(rows)
            check = sqlite3.connect(root / 'agent.db')
            try:
                before = check.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
            finally:
                check.close()
            summary = audit_full(root, gw, classify)
            check = sqlite3.connect(root / 'agent.db')
            try:
                after = check.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
            finally:
                check.close()
            self.assertEqual((before, after), (2, 2))
            self.assertEqual(78, summary['snapshot_inbox_count'])
            self.assertEqual(2, summary['old_agent_message_rows'])
            self.assertEqual(1, summary['outlook_hamza_category_count'])
            self.assertEqual(1, summary['decisions']['SEND_HAMZA'])
            self.assertEqual(1, summary['decisions']['SEND_EI'])
            self.assertEqual(76, summary['decisions']['SKIP_NOT_RELEVANT'])
            self.assertEqual(0,summary['historical_mail_forwarded_by_this_audit'])
            self.assertEqual(0,summary['failed_or_deferred_llm'])
            self.assertTrue(summary['all_classifications_completed'])
            self.assertTrue((root/'mailbox_audit_latest.json').exists())
            self.assertEqual([],gw.sends)

    def test_hamza_overrides_llm_outage_and_system_mail_not_forwarded(self):
        rows = [message(0,'lager','Graag nieuwe lager','  HAMZA , Misc '),
                message(1,'Automatic reply: report','I am away','Hamza')]
        with tempfile.TemporaryDirectory() as td:
            root = self.prepare(td, rows)
            summary = audit_full(root, Gateway(rows), lambda *args: (_ for _ in ()).throw(RuntimeError('Ollama offline')))
            self.assertEqual(1,summary['decisions']['SEND_HAMZA'])
            self.assertEqual(1,summary['decisions']['SUPPRESS_SYSTEM_HAMZA'])
            self.assertFalse(summary['all_classifications_completed'])
            self.assertFalse((root/'mailbox_audit_latest.json').exists())
            self.assertTrue((root/'mailbox_audit_incomplete.json').exists())

    def test_distinct_work_requests_not_equal_email_count(self):
        rows = [message(0,'inspectieplan','Maak nieuw inspectieplan voor pompen','',conv='C1'),
                message(1,'Re inspectieplan','Maak nieuw inspectieplan voor pompen','',conv='C1'),
                message(2,'inspectieplan','Maak nieuw inspectieplan voor pompen','',conv='C2')]
        with tempfile.TemporaryDirectory() as td:
            root=self.prepare(td,rows)
            summary=audit_full(root,Gateway(rows),classify)
            self.assertEqual(3,summary['decisions']['SKIP_NOT_RELEVANT'])
            self.assertEqual(2,summary['distinct_plan_work_requests_current_inbox'])

    def test_existing_sent_and_unknown_untouched(self):
        rows = [message(0,'plan','Maak nieuw inspectieplan voor pompen'),
                message(1,'spare','Graag spare voor druktransmitter PT101')]
        with tempfile.TemporaryDirectory() as td:
            root=self.prepare(td,rows)
            db=sqlite3.connect(root/'agent.db')
            db.execute("UPDATE messages SET status='SENT',send_token='sent-token' WHERE entry_id='0'")
            db.execute("UPDATE messages SET status='UNKNOWN',send_token='unknown-token' WHERE entry_id='1'")
            db.commit();db.close()
            summary=audit_full(root,Gateway(rows),classify)
            self.assertEqual(1,summary['previously_submitted_forwards_in_current_inbox'])
            db=sqlite3.connect(root/'agent.db')
            states=dict(db.execute('SELECT entry_id,status FROM messages'))
            db.close()
            self.assertEqual({'0':'SENT','1':'UNKNOWN'},states)

    def test_duplicate_entryid_rejected_before_report(self):
        rows=[message(0,'a','text'),message(0,'b','text')]
        with tempfile.TemporaryDirectory() as td:
            root=self.prepare(td,rows)
            with self.assertRaisesRegex(RuntimeError,'Dubbele EntryIDs'):
                audit_full(root,Gateway(rows),classify)

    def test_individual_detail_error_report_not_complete(self):
        rows=[message(0,'a','text')]
        class BrokenGateway(Gateway):
            def detail(self,msg):
                raise OSError('Outlook mail temporarily moved')
        with tempfile.TemporaryDirectory() as td:
            root=self.prepare(td,rows)
            summary=audit_full(root,BrokenGateway(rows),classify)
            self.assertEqual(1,summary['failed_or_deferred_llm'])
            self.assertEqual(1,summary['decisions']['ERROR_REVIEW_REQUIRED'])
            self.assertFalse(summary['all_classifications_completed'])
            self.assertTrue((root/'mailbox_audits').is_dir())


if __name__ == '__main__':
    unittest.main()

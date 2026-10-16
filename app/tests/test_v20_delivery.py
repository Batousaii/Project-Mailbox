"""2.0 regressions: real SQLite, simulated Outlook; no actual email."""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_pipeline import FakeGateway
from agent.state import State
from agent.rules import Decision
from agent.runner import baseline,send_one,reconcile,daemon,configure_log,LOG
from agent.cli import activate
from agent import ai

class DeliveryV20(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.st=State(self.temp.name)
        self.gw=FakeGateway();baseline(self.st,self.gw)
        self.gw.add('test','EE-AGENT-TEST','Onschuldige testinhoud','Hamza')
        self.st.metadata(self.gw.messages[-1])
        self.st.classify('test','SEND_HAMZA',Decision(),False)
    def tearDown(self):
        self.st.close();self.temp.cleanup()
    def test_submission_not_sent_until_copy_confirmed(self):
        with patch.object(self.gw,'sent_copy_exists',return_value=False):
            self.assertTrue(send_one(self.st,self.gw,self.st.row('test')))
            self.assertEqual('SUBMITTED',self.st.row('test')['status'])
            self.assertIsNone(self.st.row('test')['sent_at'])
            self.assertEqual(0,reconcile(self.st,self.gw))
        self.assertEqual(1,reconcile(self.st,self.gw))
        self.assertEqual('SENT',self.st.row('test')['status'])
    def test_submitted_restart_never_resends(self):
        with patch.object(self.gw,'sent_copy_exists',return_value=False):
            send_one(self.st,self.gw,self.st.row('test'))
            self.st.close();self.st=State(self.temp.name)
            self.st.recover_interrupted_sends()
            self.assertEqual('SUBMITTED',self.st.row('test')['status'])
            self.assertFalse(send_one(self.st,self.gw,self.st.row('test')))
            self.assertEqual(1,len(self.gw.sent))
    def test_confirmation_failure_stays_unknown(self):
        with patch.object(self.gw,'sent_copy_exists',side_effect=OSError('COM lost')):
            self.assertFalse(send_one(self.st,self.gw,self.st.row('test')))
        self.assertEqual('UNKNOWN',self.st.row('test')['status'])
        self.assertFalse(send_one(self.st,self.gw,self.st.row('test')))
    def test_receipt_required_and_activation_can_resume_without_second_send(self):
        with patch('agent.cli.preflight',return_value={}),patch('agent.cli.status',return_value={'scheduler':'RUNNING'}),patch('agent.cli.OutlookGateway',return_value=self.gw),patch('agent.cli.scan'):
            with patch('builtins.input',side_effect=['TESTFORWARD GOEDGEKEURD','NIET ONTVANGEN']):
                with self.assertRaisesRegex(RuntimeError,'Ontvangst niet bevestigd'):
                    activate(self.st)
            self.assertEqual('0',self.st.setting('forward_enabled'))
            self.assertEqual(1,len(self.gw.sent))
            with patch('builtins.input',side_effect=['TESTFORWARD GOEDGEKEURD','TEST ONTVANGEN']):
                activate(self.st)
            self.assertEqual('1',self.st.setting('forward_enabled'))
            self.assertEqual(1,len(self.gw.sent))
    def test_csv_source_text_cannot_be_formula(self):
        self.st.db.execute("UPDATE messages SET subject='=HYPERLINK(1)' WHERE entry_id='test'");self.st.db.commit()
        self.st.export_reports()
        with (self.st.root/'mail_audit.csv').open(encoding='utf-8-sig') as f:
            row=next(csv.DictReader(f,delimiter=';'))
        self.assertEqual("'=HYPERLINK(1)",row['subject'])
    def test_monthly_report_keeps_unconfirmed_submission(self):
        with patch.object(self.gw,'sent_copy_exists',return_value=False):
            send_one(self.st,self.gw,self.st.row('test'))
        self.st.db.execute("UPDATE messages SET received='2000-01-01T00:00:00+00:00'");self.st.db.commit()
        self.assertEqual(1,self.st.monthly_open_report())
        reconcile(self.st,self.gw)
        self.assertEqual(0,self.st.monthly_open_report())
    def test_fsync_durability(self):
        self.assertEqual(2,self.st.db.execute('PRAGMA synchronous').fetchone()[0])
    def test_cooperative_stop_does_not_start_a_scan(self):
        self.st.close();self.st=State(self.temp.name)
        (self.st.root/'stop.request').touch()
        streams=[]
        def capture_log(root):
            configure_log(root)
            streams.extend(h.stream for h in LOG.handlers if getattr(h,'ee_agent_owned',False))
        with patch('agent.runner.State',side_effect=lambda root=None:State(self.temp.name)),patch('agent.runner.instance_mutex',return_value=None),patch('agent.runner.configure_log',side_effect=capture_log),patch('agent.runner.scan') as scan:
            daemon();scan.assert_not_called()
        self.assertTrue(streams,'Real log file must be opened for this regression')
        self.assertTrue(all(stream.closed for stream in streams),'Daemon must release log handles before returning')
        self.assertFalse(any(getattr(h,'ee_agent_owned',False) for h in LOG.handlers))
        self.assertFalse((self.st.root/'runtime.json').exists())
    def test_local_ollama_bypasses_external_proxy(self):
        with patch('agent.ai.urllib.request.ProxyHandler') as proxy,patch('agent.ai.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value=b'{"models":[]}'
            self.assertEqual({'models':[]},ai.request_json('/api/tags'))
            proxy.assert_called_once_with({})

if __name__=='__main__':unittest.main()

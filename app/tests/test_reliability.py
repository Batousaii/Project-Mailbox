import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from test_pipeline import FakeGateway, classifier
from agent import ai
from agent.rules import Decision, decide_forward, ground_decision
from agent.runner import baseline, scan, heartbeat_worker
from agent.state import State

class ReliabilityTests(unittest.TestCase):
    def test_ai_failure_does_not_starve_later_hamza_and_one_ai_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            st=State(td); gw=FakeGateway(); baseline(st,gw)
            st.set_setting('forward_enabled','1')
            gw.add('first','Sensor','Sensor bestellen')
            gw.add('second','Plan','Plan aanpassen','Hamza')
            gw.add('third','Sensor','Nog een sensor')
            with patch('agent.runner.ai.classify',side_effect=RuntimeError('offline')) as classify, patch('agent.runner.ai.release_model'):
                with self.assertRaisesRegex(RuntimeError,'unavailable'):
                    scan(st,gw)
                self.assertEqual(1,classify.call_count)
            self.assertEqual(['second'],[x[0] for x in gw.sent])
            self.assertEqual('NEW',st.row('first')['status'])
            self.assertEqual('NEW',st.row('third')['status'])
            with patch('agent.runner.ai.classify',side_effect=classifier),patch('agent.runner.ai.release_model'):
                scan(st,gw)
            self.assertEqual(1,len([x for x in gw.sent if x[0]=='second']))
            st.close()

    def test_release_even_after_failure_and_unchanged_messages_not_classified(self):
        with tempfile.TemporaryDirectory() as td:
            st=State(td);gw=FakeGateway();baseline(st,gw)
            gw.add('one','Sensor','Sensor bestellen')
            with patch('agent.runner.ai.classify',side_effect=classifier) as classify,patch('agent.runner.ai.release_model') as release:
                scan(st,gw,False);scan(st,gw,False)
                self.assertEqual(1,classify.call_count)
                self.assertEqual(2,release.call_count)
            st.close()

    def test_old_plan_queue_reclassified_without_touching_sent_or_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            st=State(td);gw=FakeGateway()
            for key in ['ready','sent','unknown']:
                gw.add(key,'Plan','Plan aanpassen')
                st.metadata(gw.messages[-1])
            st.db.execute("UPDATE messages SET status='READY',forward_decision='SEND_PLAN'")
            st.db.execute("UPDATE messages SET status='SENT',send_token='a' WHERE entry_id='sent'")
            st.db.execute("UPDATE messages SET status='UNKNOWN',send_token='b' WHERE entry_id='unknown'")
            st.db.commit();st.close();st=State(td)
            self.assertEqual('NEW',st.row('ready')['status'])
            self.assertEqual('SENT',st.row('sent')['status'])
            self.assertEqual('UNKNOWN',st.row('unknown')['status'])
            self.assertEqual([],st.ready());st.close()

    def test_plan_plus_false_ei_claim_does_not_forward_mechanical_plan(self):
        body='Wijzig het inspectieplan voor de lagers.'
        cls=Decision(True,'MODIFY_PLAN',True,.95,'plan',False,'lagers','PLAN',body)
        cls=ground_decision(cls,'E&I overleg',body)
        self.assertEqual('REVIEW_REQUIRED',decide_forward('',False,cls))
        body='Wijzig het inspectieplan en kalibreer de sensor.'
        cls=Decision(True,'MODIFY_PLAN',True,.95,'plan and EI',False,'sensor','PLAN',body)
        self.assertEqual('SEND_EI',decide_forward('',False,ground_decision(cls,'Plan',body)))

    def test_heartbeat_independent_of_main_thread_and_stops(self):
        with tempfile.TemporaryDirectory() as td:
            st=State(td);st.close();stop=threading.Event()
            worker=threading.Thread(target=heartbeat_worker,args=(Path(td),stop))
            # Observe a real file write rather than merely thread existence.
            original=__import__('agent.runner',fromlist=['heartbeat']).heartbeat
            written=threading.Event()
            def record(*args):
                original(*args);written.set()
            with patch('agent.runner.heartbeat',side_effect=record):
                worker.start()
                try:
                    self.assertTrue(written.wait(5))
                    self.assertIn('heartbeat',json.loads((Path(td)/'runtime.json').read_text()))
                finally:
                    stop.set();worker.join(5)
            self.assertFalse(worker.is_alive())

    def test_model_request_has_finite_residency(self):
        body='Graag sensor bestellen'
        response={'done':True,'response':json.dumps(dict(ei_relevant=True,work_requested=False,plan_type='NONE',domain='EI',evidence=body,confidence=.95,review_required=False))}
        with patch('agent.ai.request_json',return_value=response) as req:
            ai.classify('Sensor',body,'')
            self.assertEqual('30s',req.call_args.args[1]['keep_alive'])
            ai.release_model()
            self.assertEqual(0,req.call_args.args[1]['keep_alive'])

    def test_unknown_send_not_retried_after_restart(self):
        with tempfile.TemporaryDirectory() as td:
            st=State(td);gw=FakeGateway();baseline(st,gw)
            st.set_setting('forward_enabled','1');gw.add('one','Hamza','Mail','Hamza')
            def ambiguous(*args):
                gw.sent.append(args)
                raise RuntimeError('Disconnected after submission')
            with patch('agent.runner.ai.classify',side_effect=classifier),patch('agent.runner.ai.release_model'),patch.object(gw,'forward',side_effect=ambiguous):
                scan(st,gw)
            self.assertEqual('UNKNOWN',st.row('one')['status'])
            st.close();st=State(td)
            with patch('agent.runner.ai.classify',side_effect=classifier),patch('agent.runner.ai.release_model'),patch.object(gw,'forward') as forward:
                scan(st,gw)
                forward.assert_not_called()
            self.assertEqual('UNKNOWN',st.row('one')['status']);st.close()

    def test_nonconnection_error_does_not_start_or_retry_ollama(self):
        import urllib.error
        failure=urllib.error.HTTPError('http://localhost',500,'failure',{},None)
        with patch('agent.ai.request_json',side_effect=failure),patch('agent.ai.ensure_server') as ensure:
            with self.assertRaises(urllib.error.HTTPError):
                ai.generate({})
            ensure.assert_not_called()

    def test_connection_refusal_recovers_then_retries_once(self):
        import urllib.error
        failure=urllib.error.URLError(ConnectionRefusedError('offline'))
        with patch('agent.ai.request_json',side_effect=[failure,{'done':True}]) as request,patch('agent.ai.ensure_server') as ensure:
            self.assertTrue(ai.generate({})['done'])
            ensure.assert_called_once();self.assertEqual(2,request.call_count)

    def test_late_hamza_overrides_review_without_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            st=State(td);gw=FakeGateway();baseline(st,gw);st.set_setting('forward_enabled','1')
            gw.add('one','Unclear','Unclear mail')
            with patch('agent.runner.ai.classify',return_value=Decision(review_required=True)),patch('agent.runner.ai.release_model'):
                scan(st,gw)
                self.assertEqual('REVIEW_REQUIRED',st.row('one')['status'])
                gw.messages[0]['categories']='Hamza'
                scan(st,gw);scan(st,gw)
            self.assertEqual(1,len(gw.sent));st.close()

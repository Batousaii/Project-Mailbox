import tempfile
import unittest
from unittest.mock import patch
from test_pipeline import FakeGateway
from agent.runner import baseline,scan
from agent.state import State
from agent.rules import Decision,completed_notice,decide_forward,decode_classification,ground_decision,split_latest_message

class CompletionTests(unittest.TestCase):
    def test_completed_even_with_hamza_no_ai_send_or_work_item(self):
        for categories in ['', 'Hamza']:
            with self.subTest(categories=categories),tempfile.TemporaryDirectory() as td:
                st=State(td);gw=FakeGateway();baseline(st,gw);st.set_setting('forward_enabled','1')
                gw.add('done','RE: Roostervloeren','Het werk aan de roostervloeren is uitgevoerd zoals afgesproken.',categories)
                with patch('agent.runner.ai.classify') as model,patch('agent.runner.ai.release_model'):
                    scan(st,gw);scan(st,gw)
                    model.assert_not_called()
                self.assertEqual([],gw.sent)
                self.assertEqual('SUPPRESS_COMPLETED',st.row('done')['forward_decision'])
                self.assertEqual('COMPLETED',st.row('done')['message_intent'])
                self.assertEqual(0,st.db.execute('SELECT COUNT(*) FROM work_items').fetchone()[0]);st.close()

    def test_completed_with_new_action_not_suppressed(self):
        for body in ['Het werk is afgerond. Graag de sensor kalibreren.',
                     'The job was completed. Please update the inspection plan.',
                     'Het werk is uitgevoerd. Maak een nieuw inspectieplan.',
                     'Het werk is uitgevoerd, vervang de sensor.',
                     'Het werk is nog niet uitgevoerd.', 'Is het werk uitgevoerd?']:
            with self.subTest(body=body):self.assertIsNone(completed_notice(body))
        body='Het werk is afgerond. Graag de sensor kalibreren.'
        cls=Decision(True,'NONE',False,.95,'Nieuwe actie',False,'','EI','de sensor kalibreren','ACTION_REQUIRED','Graag de sensor kalibreren')
        self.assertEqual('SEND_EI',decide_forward('',False,ground_decision(cls,'Roostervloeren',body)))

    def test_quoted_old_request_does_not_reopen_done_work(self):
        latest,_=split_latest_message('Het werk is uitgevoerd.\n\nFrom: A\nSent: yesterday\nGraag inspectieplan opzetten.')
        self.assertIsNotNone(completed_notice(latest))

    def test_model_status_only_with_literal_evidence_no_hamza_forward(self):
        body='Ter informatie: de inspectieronde verliep volgens planning.'
        raw=dict(ei_relevant=False,work_requested=False,plan_type='NONE',domain='OTHER',confidence=.95,review_required=False,message_intent='STATUS_ONLY',intent_evidence=body)
        cls=ground_decision(decode_classification(raw),'Inspectie',body)
        self.assertEqual('SUPPRESS_STATUS_ONLY',decide_forward('Hamza',False,cls))
        raw['intent_evidence']='Werk uit oude mail is uitgevoerd'
        cls=ground_decision(decode_classification(raw),'Inspectie',body)
        self.assertEqual('REVIEW_REQUIRED',decide_forward('Hamza',False,cls))

    def test_completed_claim_with_direct_new_request_requires_review(self):
        body='Het werk is uitgevoerd. Vervang de sensor.'
        cls=Decision(confidence=.95,message_intent='COMPLETED',intent_evidence='Het werk is uitgevoerd.')
        cls=ground_decision(cls,'Werk',body)
        self.assertEqual('REVIEW_REQUIRED',decide_forward('Hamza',False,cls))

    def test_completed_pending_hamza_is_removed_from_send_queue(self):
        with tempfile.TemporaryDirectory() as td:
            st=State(td);gw=FakeGateway();baseline(st,gw);st.set_setting('forward_enabled','1')
            gw.add('pending','Werk','Het werk is uitgevoerd.','Hamza')
            st.metadata(gw.messages[0])
            st.classify('pending','SEND_HAMZA',Decision(review_required=True),False,plan_pending=True)
            with patch('agent.runner.ai.classify') as model,patch('agent.runner.ai.release_model'):
                scan(st,gw)
                model.assert_not_called()
            self.assertEqual([],gw.sent)
            self.assertEqual('SKIPPED',st.row('pending')['status']);st.close()

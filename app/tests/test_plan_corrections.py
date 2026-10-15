import json
import tempfile
import unittest
from unittest.mock import patch
from test_pipeline import FakeGateway
from agent import ai
from agent.rules import Decision,ground_decision,plan_review_candidate
from agent.runner import baseline,scan
from agent.state import State

class CorrectionTests(unittest.TestCase):
    def test_implicit_frequency_correction_requires_model_and_literal_evidence(self):
        subject='Correctie maintenance item tekst'
        latest='PO plan zonder periodiciteit in maintenance item, denk 6M'
        self.assertTrue(plan_review_candidate(subject,latest))
        cls=Decision(False,'MODIFY_PLAN',True,.9,'Corrigeer interval',False,'maintenance item','PLAN',latest)
        self.assertFalse(ground_decision(cls,subject,latest).review_required)
        self.assertTrue(ground_decision(cls,subject,'Ter info: een onderhoudsplan bestaat.').review_required)

    def test_bounded_semantic_retry_for_false_negative(self):
        latest='Gelieve PO plan 4321 aan te passen; regel 3 mag eruit.'
        negative=dict(ei_relevant=False,work_requested=False,plan_type='NONE',domain='MECHANICAL',confidence=.95,review_required=False)
        positive=dict(ei_relevant=False,work_requested=True,plan_type='MODIFY_PLAN',domain='PLAN',confidence=.95,review_required=False,evidence=latest)
        responses=[{'done':True,'response':json.dumps(x)} for x in [negative,positive]]
        with patch('agent.ai.generate',side_effect=responses) as generate:
            result=ai.classify('PO-plan',latest,'')
            self.assertTrue(result.work_requested)
            self.assertEqual('MODIFY_PLAN',result.plan_type)
            self.assertEqual(2,generate.call_count)

    def test_status_or_completed_does_not_trigger_second_call(self):
        latest='Het maintenance item is aangepast.'
        negative=dict(ei_relevant=False,work_requested=False,plan_type='NONE',domain='OTHER',confidence=.95,review_required=False,message_intent='COMPLETED',intent_evidence=latest)
        with patch('agent.ai.generate',return_value={'done':True,'response':json.dumps(negative)}) as generate:
            ai.classify('Correctie maintenance item tekst',latest,'')
            self.assertEqual(1,generate.call_count)

    def test_old_review_reassessed_once_into_workitem_without_catchup_send(self):
        with tempfile.TemporaryDirectory() as td:
            st=State(td);gw=FakeGateway();baseline(st,gw);st.set_setting('forward_enabled','1')
            body='PO plan zonder periodiciteit in maintenance item, denk 6M'
            gw.add('review','Correctie maintenance item tekst',body)
            st.metadata(gw.messages[0])
            st.classify('review','REVIEW_REQUIRED',Decision(review_required=True,evidence=body),False)
            positive=Decision(False,'MODIFY_PLAN',True,.9,'Corrigeer periodiciteit',False,'item','PLAN',body)
            with patch('agent.runner.ai.classify',return_value=positive) as classify,patch('agent.runner.ai.release_model'):
                scan(st,gw);scan(st,gw)
                self.assertEqual(1,classify.call_count)
            self.assertEqual([],gw.sent)
            self.assertEqual(1,st.db.execute('SELECT COUNT(*) FROM work_items').fetchone()[0])
            st.close()

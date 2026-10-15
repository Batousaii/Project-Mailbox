import json
import tempfile
import unittest
from unittest.mock import patch
from test_pipeline import FakeGateway
from agent import ai
from agent.rules import decode_classification,ground_decision,decide_forward
from agent.runner import baseline,scan
from agent.state import State

class ScopeTests(unittest.TestCase):
    def decision(self,body,intent):
        return decode_classification(dict(ei_relevant=False,work_requested=False,plan_type='NONE',domain='PLAN',confidence=.95,review_required=False,message_intent=intent,intent_evidence=body))

    def test_future_other_owner_is_not_active_work_or_forward_even_hamza(self):
        body='Zodra de leverancier meetresultaten heeft, kan hun team later een onderhoudsplan opmaken.'
        for intent in ['DEFERRED','OUT_OF_SCOPE']:
            with self.subTest(intent=intent),tempfile.TemporaryDirectory() as td:
                st=State(td);gw=FakeGateway();baseline(st,gw);st.set_setting('forward_enabled','1')
                gw.add('future','Toekomstig plan',body,'Hamza')
                cls=ground_decision(self.decision(body,intent),'Toekomstig plan',body)
                with patch('agent.runner.ai.classify',return_value=cls),patch('agent.runner.ai.release_model'):
                    scan(st,gw)
                self.assertEqual([],gw.sent)
                self.assertEqual(0,st.db.execute('SELECT COUNT(*) FROM work_items').fetchone()[0])
                self.assertEqual('SUPPRESS_'+intent,st.row('future')['forward_decision']);st.close()

    def test_unfounded_future_claim_requires_review(self):
        cls=self.decision('Zodra de leverancier meetresultaten heeft.','DEFERRED')
        cls=ground_decision(cls,'Plan','Graag nu een nieuw onderhoudsplan maken.')
        self.assertEqual('REVIEW_REQUIRED',decide_forward('Hamza',False,cls))

    def test_deferred_answer_does_not_trigger_plan_retry(self):
        body='Zodra de leverancier de meting heeft, kan hun team later een plan opmaken.'
        cls=self.decision(body,'DEFERRED')
        response=dict(ei_relevant=False,work_requested=False,plan_type='NONE',domain='PLAN',confidence=.95,review_required=False,message_intent='DEFERRED',intent_evidence=body)
        with patch('agent.ai.generate',return_value={'done':True,'response':json.dumps(response)}) as model:
            self.assertEqual('DEFERRED',ai.classify('Onderhoudsplan',body,'').message_intent)
            self.assertEqual(1,model.call_count)

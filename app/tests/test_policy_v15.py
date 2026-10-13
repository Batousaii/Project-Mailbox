import tempfile
import unittest
from unittest.mock import patch
from agent import ai
from agent.rules import (Decision, decode_classification, ground_decision,
                         decide_forward, split_latest_message, has_hamza_category)
from agent.state import State
from agent.runner import baseline, scan


def model(domain, evidence, ei=False, typ='NONE', conf=.95, review=False):
    return decode_classification({
        'ei_relevant':ei,'work_requested':typ!='NONE','plan_type':typ,
        'plan_target':'PO 1026' if typ != 'NONE' else '',
        'domain':domain,'evidence':evidence,'confidence':conf,
        'reason':'Expliete actie uit nieuwste bericht','review_required':review})

class PolicyTests(unittest.TestCase):
    def test_mechanical_spares_never_forward_without_ei(self):
        for subject, body in [
            ('M1291: lager 22311EMD1','Graag een nieuw magazijnartikel voor lager 22311EMD1'),
            ('Re: GBX MAAG','Aanvraag voor nieuwe tandwielkast'),
            ('Aanmaak artikel vlotter stoomtrap','Maak een artikel voor stoomtrap vlotter'),
            ('Cutters lijn 1','Spare bedmeshouder voor cutter')]:
            with self.subTest(subject=subject):
                cls=ground_decision(model('EI',body,ei=True),subject,body)
                self.assertTrue(cls.review_required)
                self.assertEqual('REVIEW_REQUIRED',decide_forward('',False,cls))

    def test_ei_spare_requested(self):
        body='Graag spare parts voor Endress+Hauser druktransmitter PT-1001.'
        cls=ground_decision(model('EI','spare parts voor Endress+Hauser druktransmitter PT-1001',ei=True), 'Spare parts PT', body)
        self.assertEqual('SEND_EI',decide_forward('',False,cls))

    def test_hamza_category_overrides_mechanical(self):
        self.assertTrue(has_hamza_category('Mechanical; HAMZA; E&I'))
        self.assertEqual('SEND_HAMZA',decide_forward('Mechanical;HAMZA',False,model('MECHANICAL','',conf=.20,review=True)))
        self.assertEqual('SUPPRESS_SYSTEM_HAMZA',decide_forward('HAMZA',True,model('MECHANICAL','')))

    def test_plan_both_subtypes_include_mechanical_plans(self):
        for body,typ in [
            ('Kan je een nieuw inspectieplan opzetten voor de lagers?', 'CREATE_PLAN'),
            ('Wijzig het bestaande PO-plan 4270 voor de lagers.', 'MODIFY_PLAN'),
            ('Graag nieuw onderhoudsplan voor gearbox maken.', 'CREATE_PLAN'),
            ('Bestaand inspectieplan graag aanpassen.', 'MODIFY_PLAN')]:
            cls=ground_decision(model('PLAN',body,typ=typ), 'Verzoek plan',body)
            with self.subTest(body=body):
                self.assertEqual('SKIP_NOT_RELEVANT',decide_forward('',False,cls))

    def test_article_request_is_not_plan(self):
        body='Graag aanvraag nieuw magazijnartikel voor lager M1291'
        cls=ground_decision(model('PLAN',body,typ='CREATE_PLAN'), 'Aanvraag artikel',body)
        self.assertEqual('REVIEW_REQUIRED',decide_forward('',False,cls))

    def test_plan_subject_does_not_make_a_reply_action(self):
        body='Bedankt, ter info en geen actie nodig.\n\nFrom: Jan\nSent: gisteren\nSubject: PO-plan 1026\nPas dit plan aan!'
        latest,context=split_latest_message(body)
        cls=ground_decision(model('PLAN','Bedankt, ter info en geen actie nodig.',typ='MODIFY_PLAN'), 'RE: PO-plan 1026',latest)
        self.assertEqual('REVIEW_REQUIRED',decide_forward('',False,cls))
        self.assertIn('Pas dit plan aan!',context)

    def test_uncited_evidence_and_80_percent_rejected(self):
        body='Maak een nieuw inspectieplan voor vloer 12.'
        cls=ground_decision(model('PLAN','een artikel aanmaken',typ='CREATE_PLAN'),'Inspectieplan',body)
        self.assertTrue(cls.review_required)
        cls=ground_decision(model('PLAN',body,typ='CREATE_PLAN',conf=.80),'Inspectieplan',body)
        self.assertEqual('REVIEW_REQUIRED',decide_forward('',False,cls))

    def test_strange_response_requires_review(self):
        self.assertTrue(decode_classification({'ei_relevant':True, 'work_requested':False,
            'plan_type':'NONE','domain':'EI','confidence':.95}).review_required)

    def test_actual_ai_parsing_has_evidence_guards(self):
        payload = lambda domain, evidence, ei, typ: {
            'done':True, 'response':__import__('json').dumps({
                'ei_relevant':ei, 'work_requested':typ!='NONE', 'plan_type':typ,
                'plan_target':'', 'domain':domain, 'evidence':evidence,
                'confidence':.95, 'review_required':False, 'reason':'AI classification'})}
        with patch('agent.ai.request_json',return_value=payload('EI','Graag lager 22311 bestellen',True,'NONE')):
            cls=ai.classify('Mechanische onderdelen','Graag lager 22311 bestellen','')
            self.assertEqual('REVIEW_REQUIRED',decide_forward('',False,cls))
        with patch('agent.ai.request_json',return_value=payload('EI','Graag sensor PT-1144 bestellen',True,'NONE')):
            cls=ai.classify('PT spare','Graag sensor PT-1144 bestellen','')
            self.assertEqual('SEND_EI',decide_forward('',False,cls))
        with patch('agent.ai.request_json',return_value=payload('PLAN','Maak een nieuw artikel voor een lager',False,'CREATE_PLAN')):
            cls=ai.classify('Magazijn artikel', 'Maak een nieuw artikel voor een lager','')
            self.assertEqual('REVIEW_REQUIRED',decide_forward('',False,cls))

    def test_state_plan_sending_and_dedup(self):
        class Gw:
            def __init__(self): self.sent=[]
            def snapshot(self):return list(self.rows)
            def mailbox_info(self):return {'store':'EE-Reliability'}
            def detail(self,m):return {'body':m['body'],'headers':'','message_class':'IPM.Note','categories':m['categories']}
            def forward(self,e,s,to,t):self.sent.append(e)
        with tempfile.TemporaryDirectory() as tmp:
            st=State(tmp)
            gw=Gw()
            gw.rows=[]
            self.assertEqual(0,baseline(st,gw))
            st.set_setting('forward_enabled','1')
            for idx,body in enumerate(['Maak nieuw PO-plan 2222 aan.','Wijzig bestaand PO-plan 3333.']):
                gw.rows.append({'entry_id':str(idx),'store_id':'s','conversation_id':str(idx),
                 'group_fallback':str(idx),'received':'2026-10-08T08:00:00+00:00',
                 'subject':'PO-plan', 'categories':'','body':body})
            with patch('agent.runner.ai.classify',side_effect=lambda sub,latest,ctx: model('PLAN',latest,typ='MODIFY_PLAN' if 'Wijzig' in latest else 'CREATE_PLAN')):
                self.assertEqual(0,scan(st,gw)['sent'])
                self.assertEqual(0,scan(st,gw)['sent'])
            self.assertEqual([],gw.sent)
            self.assertEqual(2, st.db.execute('SELECT COUNT(*) FROM work_items').fetchone()[0])
            st.close()

if __name__=='__main__':unittest.main()

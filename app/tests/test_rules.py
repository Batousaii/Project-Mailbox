import unittest
from agent.rules import (
    Decision, canonical_subject, decide_forward, decode_classification,
    has_hamza_category, is_system_message, split_latest_message,
)

class RuleTests(unittest.TestCase):
    def test_hamza_exact_case_and_separators(self):
        for value in ['Hamza','HAMZA','Web; hamza; Plant','Web,haMzA,Extra']:
            self.assertTrue(has_hamza_category(value))
        for value in ['', 'Hamzalo', 'Hamza-extra', 'TeamHamza']:
            self.assertFalse(has_hamza_category(value))

    def test_system_mail_even_when_hamza(self):
        cls = Decision(ei_relevant=True, confidence=0.95)
        self.assertEqual('SUPPRESS_SYSTEM_HAMZA',decide_forward('Hamza', True, cls))
        self.assertTrue(is_system_message('Automatic reply: test','','','I am away'))
        self.assertTrue(is_system_message('Hi','REPORT.IPM.Note.NDR','','test'))
        self.assertTrue(is_system_message('Hello','','Auto-Submitted: auto-replied','test'))
        self.assertTrue(is_system_message('Hello','','','   '))

    def test_hamza_overrides_classification(self):
        cls = Decision(ei_relevant=False,confidence=0.99)
        self.assertEqual('SEND_HAMZA',decide_forward('x;hAMza',False,cls))

    def test_ei_and_non_ei(self):
        self.assertEqual('SEND_EI',decide_forward('',False,Decision(ei_relevant=True,confidence=.9,domain='EI',evidence='sensor')))
        self.assertEqual('SKIP_NOT_RELEVANT',decide_forward('',False,Decision(ei_relevant=False,confidence=.9)))
        self.assertEqual('REVIEW_REQUIRED',decide_forward('',False,Decision(ei_relevant=True,confidence=.6,review_required=True)))

    def test_newest_part_excludes_quoted_request(self):
        body = 'Ter info, geen actie nodig.\r\n\r\nFrom: A\r\nSent: gisteren\r\nSubject: PO-plan\r\nWijzig PO plan 1026!'
        latest, context = split_latest_message(body)
        self.assertNotIn('Wijzig PO plan',latest)
        self.assertIn('Wijzig PO plan',context)

    def test_reply_with_new_request_kept(self):
        body = 'Kun je het bestaande inspectieplan aanpassen?\n\nFrom: A\nSent: now\nOld text'
        latest, _ = split_latest_message(body)
        self.assertIn('aanpassen',latest)
        self.assertEqual('plan 1026', canonical_subject('RE: FW: AW: Plan 1026'))

    def test_four_plan_subtypes_equal_confidence(self):
        scenarios = [('new inspection','CREATE_PLAN'),('new PO','CREATE_PLAN'),
                     ('modify inspection','MODIFY_PLAN'),('modify PO','MODIFY_PLAN')]
        for label,typ in scenarios:
            with self.subTest(label=label):
                cls=decode_classification({'ei_relevant':False,'work_requested':True,
                   'plan_type':typ,'plan_target':label,'confidence':.93,'domain':'PLAN','evidence':'Please set up inspection plan',
                   'review_required':False,'reason':'explicit request'})
                self.assertTrue(cls.work_requested)
                self.assertEqual(typ,cls.plan_type)
                self.assertFalse(cls.review_required)
                self.assertEqual('SKIP_NOT_RELEVANT', decide_forward('',False,cls))

    def test_plan_status_no_action(self):
        cls=decode_classification({'ei_relevant':False,'work_requested':False,
                'plan_type':'NONE','confidence':.92,'review_required':False,
                'reason':'status only'})
        self.assertFalse(cls.work_requested)

    def test_bad_model_decision_safe(self):
        for value in ['garbage','{}','{"ei_relevant": true}','{"ei_relevant": "true"}']:
            with self.subTest(value=value):
                self.assertTrue(decode_classification(value).review_required)

if __name__ == '__main__':unittest.main()

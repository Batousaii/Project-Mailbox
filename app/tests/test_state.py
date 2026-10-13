import tempfile
import unittest
from agent.state import State
from agent.rules import Decision

class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.st=State(self.temp.name)
        self.msg={'entry_id':'abc','store_id':'store','conversation_id':'thread1',
                  'group_fallback':'fallback','received':'2026-10-08T08:00:00+00:00',
                  'subject':'RE: PO plan 1026','categories':'Hamza'}
    def tearDown(self):
        self.st.close();self.temp.cleanup()

    def test_historical_mail_immutable(self):
        self.st.metadata(self.msg,historical=True)
        self.st.metadata(self.msg,historical=False)
        self.assertEqual('HISTORICAL_IGNORE',self.st.row('abc')['status'])
        self.assertFalse(self.st.reserve_send('abc','one'))

    def test_single_send_dedup_even_after_restart(self):
        self.st.metadata(self.msg)
        cls=Decision(ei_relevant=True,confidence=.95)
        self.st.classify('abc','SEND_HAMZA',cls,False)
        self.assertTrue(self.st.reserve_send('abc','unique-token'))
        self.assertFalse(self.st.reserve_send('abc','another-token'))
        self.st.close()
        self.st=State(self.temp.name)
        self.assertEqual(1,self.st.recover_interrupted_sends())
        self.assertEqual('UNKNOWN',self.st.row('abc')['status'])
        self.assertFalse(self.st.reserve_send('abc','another-token'))
        self.st.sent('abc','unique-token')
        self.assertEqual('SENT',self.st.row('abc')['status'])

    def test_work_items_group_by_thread_and_plan_target(self):
        self.st.metadata(self.msg)
        cls=Decision(False,'MODIFY_PLAN',True,.94,'change plan',False,'PO 1026')
        self.st.add_work_item(self.msg,cls,'wijzigen')
        new=dict(self.msg,entry_id='def')
        self.st.metadata(new)
        self.st.add_work_item(new,cls,'opnieuw wijzigen')
        self.assertEqual(1,self.st.db.execute('SELECT COUNT(*) FROM work_items').fetchone()[0])
        self.assertEqual('def',self.st.db.execute('SELECT last_entry_id FROM work_items').fetchone()[0])

    def test_reports_and_backup(self):
        self.st.metadata(self.msg,historical=True)
        self.st.export_reports()
        self.assertTrue((self.st.root/'mail_audit.csv').is_file())
        self.assertTrue((self.st.root/'work_items.csv').is_file())
        self.assertTrue((self.st.root/'plan_requests.csv').is_file())
        import os
        self.assertTrue(os.path.isfile(self.st.backup()))

if __name__=='__main__':unittest.main()

import tempfile
import unittest
from unittest.mock import patch
from agent.state import State
from agent.rules import Decision
from agent.runner import baseline, scan

class FakeGateway:
    def __init__(self):
        self.messages=[]
        self.bodies={}
        self.sent=[]
    def mailbox_info(self):
        return {'store':'EE-Reliability'}
    def snapshot(self):
        return list(self.messages)
    def detail(self,msg):
        return {'body':self.bodies[msg['entry_id']], 'headers':'',
                'message_class':'IPM.Note','categories':msg['categories']}
    def forward(self,entry_id,store_id,to_address,token):
        self.sent.append((entry_id,to_address,token))
    def sent_copy_exists(self,token):
        return any(x[2] == token for x in self.sent)
    def add(self,key,subject,body,category='',thread=None):
        self.messages.append({'entry_id':key,'store_id':'store','conversation_id':thread or key,
             'group_fallback':'fallback:'+subject,'received':'2026-10-08T08:00:00+00:00',
             'subject':subject,'categories':category})
        self.bodies[key]=body

def classifier(subject,latest,context):
    low=latest.lower()
    if 'instrumentatie' in low or 'sensor' in low:
        return Decision(True,'NONE',False,.95,'E&I spare parts',False,'','EI',latest)
    if 'opzetten' in low:
        return Decision(False,'CREATE_PLAN',True,.93,'new plan',False,'PO 1026','PLAN',latest)
    if 'aanpassen' in low:
        return Decision(False,'MODIFY_PLAN',True,.92,'modify plan',False,'PO 1026','PLAN',latest)
    return Decision(False,'NONE',False,.94,'no E&I/work action',False,'')

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.st=State(self.temp.name)
        self.gw=FakeGateway()
        self.gw.add('history','Inspectieplan opzetten Roostervloeren','Plan graag opzetten','Hamza')
        self.assertEqual(1,baseline(self.st,self.gw))
        self.st.set_setting('forward_enabled','1')
    def tearDown(self):
        self.st.close()
        self.temp.cleanup()

    def test_real_pipeline_rules_with_fake_ai_and_outlook(self):
        self.gw.add('h','Mechanical','lager vervangen','Hamza')
        self.gw.add('e','RE: Spare parts','Spare parts voor instrumentatie nodig')
        self.gw.add('m','Mechanical','Mechanische schroeven stuk')
        self.gw.add('p1','PO plan 1026','Graag PO plan 1026 opzetten',thread='PO thread')
        self.gw.add('p2','RE: PO plan 1026','Bestaand PO plan 1026 aanpassen',thread='PO thread')
        self.gw.add('oldquote','RE: PO plan 1026','Ter info. Geen actie nodig.\n\nFrom: A\nSent: Yesterday\nPO-plan opzetten')
        self.gw.add('auto','Automatic reply: hello','Out of office','Hamza')
        with patch('agent.runner.ai.classify',side_effect=classifier):
            result=scan(self.st,self.gw)
        self.assertEqual(7,result['new'])
        self.assertEqual({'h','e'},{x[0] for x in self.gw.sent})
        self.assertEqual('HISTORICAL_IGNORE',self.st.row('history')['status'])
        self.assertEqual('SKIPPED',self.st.row('auto')['status'])
        work=[(x[0],x[1]) for x in self.st.db.execute('SELECT plan_type,plan_target FROM work_items')]
        self.assertEqual(2,len(work))
        self.assertEqual({'CREATE_PLAN','MODIFY_PLAN'},{x[0] for x in work})
        with patch('agent.runner.ai.classify',side_effect=classifier):
            scan(self.st,self.gw)
        self.assertEqual(2,len(self.gw.sent),'Repeated scan must not resend anything')

    def test_hamza_forwards_during_ai_outage_then_plan_work_recovers(self):
        self.gw.add('offline','RE: PO plan','Pas dit bestaande PO-plan 1026 aanpassen','HAMZA')
        with patch('agent.runner.ai.classify',side_effect=RuntimeError('Ollama offline')):
            scan(self.st,self.gw)
        self.assertEqual('SENT',self.st.row('offline')['status'])
        self.assertEqual(1,self.st.row('offline')['plan_pending'])
        self.assertEqual(1,len(self.gw.sent))
        with patch('agent.runner.ai.classify',side_effect=classifier):
            scan(self.st,self.gw)
        self.assertEqual(0,self.st.row('offline')['plan_pending'])
        self.assertEqual(1,self.st.db.execute('SELECT COUNT(*) FROM work_items').fetchone()[0])
        self.assertEqual(1,len(self.gw.sent))

    def test_hamza_category_applied_after_initial_classification(self):
        self.gw.add('latecat','Afspraak','vergadering')
        with patch('agent.runner.ai.classify',side_effect=classifier):
            scan(self.st,self.gw)
        self.assertEqual('SKIPPED',self.st.row('latecat')['status'])
        self.gw.messages[-1]['categories']='Hamza; Overig'
        with patch('agent.runner.ai.classify',side_effect=classifier):
            scan(self.st,self.gw)
        self.assertEqual('SENT',self.st.row('latecat')['status'])
        self.assertEqual(1,len(self.gw.sent))

if __name__=='__main__': unittest.main()

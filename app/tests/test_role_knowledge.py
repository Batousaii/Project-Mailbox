import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agent import ai,role_eval
from agent.role_knowledge import load,matches,context_for,supports_plan
from agent.rules import Decision,ground_decision

class KnowledgeTests(unittest.TestCase):
    def test_graph_has_valid_relations_and_aliases(self):
        data=load();ids={c['id'] for c in data['concepts']}
        self.assertGreaterEqual(len(ids),18)
        for c in data['concepts']:
            self.assertTrue(set(c['related']) <= ids)
            for alias in c['aliases']:
                self.assertIn(c['id'],{x['id'] for x,_ in matches(alias)})

    def test_item_retrieves_plan_and_frequency_relations_with_bounded_context(self):
        text=context_for('Correctie maintenance item','Periodiciteit ontbreekt; denk 6M.')
        self.assertIn('MAINTENANCE_ITEM',text)
        self.assertIn('MAINTENANCE_PLAN',text)
        self.assertIn('CYCLE',text)
        self.assertLessEqual(len(text),4200)

    def test_generic_item_procurement_or_bom_is_not_a_plan(self):
        for text in ['Please order this item','purchase order 123','Mechanische stuklijst aanpassen','generic strategy']:
            with self.subTest(text=text):self.assertFalse(supports_plan(text))

    def test_tasklist_and_strategy_requests_have_grounded_plan_scope(self):
        for body in ['Wijzig de onderhoudstaaklijst voor de pomp.',
                     'Change the maintenance strategy package from 6M to 12M.']:
            cls=Decision(False,'MODIFY_PLAN',True,.95,'Planconfiguratie',False,'item','PLAN',body)
            self.assertFalse(ground_decision(cls,'Onderhoud',body).review_required)

    def test_actual_model_request_receives_domain_relations(self):
        body='Periodicity missing in maintenance item; suggest 6M.'
        payload=dict(ei_relevant=False,work_requested=True,plan_type='MODIFY_PLAN',domain='PLAN',confidence=.95,review_required=False,evidence=body)
        with patch('agent.ai.generate',return_value={'done':True,'response':json.dumps(payload)}) as generate:
            ai.classify('Correction maintenance item',body,'')
            self.assertIn('MAINTENANCE_PLAN',generate.call_args.args[0]['system'])
            self.assertIn('MAINTENANCE_ITEM',generate.call_args.args[0]['system'])

class EvaluationTests(unittest.TestCase):
    def setUp(self):
        output=patch('agent.role_eval.print',create=True)
        output.start()
        self.addCleanup(output.stop)

    def test_failure_is_reported_and_blocks_acceptance(self):
        with tempfile.TemporaryDirectory() as td,patch('agent.role_eval.model_digest',return_value='fake-digest'),patch('agent.role_eval.ai.classify',return_value=Decision()),patch('agent.role_eval.ai.release_model'):
            output=Path(td)/'evaluation.json'
            self.assertEqual(2,role_eval.run(output))
            report=json.loads(output.read_text())
            self.assertGreater(report['failed'],0)
            self.assertEqual(len(role_eval.CASES),len(report['results']))
            self.assertEqual(sum(case[3] for case in role_eval.CASES),report['missed_forwards'])
            self.assertEqual(sum(case[4]!='NONE' for case in role_eval.CASES),report['missed_work_items'])

    def test_identical_passed_report_reused_but_changed_model_is_tested(self):
        with tempfile.TemporaryDirectory() as td,patch('agent.role_eval.model_digest',return_value='same'),patch('agent.role_eval.ai.classify',return_value=Decision()) as classify,patch('agent.role_eval.ai.release_model'):
            output=Path(td)/'evaluation.json'
            output.write_text(json.dumps(dict(signature=role_eval.signature(),model_digest='same',passed=len(role_eval.CASES),failed=0)))
            self.assertEqual(0,role_eval.run(output));classify.assert_not_called()
            with patch('agent.role_eval.model_digest',return_value='changed'):
                self.assertEqual(2,role_eval.run(output))
            self.assertEqual(len(role_eval.CASES),classify.call_count)

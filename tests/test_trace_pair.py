"""Tests for the downstream FiF result/detail pair checker (synthetic only)."""
import json
import tempfile
import unittest
from pathlib import Path

from tests.test_auditor import detail, step, usage # reuse existing schema-faithful fixture factories
from validate_trace_pair import verify_pair


class SavedPairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.detail_path = self.root / 'details' / '1.json'
        self.detail_path.parent.mkdir()
        self.jsonl_path = self.root / 'fif.jsonl'

    def make_pair(self, dids=None, rids=None, qid='q-one', other_qid=None, result_usage=None):
        dids = dids if dids is not None else [('docA','1'),('docB','2')]
        rids = rids if rids is not None else list(dids)
        def selected(ids): return [[[a,b],float(i+1)] for i,(a,b) in enumerate(ids)]
        payload = {'qid':qid,'question':'synthetic only','retrieved_nids':selected(dids),
                   'agent_usage':{'orchestrator': {'llm_calls':1}},
                   'memory':{'tool_usage':[{'action_decisions':[],
                      'retrieval_subtask': {'predicted_subtasks': [], 'time': usage()['time'], 'api_usage':usage()['api_usage']},
                      'retrieval_result':{'subquery_task':'test','final_status':'not answerable',
                       'candidate_result':{'mode':'vector search',**usage()},
                       'component_result': {'mode':'vector search','selected_components':selected(dids),**usage()},
                       'evaluator_result':{'updated_subtasks':[{'answerability':False}],**usage()}}
                   }]}}
        self.detail_path.write_text(json.dumps(payload))
        res = {'qid':other_qid or qid, 'retrieved_units': [{'nodes':[[a,b]], 'edges':[],'score':float(i+1),'type':'node'} for i,(a,b) in enumerate(rids)],
               'agent_usage':result_usage if result_usage is not None else payload['agent_usage'],'llm_calls':1, 'api_usage':{}}
        self.jsonl_path.write_text(json.dumps(res)+'\n')

    def test_matching_pair(self):
        self.make_pair()
        out=verify_pair(self.detail_path,self.jsonl_path)
        self.assertTrue(out['internal_consistency_passed'])
        self.assertFalse(out['authentic_fif_execution_verified'])
        self.assertEqual(out['detail_final_component_count'], 2)

    def test_different_final_components_detected(self):
        self.make_pair(rids=[('docA','1'),('docC','3')])
        out=verify_pair(self.detail_path,self.jsonl_path)
        self.assertFalse(out['internal_consistency_passed'])
        self.assertFalse(out['checks']['same_final_component_set'])

    def test_reordered_final_components_detected(self):
        self.make_pair(rids=[('docB','2'),('docA','1')])
        out=verify_pair(self.detail_path,self.jsonl_path)
        self.assertFalse(out['internal_consistency_passed'])
        self.assertTrue(out['checks']['same_final_component_set'])
        self.assertFalse(out['checks']['same_final_component_sequence'])

    def test_missing_qid_detected(self):
        self.make_pair(other_qid='q-other')
        out=verify_pair(self.detail_path,self.jsonl_path)
        self.assertEqual(out['matching_jsonl_records'],0)
        self.assertFalse(out['internal_consistency_passed'])

    def test_repeated_qid_detected(self):
        self.make_pair()
        self.jsonl_path.write_text(self.jsonl_path.read_text()*2)
        out=verify_pair(self.detail_path,self.jsonl_path)
        self.assertEqual(out['matching_jsonl_records'],2)
        self.assertFalse(out['internal_consistency_passed'])

    def test_usage_mismatch_detected(self):
        self.make_pair(result_usage={'orchestrator':{'llm_calls':2}})
        out=verify_pair(self.detail_path,self.jsonl_path)
        self.assertFalse(out['checks']['same_agent_usage'])
        self.assertFalse(out['internal_consistency_passed'])

    def test_invalid_jsonl_line_fails_when_companion_exists(self):
        self.make_pair()
        self.jsonl_path.write_text('garbage\n'+self.jsonl_path.read_text())
        out=verify_pair(self.detail_path,self.jsonl_path)
        self.assertTrue(out['internal_consistency_passed'])
        self.assertEqual(out['invalid_jsonl_lines'],[1])

    def test_missing_retrieval_history_fails_consistency_check(self):
        self.make_pair()
        payload = json.loads(self.detail_path.read_text())
        del payload['memory']['tool_usage']
        self.detail_path.write_text(json.dumps(payload))
        out = verify_pair(self.detail_path, self.jsonl_path)
        self.assertFalse(out['checks']['memory_tool_usage_present'])
        self.assertFalse(out['internal_consistency_passed'])

    def test_malformed_selected_id_fails_consistency_check(self):
        self.make_pair()
        payload = json.loads(self.detail_path.read_text())
        payload['retrieved_nids'][0] = [['docA'], 1.0]
        self.detail_path.write_text(json.dumps(payload))
        out = verify_pair(self.detail_path, self.jsonl_path)
        self.assertFalse(out['checks']['same_final_component_sequence'])
        self.assertFalse(out['internal_consistency_passed'])


if __name__ == '__main__':
    unittest.main()

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from tracemicro.providers import safe_provider_error, rejected_generation_structure, ProviderError
from petclinic_batch_groq import GlobalBudget, run
from tracemicro.pilot import ROOT


class RejectedGenerationTests(unittest.TestCase):
    def test_safe_rejection_diagnostics_reach_batch_trace(self):
        base=ROOT/'results/full_scope_session_20261122/test-tmp'
        base.mkdir(parents=True,exist_ok=True)
        def transport(method,url,headers,body,timeout):
            context=json.loads(json.loads(body)['messages'][-1]['content'])
            rejected={'action':{'type':'submit','output':{'assignments':[{
                'class':context['state']['scope'][0], 'services':['private-invalid-label'],
                'shared':False,'evidence':['E1','E2']}]}}}
            payload={'error':{'code':'json_validate_failed','type':'invalid_request_error',
                              'failed_generation':json.dumps(rejected)}}
            raise urllib.error.HTTPError(url,400,'not-saved',{},io.BytesIO(json.dumps(payload).encode()))
        with tempfile.TemporaryDirectory(dir=base) as tmp, \
             patch('os.environ',{'GROQ_API_KEY':'synthetic-only-secret','TMP':str(base),'TEMP':str(base)}), \
             patch('socket.socket.connect',side_effect=AssertionError('No network')):
            result=run(Path(tmp)/'simulated',transport=transport,interval=0)
            error=result['batches'][0]['errors'][0]['provider_error']
            self.assertEqual(error['classification'],'json_output_rejected')
            self.assertEqual(error['rejected_generation_structure']['invalid_service_values'],1)
            self.assertEqual(error['rejected_generation_structure']['missing_scoped_classes_capped'],2)
            self.assertEqual(result['global_transport_attempts'],1)
            for path in (Path(tmp)/'simulated').glob('*.json'):
                text=path.read_text()
                self.assertNotIn('private-invalid-label',text)
                self.assertNotIn('synthetic-only-secret',text)

    def test_valid_json_content_is_not_persisted_but_label_error_is_counted(self):
        value={'action':{'type':'submit','output':{'assignments':[
            {'class':'private-class','services':['private-invalid-label'],'shared':False,'evidence':['private-ref']}]}}}
        constraints={'scope':['private-class'],'services':['candidate_1'],'evidence':{}}
        raw=json.dumps({'error':{'code':'json_validate_failed','failed_generation':json.dumps(value),
                                'message':'DO-NOT-LOG-private-secret'}}).encode()
        error=io.BytesIO(raw)
        result=safe_provider_error(error,'private-secret',constraints)
        diag=result['rejected_generation_structure']
        self.assertTrue(diag['parsed']); self.assertTrue(diag['exact_action_envelope'])
        self.assertEqual(diag['invalid_service_values'],1)
        self.assertEqual(diag['invalid_evidence_references'],1)
        for private in ['private-class','private-invalid-label','private-ref','private-secret','DO-NOT-LOG']:
            self.assertNotIn(private,json.dumps(result))

    def test_syntax_size_missing_envelope_and_unexpected_types(self):
        self.assertFalse(rejected_generation_structure('{"action":')['parsed'])
        self.assertEqual(rejected_generation_structure('x'*8193)['reason'],'size_limit')
        self.assertFalse(rejected_generation_structure('{}')['exact_action_envelope'])
        self.assertFalse(rejected_generation_structure(None)['parsed'])
        self.assertEqual(rejected_generation_structure('{"action":{"type":[]}}')['action_type'],'other_or_missing')
        self.assertNotIn('rejected_generation_structure',safe_provider_error(
            io.BytesIO(b'{"error":{"code":"json_validate_failed"}}'),'synthetic-secret'))

    def test_good_shared_generation_and_missing_scope_are_only_counts(self):
        value={'action':{'type':'submit','output':{'assignments':[
            {'class':'A','services':['x','y'],'shared':True,'evidence':['E1','E2']}]}}}
        result=rejected_generation_structure(json.dumps(value),{
            'scope':['A','B'],'services':['x','y'],'evidence':{'E1':'A','E2':'A'}})
        self.assertEqual(result['invalid_service_values'],0)
        self.assertEqual(result['invalid_shared_declarations'],0)
        self.assertEqual(result['missing_scoped_classes_capped'],1)

    def test_persistent_cap_cooldown_and_deadline_across_attempts(self):
        base=ROOT/'results/full_scope_session_20261122/test-tmp'; base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            ledger=Path(tmp)/'session.json'; now=[0.0]
            def sleep(n): now[0]+=n
            first=GlobalBudget(2,60,60,clock=lambda:now[0],sleeper=sleep,
                               deadline_monotonic=200,checkpoint_path=ledger)
            self.assertEqual(first.acquire(),0); first.finish()
            second=GlobalBudget(2,60,60,clock=lambda:now[0],sleeper=sleep,
                                deadline_monotonic=999,checkpoint_path=ledger)
            self.assertEqual(second.deadline_monotonic,200)
            self.assertEqual(second.acquire(),60); second.finish()
            with self.assertRaises(ProviderError): second.acquire()
            limited=GlobalBudget(2,60,60,clock=lambda:now[0],sleeper=sleep,deadline_monotonic=70)
            with self.assertRaisesRegex(ProviderError,'session_wall_time_limit'): limited.acquire()

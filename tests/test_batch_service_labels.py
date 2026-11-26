"""Wire schema and local correction tests; simulated HTTP may violate enum."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from petclinic_batch_groq import run
from petclinic_batch_prototype import SERVICES
from tracemicro.action_schema import response_schema
from tracemicro.pilot import ROOT, load_config, make_workflow
from tracemicro.providers import ScriptedProvider
from tracemicro.workflow import validate_output


def service_item(schema):
    action=schema['json_schema']['schema']['properties']['action']
    branch=action['anyOf'][-1] if 'anyOf' in action else action
    return branch['properties']['output']['properties']['assignments']['items']['properties']['services']['items']


class LabelSchemaTests(unittest.TestCase):
    def test_enum_uses_actual_labels_without_mutating_default_schema(self):
        self.assertEqual(service_item(response_schema(SERVICES)),{'type':'string','enum':SERVICES})
        self.assertNotIn('declared service',json.dumps(response_schema(SERVICES)))
        self.assertNotIn('enum',service_item(response_schema()))
        for bad in [[],['x','x'],[''],[1]]:
            with self.assertRaises(ValueError): response_schema(bad)

    def test_valid_shared_and_invalid_labels_use_unchanged_validator(self):
        evidence={'E1':{'class':'A','tool':'inspect_source'},'E2':{'class':'A','tool':'inspect_dependencies'}}
        row={'class':'A','services':SERVICES[:2],'shared':True,'evidence':['E1','E2']}
        self.assertEqual(validate_output({'assignments':[row]},['A'],SERVICES,evidence),[])
        for labels in [['declared service'],['candidate_99'],['candidate_1','candidate_1']]:
            bad=copy.deepcopy(row);bad['services']=labels
            self.assertIn('unknown_or_duplicate_service',[f['code'] for f in validate_output(
                {'assignments':[bad]},['A'],SERVICES,evidence)])

    def test_generic_examples_are_valid_labels_not_ground_truth(self):
        core=make_workflow(load_config('configs/petclinic_pilot.json'),ScriptedProvider([]))
        context=core.context()
        example=context['action_schema']['submit']['output']['assignments'][0]
        self.assertIn(example['services'][0],core.state.services)
        self.assertEqual(context['allowed_service_labels'],core.state.services)
        self.assertNotIn('declared service',json.dumps(context))


def label_fixture(persistent=False):
    saved=json.loads((ROOT/'results/petclinic_batch_groq/live_1/batch_01.json').read_text())
    original=[e['action'] for e in saved['events'] if e['kind']=='decision_received']
    contexts=[]; bodies=[]; clock=[0.0]
    def transport(method,url,headers,body,timeout):
        request=json.loads(body); bodies.append(request)
        context=json.loads(request['messages'][-1]['content']); contexts.append(context)
        assert service_item(request['response_format'])['enum']==SERVICES
        if len(contexts)==1 or (persistent and len(contexts)==2):
            action=copy.deepcopy(original[min(len(contexts)-1,1)])
        else:
            state=context['state']; evidence=state['evidence']
            action={'type':'submit','output':{'assignments':[
                {'class':name,'services':SERVICES[:2] if i==0 else SERVICES[:1],
                 'shared':i==0,'evidence':[eid for eid,r in evidence.items() if r['class']==name]}
                for i,name in enumerate(state['scope'])]}}
        clock[0]+=1
        return json.dumps({'model':'offline-simulation','choices':[{'finish_reason':'stop',
            'message':{'content':json.dumps({'action':action})}}],
            'usage':{'prompt_tokens':17,'completion_tokens':9,'total_tokens':26}}).encode()
    def sleep(seconds): clock[0]+=seconds
    return transport,lambda:clock[0],sleep,contexts,bodies


@unittest.skipUnless(importlib.util.find_spec('langgraph'),'LangGraph missing')
class LabelCorrectionTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'results/batch_label_fix/test-tmp'; base.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        env=patch('os.environ',{'GROQ_API_KEY':'synthetic-label-placeholder','TMP':str(base),
                              'TEMP':str(base),'LANGSMITH_TRACING':'false'})
        env.start();self.addCleanup(env.stop)
        guard=patch('socket.socket.connect',side_effect=AssertionError('No network allowed'))
        guard.start();self.addCleanup(guard.stop)

    def test_original_failure_corrected_using_explicit_feedback(self):
        transport,clock,sleep,contexts,bodies=label_fixture()
        result=run(self.path/'corrected',transport=transport,clock=clock,sleeper=sleep)
        self.assertEqual(result['status'],'basic_checks_passed')
        self.assertEqual(len(result['accepted_assignments']),25)
        self.assertEqual(result['global_transport_attempts'],10)
        self.assertEqual(result['global_wait_seconds'],540)
        feedback=contexts[1]['service_label_feedback']
        self.assertEqual(len(feedback),3)
        self.assertTrue(all(r['invalid_labels']==['declared service'] for r in feedback))
        self.assertEqual(len(contexts[1]['state']['verification_findings']),3)
        self.assertEqual(contexts[1]['allowed_service_labels'],SERVICES)
        self.assertIn(json.dumps(SERVICES),contexts[1]['batch_guidance'])
        self.assertNotIn('declared service',json.dumps(contexts[0]))
        for context in contexts:
            example=context['action_schema']['submit']['output']['assignments'][0]
            self.assertTrue(example['evidence'])
            self.assertTrue(all(context['state']['evidence'][eid]['class']==example['class']
                                for eid in example['evidence']))
        self.assertTrue(any(row['shared'] for row in result['accepted_assignments']))
        trace=json.loads((self.path/'corrected/batch_01.json').read_text())
        self.assertEqual(trace['model_usage'][0]['response_format'],bodies[0]['response_format'])
        self.assertFalse(trace['live_model_run'])

    def test_original_two_bad_responses_still_fail_locally(self):
        transport,clock,sleep,_,_=label_fixture(persistent=True)
        result=run(self.path/'original_failure',transport=transport,clock=clock,sleeper=sleep)
        self.assertEqual(result['status'],'failed_batch')
        self.assertEqual(result['accepted_assignments'],[])
        self.assertEqual(result['global_transport_attempts'],2)
        self.assertEqual(result['batches'][0]['stop'],'revision_budget_exhausted')
        self.assertEqual([f['code'] for f in result['batches'][0]['findings']],
                         ['unknown_or_duplicate_service']*3)

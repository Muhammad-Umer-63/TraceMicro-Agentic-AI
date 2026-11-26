import json
import unittest
from unittest.mock import patch

from petclinic_batch_groq import BatchGroqProvider, GlobalBudget, PreparedBatchWorkflow
from petclinic_batch_prototype import SERVICES, TOOLS
from tracemicro.action_schema import response_schema
from tracemicro.pilot import make_store
from tracemicro.providers import GroqConfig, rejected_generation_structure
from tracemicro.workflow import Budget, validate_output


class SubmitOnlyTests(unittest.TestCase):
    def test_schema_removes_union_and_tools_but_preserves_shared_array(self):
        schema=response_schema(SERVICES,allowed_actions=('submit',))
        action=schema['json_schema']['schema']['properties']['action']
        self.assertNotIn('anyOf',action)
        self.assertEqual(action['properties']['type']['enum'],['submit'])
        row=action['properties']['output']['properties']['assignments']['items']
        self.assertEqual(row['properties']['services']['items']['enum'],SERVICES)
        self.assertEqual(row['properties']['shared'],{'type':'boolean'})
        self.assertFalse(row['additionalProperties'])
        self.assertEqual(len(response_schema()['json_schema']['schema']['properties']['action']['anyOf']),3)
        with self.assertRaises(ValueError): response_schema(SERVICES,allowed_actions=['unknown'])

    def test_empty_generation_is_not_evidence_of_truncation_or_bad_enum(self):
        result=rejected_generation_structure('')
        self.assertEqual(result['characters_capped'],0)
        self.assertEqual(result['reason'],'empty_generation')
        self.assertNotIn('action_type',result)
        self.assertNotIn('invalid_service_values',result)
        self.assertNotIn('truncated',result)

    def test_actual_wire_and_recorded_instructions_are_submit_only(self):
        store=make_store(); name=store.classes[0]
        requests=[]
        action={'type':'submit','output':{'assignments':[{'class':name,'services':SERVICES[:2],
                 'shared':True,'evidence':['E1','E2']}]}}
        def transport(method,url,headers,body,timeout):
            requests.append(json.loads(body))
            return json.dumps({'choices':[{'finish_reason':'stop',
                'message':{'content':json.dumps({'action':action})}}]}).encode()
        provider=BatchGroqProvider(GroqConfig('openai/gpt-oss-20b',structured_outputs=True),
            GlobalBudget(interval=0),transport=transport)
        core=PreparedBatchWorkflow(store,provider,[name],SERVICES,Budget(2,0,1),
             required_evidence_tools=TOOLS,excerpt_ledger=[],previous_assignments=[])
        core.state.evidence={'E1':store.inspect_source(name),'E2':store.inspect_dependencies(name)}
        context=core.context()
        self.assertEqual(set(context['action_schema']),{'submit'})
        with patch('os.environ',{'GROQ_API_KEY':'synthetic-submit-only'}), \
             patch('socket.socket.connect',side_effect=AssertionError('No network')):
            returned=provider.decide(context)
        self.assertEqual(validate_output(returned['output'],[name],SERVICES,core.state.evidence,TOOLS),[])
        request=requests[0]; wire=json.loads(request['messages'][1]['content'])
        self.assertIn('submit is the only allowed action',wire['instruction'])
        self.assertEqual(provider.records[0]['system_instruction'],request['messages'][0]['content'])
        self.assertEqual(provider.records[0]['wire_instruction'],wire['instruction'])
        self.assertEqual(provider.records[0]['response_format'],request['response_format'])
        self.assertNotIn('anyOf',request['response_format']['json_schema']['schema']['properties']['action'])

    def test_invalid_labels_still_require_local_rejection(self):
        row={'class':'A','services':['unrecognized'],'shared':False,'evidence':['E1']}
        findings=validate_output({'assignments':[row]},['A'],SERVICES,
                                  {'E1':{'class':'A','tool':'inspect_source'}})
        self.assertIn('unknown_or_duplicate_service',[f['code'] for f in findings])

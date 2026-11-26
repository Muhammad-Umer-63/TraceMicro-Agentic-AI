import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from tracemicro.action_schema import response_schema
from tracemicro.providers import GroqProvider,GroqConfig,ProviderError
from tracemicro.pilot import make_store,ROOT
from tracemicro.workflow import Workflow,Budget,validate_output


def response(value,finish='stop',refusal=None):
    return json.dumps({'choices':[{'finish_reason':finish,'message':{'content':json.dumps(value),'refusal':refusal}}]}).encode()


class StructuredTests(unittest.TestCase):
    def provider(self,transport):
        return GroqProvider(GroqConfig('openai/gpt-oss-20b',structured_outputs=True),transport=transport)

    def test_schema_closed_required_properties_and_three_branches(self):
        schema=response_schema()['json_schema']
        self.assertTrue(schema['strict'])
        def check(value):
            if isinstance(value,dict):
                if value.get('type')=='object':
                    self.assertFalse(value['additionalProperties'])
                    self.assertEqual(set(value['required']),set(value['properties']))
                for child in value.values(): check(child)
            elif isinstance(value,list):
                for child in value: check(child)
        check(schema['schema'])
        branches=schema['schema']['properties']['action']['anyOf']
        self.assertEqual([b['properties']['type']['enum'][0] for b in branches],['inspect_source','inspect_dependencies','submit'])

    def test_each_valid_action_unwrapped_and_request_mode_explicit(self):
        actions=[{'type':'inspect_source','class':'fixture.A'},
                 {'type':'inspect_dependencies','class':'fixture.A'},
                 {'type':'submit','output':{'assignments':[{'class':'fixture.A','services':['a','b'],'shared':True,'evidence':['E1']}]}}]
        for action in actions:
            captured=[]
            def transport(method,url,headers,body,timeout):
                captured.append(json.loads(body)); return response({'action':action})
            p=self.provider(transport)
            with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'offline-placeholder'}):
                self.assertEqual(p.decide({'instruction':'old raw action instruction'}),action)
            request=captured[0]
            self.assertEqual(request['response_format']['type'],'json_schema')
            self.assertTrue(request['response_format']['json_schema']['strict'])
            self.assertFalse(request['stream']); self.assertNotIn('tools',request)
            self.assertIn('envelope',request['messages'][0]['content'])
            self.assertIn('"action"',json.loads(request['messages'][1]['content'])['instruction'])

    def test_refusal_incomplete_and_bad_envelopes_stop(self):
        cases=[(response({'action':{}},refusal='private refusal not logged'),'provider_refusal'),
               (response({'action':{}},finish='length'),'truncated_or_nonstop_response'),
               (response({'type':'inspect_source','class':'fixture.A'}),'invalid_structured_envelope'),
               (response({'action':{},'extra':'not allowed'}),'invalid_structured_envelope')]
        for raw,code in cases:
            p=self.provider(lambda *args:raw)
            with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'offline-placeholder'}):
                with self.assertRaises(ProviderError) as caught: p.decide({})
            self.assertEqual(caught.exception.code,code)
            self.assertEqual(p.request_count,1)
            self.assertNotIn('private refusal',json.dumps(p.records))

    def test_schema_http_error_no_fallback(self):
        calls=[]
        def transport(*args):
            calls.append(1)
            raise urllib.error.HTTPError('https://api.groq.com',400,'private',{},
                       io.BytesIO(b'{"error":{"code":"unsupported_schema","type":"invalid_request_error","message":"private"}}'))
        p=self.provider(transport)
        with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'offline-placeholder'}):
            with self.assertRaises(ProviderError): p.decide({})
        self.assertEqual(len(calls),1)
        self.assertEqual(p.records[0]['structured_output_status'],'request_rejected_no_fallback')
        self.assertEqual(p.records[0]['provider_error']['classification'],'schema_request_rejected')
        with self.assertRaises(ValueError): GroqConfig('unverified-model',structured_outputs=True)

    def test_original_local_argument_and_assignment_validation_still_applies(self):
        folder=ROOT/'results/groq_structured/test-tmp'; folder.mkdir(parents=True,exist_ok=True)
        p=self.provider(lambda *args:response({'action':{'type':'inspect_source'}}))
        name='org.springframework.samples.petclinic.model.BaseEntity'
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'offline-placeholder'}):
                doc=Workflow(make_store(),p,[name],['a','b'],Budget(1,1,0)).run(Path(tmp)/'trace.json')
        self.assertEqual(doc['state']['termination_reason'],'action_or_provider_error')
        self.assertEqual(doc['state']['evidence'],{})
        invalid={'assignments':[{'class':name,'services':['a','b'],'shared':False,'evidence':['E1']}]}
        findings=validate_output(invalid,[name],['a','b'],{'E1':{'class':name,'tool':'inspect_source'}})
        self.assertIn('invalid_shared_declaration',[f['code'] for f in findings])


if __name__=='__main__': unittest.main()

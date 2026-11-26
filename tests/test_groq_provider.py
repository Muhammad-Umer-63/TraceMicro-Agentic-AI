import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from tracemicro.providers import GroqConfig, GroqProvider, ProviderError, NoRedirect
from tracemicro.evidence import EvidenceStore
from tracemicro.workflow import Workflow, Budget

SECRET='unit-test-only-secret-not-a-credential'
ROOT=Path(__file__).resolve().parents[1]


def envelope(action=None, **extra):
    result={'model':'simulated-model','choices':[{'finish_reason':'stop',
            'message':{'content':json.dumps(action or {'type':'inspect_source','class':'fixture.A'})}}],
            'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}}
    result.update(extra)
    return json.dumps(result).encode()


class GroqTests(unittest.TestCase):
    def provider(self, transport, **settings):
        return GroqProvider(GroqConfig(model='simulation-only',**settings),transport=transport)

    @patch.dict(os.environ,{'GROQ_API_KEY':SECRET})
    def test_request_fields_and_content_response(self):
        calls=[]
        def transport(method,url,headers,body,timeout):
            calls.append((method,url,headers,body,timeout)); return envelope()
        p=self.provider(transport)
        self.assertEqual(p.decide({})['type'],'inspect_source')
        method,url,headers,body,timeout=calls[0]
        request=json.loads(body)
        self.assertEqual(method,'POST')
        self.assertTrue(url.endswith('/chat/completions'))
        self.assertEqual(headers['Authorization'],'Bearer '+SECRET)
        self.assertEqual(headers['User-Agent'],'TraceMicro-Diagnostic/1.0')
        self.assertNotIn(SECRET,body.decode())
        self.assertNotIn('max_tokens',request)
        self.assertEqual(request['max_completion_tokens'],512)
        self.assertEqual(request['response_format'],{'type':'json_object'})
        self.assertEqual(timeout,15)
        self.assertEqual(p.records[0]['usage']['total_tokens'],30)

    @patch.dict(os.environ,{'GROQ_API_KEY':SECRET})
    def test_http_errors_are_sanitized_without_retries(self):
        for status,code in [(400,'bad_request'),(401,'authentication_failed'),(403,'permission_denied'),(404,'not_found'),(429,'rate_limited'),(500,'http_error')]:
            calls=[]
            def transport(*args):
                calls.append(1); raise urllib.error.HTTPError('https://example.invalid/'+SECRET,status,SECRET,{},None)
            p=self.provider(transport)
            with self.assertRaises(ProviderError) as caught: p.decide({})
            self.assertEqual(caught.exception.code,code)
            self.assertEqual(len(calls),1)
            self.assertNotIn(SECRET,str(caught.exception)+json.dumps(p.records))

    @patch.dict(os.environ,{'GROQ_API_KEY':SECRET})
    def test_timeout_and_network_error(self):
        for error,code in [(TimeoutError(SECRET),'timeout'),(urllib.error.URLError(SECRET),'network_error')]:
            def transport(*args): raise error
            p=self.provider(transport)
            with self.assertRaises(ProviderError) as caught: p.decide({})
            self.assertEqual(caught.exception.code,code)
            self.assertNotIn(SECRET,json.dumps(p.records))

    @patch.dict(os.environ,{'GROQ_API_KEY':SECRET})
    def test_invalid_and_truncated_responses(self):
        cases=[(b'not JSON','invalid_response_json'),(b'{}','invalid_response_shape'),
               (envelope(choices=[{'finish_reason':'length','message':{'content':'{}'}}]),'truncated_or_nonstop_response'),
               (envelope(choices=[{'finish_reason':'stop','message':{'content':'```json {} ```'}}]),'invalid_action_json'),
               (envelope({'type':'shell','command':'delete'}),'invalid_action_shape'),
               (envelope(choices=[{'finish_reason':'stop','message':{'content':None}}]),'invalid_response_content')]
        for raw,code in cases:
            p=self.provider(lambda *args:raw)
            with self.assertRaises(ProviderError) as caught: p.decide({})
            self.assertEqual(caught.exception.code,code)

    @patch.dict(os.environ,{'GROQ_API_KEY':SECRET})
    def test_request_and_input_caps(self):
        calls=[]
        def transport(*args): calls.append(1); return envelope()
        p=self.provider(transport,max_requests=1)
        p.decide({})
        with self.assertRaises(ProviderError): p.decide({})
        self.assertEqual(len(calls),1)
        p=self.provider(transport,max_input_bytes=10)
        with self.assertRaises(ProviderError) as caught: p.decide({})
        self.assertEqual(caught.exception.code,'input_size_cap')
        self.assertEqual(p.request_count,0)

    def test_no_key_access_without_opt_in_and_missing_key(self):
        with patch('tracemicro.providers.os.environ') as environment:
            environment.get.side_effect=AssertionError('must not read key')
            p=GroqProvider(GroqConfig('not-selected'))
            with self.assertRaises(ProviderError): p.decide({})
        with patch.dict(os.environ,{},clear=True):
            p=self.provider(lambda *args:envelope())
            with self.assertRaises(ProviderError) as caught: p.decide({})
            self.assertEqual(caught.exception.code,'missing_api_key')
            self.assertEqual(p.http_requests_sent,0)

    @patch.dict(os.environ,{'GROQ_API_KEY':SECRET})
    def test_model_list_and_redirect_guard(self):
        p=self.provider(lambda *args:json.dumps({'data':[{'id':'chat-a'},{'id':'chat-b'}]}).encode())
        self.assertEqual(p.list_models(),['chat-a','chat-b'])
        with self.assertRaises(ProviderError): p.list_models()
        with self.assertRaises(ProviderError): NoRedirect().redirect_request(None,None,302,'',{},'https://other.invalid')
        with self.assertRaises(ValueError): GroqConfig('x',endpoint='https://other.invalid')

    @patch.dict(os.environ,{'GROQ_API_KEY':SECRET})
    def test_workflow_with_simulated_http_and_secret_echo(self):
        folder=ROOT/'results/groq_provider/test-tmp'
        folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            root=Path(tmp)
            src=root/'app/src/main/java'
            src.mkdir(parents=True)
            (src/'A.java').write_text('package fixture; class A {}')
            (root/'graph.json').write_text(json.dumps({'classes':{'fixture.A':{'relationships':{}}}}))
            store=EvidenceStore(root,'app','graph.json')
            actions=iter([{'type':'inspect_source','class':'fixture.A'},
                          {'type':'submit','output':{'assignments':[{'class':'fixture.A','services':['candidate'],
                             'shared':False,'evidence':['E1']}]}}])
            p=self.provider(lambda *args:envelope(next(actions),model=SECRET))
            trace=Workflow(store,p,['fixture.A'],['candidate'],Budget(2,1,0)).run(root/'trace.json')
            self.assertEqual(trace['state']['termination_reason'],'basic_checks_passed')
            self.assertFalse(trace['live_model_run'])
            self.assertEqual(trace['run_kind'],'groq_simulated_http')
            self.assertEqual(len(trace['model_usage']),2)
            self.assertNotIn(SECRET,(root/'trace.json').read_text())


if __name__ == '__main__': unittest.main()

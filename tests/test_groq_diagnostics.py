"""Offline diagnosis only; environment and transport are always substituted."""
import contextlib
import io
import json
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

import groq_workflow
from tracemicro.providers import GroqProvider, GroqConfig, ProviderError, NoRedirect, http_transport


class DiagnosticTests(unittest.TestCase):
    def classify(self, error):
        def transport(*args): raise error
        provider=GroqProvider(GroqConfig('simulation-only'),transport=transport)
        # Replace mapping entirely; never enumerate/read real environment credentials.
        with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'offline-placeholder'}):
            with self.assertRaises(ProviderError) as caught: provider.list_models()
        return caught.exception

    def test_403_has_http_source_not_local_permission_source(self):
        result=self.classify(urllib.error.HTTPError('https://api.groq.com/openai/v1/models',403,'not logged',{},None))
        self.assertEqual((result.code,result.status,result.source),('permission_denied',403,'http_response'))

    def test_direct_os_permission_failure_is_distinct(self):
        result=self.classify(PermissionError(13,'sensitive path not logged'))
        self.assertEqual((result.code,result.status,result.source),('local_permission_denied',None,'local_os'))
        self.assertNotIn('sensitive',str(result))

    def test_wrapped_os_permission_failure_is_distinct(self):
        result=self.classify(urllib.error.URLError(PermissionError(13,'not logged')))
        self.assertEqual((result.code,result.status,result.source),('local_permission_denied',None,'local_os'))

    def test_other_url_error_is_not_http_forbidden(self):
        result=self.classify(urllib.error.URLError('offline DNS failure'))
        self.assertEqual((result.code,result.status,result.source),('network_error',None,'transport'))

    def test_model_list_method_url_headers_body(self):
        calls=[]
        def transport(*args):
            calls.append(args); return b'{"data":[{"id":"simulated-only"}]}'
        provider=GroqProvider(GroqConfig('not-used-for-get'),transport=transport)
        with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'offline-placeholder'}):
            self.assertEqual(provider.list_models(),['simulated-only'])
        method,url,headers,body,timeout=calls[0]
        self.assertEqual((method,url,body),('GET','https://api.groq.com/openai/v1/models',None))
        self.assertEqual(headers,{'Authorization':'Bearer offline-placeholder','Content-Type':'application/json',
                                 'User-Agent':'TraceMicro-Diagnostic/1.0'})
        self.assertEqual(timeout,15)

    def test_transport_proxy_and_redirect_policy_without_network(self):
        response=Mock()
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        response.read.return_value=b'{}'
        opener=Mock()
        opener.open.return_value=response
        with patch('tracemicro.providers.urllib.request.build_opener',return_value=opener) as build:
            response.headers={}
            self.assertEqual(http_transport('GET','https://api.groq.com/openai/v1/models',{'Authorization':'Bearer offline-placeholder'},None,15).body,b'{}')
        proxy,redirect=build.call_args.args
        self.assertIsInstance(proxy,urllib.request.ProxyHandler)
        self.assertEqual(proxy.proxies,{})
        self.assertIsInstance(redirect,NoRedirect)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.get_method(),'GET')
        self.assertIsNone(request.data)
        self.assertIsNone(request.get_header('User-agent'))
        # urllib's default opener adds its own User-Agent later.
        self.assertTrue(dict(urllib.request.OpenerDirector().addheaders)['User-agent'].startswith('Python-urllib/'))

    def test_cli_exposes_http_status_without_error_body(self):
        provider=Mock()
        provider.list_models.side_effect=ProviderError('permission_denied',403,source='http_response')
        stderr=io.StringIO()
        with patch('sys.argv',['groq_workflow.py','--allow-live','--list-models']), patch('groq_workflow.GroqProvider',return_value=provider), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as caught: groq_workflow.main()
        self.assertEqual(caught.exception.code,1)
        self.assertIn('HTTP 403; response origin unverified',stderr.getvalue())

    def test_cli_distinguishes_local_failure(self):
        provider=Mock()
        provider.list_models.side_effect=ProviderError('local_permission_denied',source='local_os')
        stderr=io.StringIO()
        with patch('sys.argv',['groq_workflow.py','--allow-live','--list-models']), patch('groq_workflow.GroqProvider',return_value=provider), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit): groq_workflow.main()
        self.assertIn('local_permission_denied [local_os]',stderr.getvalue())
        self.assertNotIn('HTTP 403',stderr.getvalue())


if __name__ == '__main__': unittest.main()

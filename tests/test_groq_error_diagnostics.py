import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from tracemicro.providers import GroqProvider,GroqConfig,ProviderError,safe_provider_error


class ErrorDiagnosticTests(unittest.TestCase):
    def test_only_fixed_fields_and_structural_diagnostics_survive(self):
        secret='synthetic-placeholder'
        payload={'error':{'code':'json_validate_failed','type':'invalid_request_error',
                         'message':secret+' private text','failed_generation':'private generated output',
                         'authorization':'Bearer '+secret}}
        result=safe_provider_error(io.BytesIO(json.dumps(payload).encode()),secret)
        structure=result.pop('rejected_generation_structure')
        self.assertFalse(structure['parsed'])
        self.assertEqual(structure['reason'],'json_syntax_or_depth')
        self.assertEqual(result,{'classification':'json_output_rejected','code':'json_validate_failed','type':'invalid_request_error'})
        self.assertNotIn('private',json.dumps(structure))
        self.assertNotIn('private',json.dumps(result))
        self.assertNotIn(secret,json.dumps(result))

    def test_unknown_values_are_never_copied(self):
        payload={'error':{'code':'untrusted arbitrary code','type':'private arbitrary type','message':'private'}}
        self.assertEqual(safe_provider_error(io.BytesIO(json.dumps(payload).encode()),'synthetic'),
                         {'classification':'unrecognized_provider_error'})
        payload={'error':{'code':'invalid_api_key'}}
        self.assertEqual(safe_provider_error(io.BytesIO(json.dumps(payload).encode()),'invalid_api_key'),
                         {'classification':'unrecognized_provider_error'})

    def test_non_json_and_large_bodies_have_controlled_categories(self):
        self.assertEqual(safe_provider_error(io.BytesIO(b'<html>private</html>'),'synthetic'),{'classification':'error_body_not_json'})
        self.assertEqual(safe_provider_error(io.BytesIO(b'x'*20000),'synthetic'),{'classification':'error_body_too_large'})
        self.assertEqual(safe_provider_error(io.BytesIO(b'{}'),'synthetic'),{'classification':'error_object_unavailable'})

    def test_http400_metadata_preserves_no_retry_and_secret_safety(self):
        calls=[]
        def transport(*args):
            calls.append(1)
            body=json.dumps({'error':{'code':'json_validate_failed','type':'invalid_request_error',
                                     'message':'private synthetic-placeholder'}}).encode()
            raise urllib.error.HTTPError('https://api.groq.com',400,'private reason',
                  {'retry-after':'60'},io.BytesIO(body))
        provider=GroqProvider(GroqConfig('simulation-only'),transport=transport)
        with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'synthetic-placeholder'}):
            with self.assertRaises(ProviderError) as caught: provider.decide({})
        self.assertEqual((caught.exception.code,caught.exception.status),('bad_request',400))
        self.assertEqual(len(calls),1)
        record=provider.records[0]
        self.assertEqual(record['provider_error']['classification'],'json_output_rejected')
        self.assertEqual(record['rate_limits'],{'retry_after_seconds':60.0})
        self.assertNotIn('private',json.dumps(record))
        self.assertNotIn('synthetic-placeholder',json.dumps(record))


if __name__=='__main__': unittest.main()

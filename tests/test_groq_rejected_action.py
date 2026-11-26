"""Rejected-shape regression, synthetic responses and environment only."""
import json
import unittest
from unittest.mock import patch

from tracemicro.providers import GroqProvider, GroqConfig, ProviderError


class RejectedActionTests(unittest.TestCase):
    def test_shape_diagnostics_without_arbitrary_response_content(self):
        cases=[([], (False,False,False,False)),
               ({'unexpected':'private-response-content'},(True,False,False,False)),
               ({'type':'unknown-private-action'},(True,True,True,False)),
               ({'type':['inspect_source']},(True,True,False,False))]
        for action,expected in cases:
            payload={'model':'simulated-only','usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5},
                     'choices':[{'finish_reason':'stop','message':{'content':json.dumps(action)}}]}
            calls=[]
            def transport(*args): calls.append(1); return json.dumps(payload).encode()
            provider=GroqProvider(GroqConfig('simulated-only'),transport=transport)
            with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'synthetic-placeholder'}):
                with self.assertRaises(ProviderError) as caught: provider.decide({})
            self.assertEqual(caught.exception.code,'invalid_action_shape')
            record=provider.records[0]
            self.assertTrue(record['response_json_received'])
            self.assertTrue(record['action_json_received'])
            self.assertEqual(record['finish_reason'],'stop')
            self.assertEqual(tuple(record['action_shape'].values()),expected)
            self.assertEqual(record['usage']['total_tokens'],5)
            self.assertEqual(len(calls),1)
            serialized=json.dumps(record)
            self.assertNotIn('private-response-content',serialized)
            self.assertNotIn('unknown-private-action',serialized)
            self.assertNotIn('synthetic-placeholder',serialized)


if __name__ == '__main__': unittest.main()

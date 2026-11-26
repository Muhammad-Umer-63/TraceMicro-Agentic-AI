import json
import unittest
from unittest.mock import Mock, patch

from tracemicro.providers import GroqProvider, GroqConfig, ProviderError
from tracemicro.workflow import Workflow


class ActionPromptTests(unittest.TestCase):
    def test_prompt_has_explicit_top_level_type_examples_and_roundtrips(self):
        store=Mock(); store.classes=['fixture.A']
        context=Workflow(store,Mock(),['fixture.A'],['candidate']).context()
        for name,example in context['action_schema'].items():
            self.assertIsInstance(example,dict)
            self.assertEqual(example['type'],name)
        self.assertEqual(context['action_schema']['inspect_source'],{'type':'inspect_source','class':'fixture.A'})
        self.assertEqual(context['action_schema']['inspect_dependencies'],{'type':'inspect_dependencies','class':'fixture.A'})
        calls=[]
        def transport(method,url,headers,body,timeout):
            request=json.loads(body)
            calls.append(request)
            example=json.loads(request['messages'][1]['content'])['action_schema']['inspect_source']
            return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(example)}}]}).encode()
        provider=GroqProvider(GroqConfig('simulated-only'),transport=transport)
        with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'offline-placeholder'}):
            action=provider.decide(context)
        self.assertEqual(action,{'type':'inspect_source','class':'fixture.A'})
        self.assertIn('mandatory top-level string field "type"',calls[0]['messages'][0]['content'])
        self.assertIn('mandatory top-level string field "type"',context['instruction'])

    def test_missing_type_still_rejected_without_normalizing_aliases(self):
        # Synthetic missing-type example, not a reconstruction of the live reply.
        def transport(*args):
            return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'action':'inspect_source','class':'fixture.A'})}}]}).encode()
        provider=GroqProvider(GroqConfig('simulated-only'),transport=transport)
        with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'offline-placeholder'}):
            with self.assertRaises(ProviderError) as caught: provider.decide({})
        self.assertEqual(caught.exception.code,'invalid_action_shape')
        self.assertFalse(provider.records[0]['action_shape']['has_type'])


if __name__ == '__main__': unittest.main()

"""Simulate the recorded control-flow pattern, not unrecorded server details."""
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from tracemicro.pilot import ROOT,load_config,make_workflow
from tracemicro.providers import GroqConfig,GroqProvider


class PilotRateLimitTests(unittest.TestCase):
    def test_429_after_three_tools_preserves_evidence_budget_and_unknown_usage(self):
        config=load_config('configs/petclinic_pilot.json')
        classes=sorted(config['scope'])
        calls=[]
        def transport(method,url,headers,body,timeout):
            calls.append(1)
            index=len(calls)-1
            if index==3:
                raise urllib.error.HTTPError(url,429,'private server details not logged',{},None)
            action={'type':'inspect_source','class':classes[index]}
            return json.dumps({'model':'simulated-only',
                  'usage':{'prompt_tokens':2,'completion_tokens':1,'total_tokens':3},
                  'choices':[{'finish_reason':'stop','message':{'content':json.dumps(action)}}]}).encode()
        provider=GroqProvider(GroqConfig('simulated-only',max_requests=8,max_output_tokens=1024,max_input_bytes=64000),transport=transport)
        temp_root=ROOT/'results/pilot_1_diagnosis/test-tmp'
        temp_root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            path=Path(tmp)/'trace.json'
            with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'offline-placeholder'}):
                doc=make_workflow(config,provider).run(path)
            self.assertEqual(len(calls),4)  # no fifth call or automatic retry
            self.assertEqual(doc['state']['termination_reason'],'action_or_provider_error')
            self.assertEqual(doc['state']['budget'],{'decisions':4,'tool_calls':3,'revisions':1})
            self.assertEqual(len(doc['state']['evidence']),3)
            self.assertEqual(doc['state']['candidate_assignments'],[])
            self.assertEqual(doc['state']['revisions'],[])
            self.assertFalse(any(e['kind']=='verification' for e in doc['events']))
            error=next(e for e in doc['events'] if e['kind']=='error')
            self.assertEqual((error['code'],error['http_status'],error['error_source']),('rate_limited',429,'http_response'))
            self.assertIsNone(doc['model_usage'][-1]['usage'])
            self.assertFalse(doc['model_usage'][-1]['response_json_received'])
            self.assertEqual(doc['run_kind'],'groq_simulated_http')
            self.assertFalse(doc['live_model_run'])
            self.assertNotIn('private server details',path.read_text())
            self.assertNotIn('offline-placeholder',path.read_text())


if __name__=='__main__': unittest.main()

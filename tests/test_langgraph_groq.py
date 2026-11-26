"""Groq through actual LangGraph with injected HTTP; never real credentials."""
import copy
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from tracemicro.langgraph_workflow import LangGraphWorkflow
from tracemicro.pilot import ROOT, load_config, make_workflow, scripted_actions
from tracemicro.providers import GroqConfig, GroqProvider


def simulated_provider(actions, *, fail_http=False, max_requests=8):
    actions = iter(copy.deepcopy(actions))
    requests = []
    clock = [0.0]
    def transport(method, url, headers, body, timeout):
        # Headers intentionally never retained in evidence or request fixtures.
        requests.append(json.loads(body))
        if fail_http:
            raise urllib.error.HTTPError(url,429,'rate limit',{},io.BytesIO(b'{"error":{"code":"rate_limit_exceeded"}}'))
        return json.dumps({'model':'offline-simulation','choices':[{
            'finish_reason':'stop', 'message':{'content':json.dumps({'action':next(actions)})}}],
            'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}}).encode()
    def sleep(seconds):
        clock[0] += seconds  # No actual waiting.
    provider = GroqProvider(GroqConfig('openai/gpt-oss-20b', structured_outputs=True,
        max_requests=max_requests, max_output_tokens=1024, timeout_seconds=15,
        max_input_bytes=64000, min_interval_seconds=60, max_pacing_wait_seconds=420),
        transport=transport, clock=lambda:clock[0], sleeper=sleep)
    return provider, requests


@unittest.skipUnless(importlib.util.find_spec('langgraph'), 'LangGraph dependency missing')
class GraphGroqTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'results/langgraph_groq/test-tmp'
        folder.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.config=load_config('configs/petclinic_pilot.json')
        env=patch('os.environ',{'GROQ_API_KEY':'synthetic-offline-placeholder',
            'TMP':str(folder),'TEMP':str(folder),'LANGSMITH_TRACING':'false'})
        env.start(); self.addCleanup(env.stop)
        for target in ['socket.create_connection','socket.socket.connect','socket.socket.connect_ex']:
            guard=patch(target,side_effect=AssertionError('Offline test attempted network'))
            guard.start(); self.addCleanup(guard.stop)

    def run_simulation(self, actions, **kwargs):
        provider, requests=simulated_provider(actions,**kwargs)
        runner=LangGraphWorkflow(make_workflow(self.config,provider))
        doc=runner.run(self.path/'simulated.json')
        self.assertEqual(doc['execution_engine'],'langgraph')
        self.assertEqual(doc['run_kind'],'groq_simulated_http')
        self.assertFalse(doc['live_model_run'])
        self.assertNotIn('synthetic-offline-placeholder',json.dumps(doc))
        return doc,provider,requests

    def test_structured_http_shared_correction_usage_and_pacing(self):
        doc,provider,requests=self.run_simulation(scripted_actions(self.config))
        self.assertEqual(doc['state']['termination_reason'],'basic_checks_passed')
        self.assertEqual(doc['state']['budget'],{'decisions':0,'tool_calls':0,'revisions':0})
        self.assertEqual(len(doc['state']['evidence']),6)
        self.assertEqual(len(doc['state']['revisions']),1)
        self.assertEqual(len(requests),8)
        self.assertEqual(provider.pacing_wait_total,420)
        self.assertEqual(len(doc['model_usage']),8)
        self.assertEqual(sum(r['usage']['total_tokens'] for r in doc['model_usage']),120)
        self.assertTrue(all(r['response_format']['type']=='json_schema' for r in requests))
        self.assertTrue(all(r['max_completion_tokens']==1024 for r in requests))
        self.assertEqual(doc['run_config']['provider_config']['max_requests'],8)

    def test_incomplete_submission_still_fails(self):
        actions=scripted_actions(self.config); actions[-1]=copy.deepcopy(actions[-2])
        doc,_,_=self.run_simulation(actions)
        self.assertEqual(doc['state']['termination_reason'],'revision_budget_exhausted')
        self.assertEqual([f['code'] for f in doc['state']['verification_findings']],['missing_class'])

    def test_http_failure_stops_without_retry(self):
        doc,provider,requests=self.run_simulation([],fail_http=True)
        self.assertEqual(doc['state']['termination_reason'],'action_or_provider_error')
        self.assertEqual(len(requests),1)
        self.assertEqual(provider.http_requests_sent,1)
        self.assertEqual(doc['state']['evidence'],{})
        errors=[e for e in doc['events'] if e['kind']=='error']
        self.assertEqual(errors[0]['http_status'],429)
        self.assertEqual(errors[0]['code'],'rate_limited')
        self.assertIsNone(doc['model_usage'][0]['usage'])

    def test_provider_cap_not_bypassed_by_graph(self):
        doc,provider,requests=self.run_simulation(scripted_actions(self.config),max_requests=3)
        self.assertEqual(doc['state']['termination_reason'],'action_or_provider_error')
        self.assertEqual(len(requests),3)
        self.assertEqual(provider.http_requests_sent,3)
        self.assertEqual([e for e in doc['events'] if e['kind']=='error'][0]['code'],'provider_request_cap')

    def test_live_provider_requires_separate_explicit_graph_opt_in(self):
        provider=GroqProvider(GroqConfig('openai/gpt-oss-20b'),allow_live=True)
        core=make_workflow(self.config,provider)
        with self.assertRaises(ValueError): LangGraphWorkflow(core)
        runner=LangGraphWorkflow(core,allow_live=True)
        self.assertEqual(provider.http_requests_sent,0)
        doc=runner.document(runner.initial_state(),execution_engine='node_harness_not_langgraph')
        self.assertFalse(doc['live_model_run'])

    def test_cli_live_flags_are_explicit_and_bounded_without_request(self):
        import langgraph_pilot
        args=['langgraph_pilot.py','--allow-live','--model','openai/gpt-oss-20b',
              '--structured-output','--pace-seconds','60','--max-pacing-wait-seconds','420',
              '--output',str(self.path/'not_executed.json')]
        stub={'run_kind':'not_executed','execution_engine':'not_executed',
              'state':{'termination_reason':'basic_checks_passed'}}
        with patch('sys.argv',args), patch.object(langgraph_pilot,'LangGraphWorkflow') as graph:
            graph.return_value.run.return_value=stub
            with contextlib.redirect_stdout(io.StringIO()): langgraph_pilot.main()
        core=graph.call_args.args[0]
        self.assertTrue(graph.call_args.kwargs['allow_live'])
        self.assertEqual(core.provider.http_requests_sent,0)
        self.assertEqual(core.provider.config.max_requests,8)
        self.assertEqual(core.provider.config.max_output_tokens,1024)
        self.assertEqual(core.provider.config.min_interval_seconds,60)
        self.assertEqual(core.provider.config.max_pacing_wait_seconds,420)
        self.assertTrue(core.provider.config.structured_outputs)

    def test_cli_rejects_implicit_live_options_and_missing_model(self):
        import langgraph_pilot
        for options in [['--model','openai/gpt-oss-20b'],['--allow-live']]:
            with patch('sys.argv',['langgraph_pilot.py','--output',str(self.path/'unused.json'),*options]), \
                 contextlib.redirect_stderr(io.StringIO()), \
                 patch.object(langgraph_pilot,'GroqProvider',side_effect=AssertionError('No provider should be created')):
                with self.assertRaises(SystemExit) as stopped: langgraph_pilot.main()
                self.assertEqual(stopped.exception.code,2)


if __name__=='__main__': unittest.main()

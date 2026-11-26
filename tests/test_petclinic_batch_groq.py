import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from petclinic_batch_groq import GlobalBudget, run
from tracemicro.pilot import ROOT
from tracemicro.providers import ProviderError


def simulation(fail_batch=None, correct_first=True):
    """HTTP fixture generated from presented scope; mappings are artificial."""
    scopes, counts, contexts = [], {}, []
    clock = [0.0]
    def transport(method,url,headers,body,timeout):
        request=json.loads(body)
        context=json.loads(request['messages'][-1]['content'])
        contexts.append(context)
        scope=tuple(context['state']['scope'])
        if scope not in scopes: scopes.append(scope)
        batch=scopes.index(scope)+1
        counts[scope]=counts.get(scope,0)+1
        clock[0]+=1
        if batch==fail_batch:
            raise urllib.error.HTTPError(url,429,'synthetic-error',{},io.BytesIO(
                b'{"error":{"code":"rate_limit_exceeded","message":"do not save raw text"}}'))
        evidence=context['state']['evidence']
        labels=context['state']['services']
        rows=[{'class':name,'services':labels[:2] if i==0 else labels[:1],
               'shared':i==0,'evidence':[eid for eid,r in evidence.items() if r['class']==name]}
              for i,name in enumerate(scope)]
        if correct_first and batch==1 and counts[scope]==1: rows=rows[:-1]
        return json.dumps({'model':'offline-simulation','choices':[{'finish_reason':'stop',
            'message':{'content':json.dumps({'action':{'type':'submit','output':{'assignments':rows}}})}}],
            'usage':{'prompt_tokens':17,'completion_tokens':9,'total_tokens':26}}).encode()
    def sleep(seconds): clock[0]+=seconds
    return transport,lambda:clock[0],sleep,contexts


@unittest.skipUnless(importlib.util.find_spec('langgraph'),'LangGraph missing')
class FullBatchGroqTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'results/petclinic_batch_groq/test-tmp'; base.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=base); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        env=patch('os.environ',{'GROQ_API_KEY':'synthetic-batch-placeholder','TMP':str(base),
                              'TEMP':str(base),'LANGSMITH_TRACING':'false'})
        env.start(); self.addCleanup(env.stop)
        guard=patch('socket.socket.connect',side_effect=AssertionError('No network allowed'))
        guard.start(); self.addCleanup(guard.stop)

    def simulate(self, name='run', **scenario):
        transport,clock,sleep,contexts=simulation(**scenario)
        summary=run(self.path/name,transport=transport,clock=clock,sleeper=sleep)
        self.assertFalse(summary['live_model_run'])
        self.assertEqual(summary['run_kind'],'groq_simulated_http')
        self.assertNotIn('synthetic-batch-placeholder',json.dumps(summary))
        return summary,contexts

    def test_full_scope_correction_global_pacing_and_partial_context(self):
        summary,contexts=self.simulate()
        self.assertEqual(summary['status'],'basic_checks_passed')
        self.assertEqual(len(summary['accepted_assignments']),25)
        self.assertEqual(summary['combined_findings'],[])
        self.assertEqual(summary['global_transport_attempts'],10)
        self.assertEqual(summary['global_wait_seconds'],540)
        self.assertEqual(summary['batches'][1]['wait_seconds'],60) # new provider, same cooldown
        self.assertEqual(summary['reported_tokens']['total_tokens'],260)
        self.assertEqual(len(summary['batches']),9)
        self.assertTrue(any(x['source_excerpt_is_partial'] for c in contexts for x in c['source_excerpt_coverage']))
        self.assertTrue(any(r['shared'] for r in summary['accepted_assignments']))
        self.assertEqual(summary['precollection_reads'],50)
        self.assertTrue(contexts[2]['previous_accepted_assignments_for_global_label_consistency'])

    def test_failed_batch_keeps_accepted_rows_errors_and_unassigned_classes(self):
        summary,_=self.simulate(fail_batch=2)
        self.assertEqual(summary['status'],'failed_batch')
        self.assertEqual(len(summary['accepted_assignments']),3)
        self.assertEqual(summary['global_transport_attempts'],3)
        self.assertEqual(summary['batches'][-1]['errors'][0]['http_status'],429)
        self.assertEqual(summary['records_missing_token_fields']['total_tokens'],1)
        self.assertEqual(len(summary['combined_findings']),22)
        self.assertTrue((self.path/'run/batch_02.json').exists())
        self.assertNotIn('do not save raw text',(self.path/'run/batch_02.json').read_text())

    def test_global_request_and_wait_caps_stop_before_transport(self):
        for name,kwargs,expected in [('requests',{'max_requests':2},'global_request_cap'),
                                     ('wait',{'max_wait':60},'global_pacing_wait_budget_exhausted')]:
            transport,clock,sleep,_=simulation()
            summary=run(self.path/name,transport=transport,clock=clock,sleeper=sleep,**kwargs)
            self.assertEqual(summary['status'],'failed_batch')
            self.assertEqual(summary['global_transport_attempts'],2)
            self.assertEqual(summary['batches'][-1]['errors'][0]['code'],expected)

    def test_no_live_optin_and_existing_output_refused(self):
        with self.assertRaises(ValueError): run(self.path/'no_permission')
        self.assertFalse((self.path/'no_permission').exists())
        transport,clock,sleep,_=simulation()
        with self.assertRaises(FileExistsError):
            run(self.path,transport=transport,clock=clock,sleeper=sleep)


class GlobalBudgetTests(unittest.TestCase):
    def test_extended_session_cap_charges_all_24_attempts(self):
        budget = GlobalBudget(24, 0, 1380)
        for _ in range(24):
            budget.acquire()
        with self.assertRaises(ProviderError):
            budget.acquire()
        self.assertEqual(budget.requests, 24)
        with self.assertRaises(ValueError):
            GlobalBudget(25)
        with self.assertRaises(ValueError):
            GlobalBudget(24, 60, 1381)

    def test_cap_and_wait_do_not_reset_with_caller(self):
        now=[0.0]; waits=[]
        def sleep(n): waits.append(n); now[0]+=n
        budget=GlobalBudget(2,60,60,clock=lambda:now[0],sleeper=sleep)
        self.assertEqual(budget.acquire(),0)
        budget.last_finished=0
        self.assertEqual(budget.acquire(),60)
        with self.assertRaises(ProviderError): budget.acquire()
        self.assertEqual(waits,[60])

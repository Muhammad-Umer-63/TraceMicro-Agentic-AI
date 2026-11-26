import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tracemicro.pilot import ROOT,load_config,make_workflow,scripted_actions
from tracemicro.providers import GroqConfig,GroqProvider,ScriptedProvider
from tracemicro.workflow import validate_output


class PilotTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'results/petclinic_pilot/test-tmp'; folder.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.config=load_config('configs/petclinic_pilot.json')

    def test_simulated_http_incomplete_then_shared_correction(self):
        actions=iter(scripted_actions(self.config)); requests=[]
        def transport(method,url,headers,body,timeout):
            requests.append(json.loads(body))
            return json.dumps({'model':'offline-simulation','choices':[{'finish_reason':'stop',
                              'message':{'content':json.dumps(next(actions))}}]}).encode()
        limits=self.config['limits']
        provider=GroqProvider(GroqConfig('offline-simulation',max_requests=limits['model_requests'],
                                        max_output_tokens=limits['max_output_tokens'],max_input_bytes=limits['max_input_bytes']),transport=transport)
        with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'offline-placeholder'}):
            doc=make_workflow(self.config,provider).run(self.path/'simulated.json')
        self.assertEqual(doc['run_kind'],'groq_simulated_http')
        self.assertFalse(doc['live_model_run'])
        self.assertEqual(doc['state']['termination_reason'],'basic_checks_passed')
        self.assertEqual(len(requests),8)
        self.assertTrue(all(r['max_completion_tokens']==1024 for r in requests))
        self.assertEqual(len(doc['state']['evidence']),6)
        self.assertEqual(len(doc['state']['revisions']),1)
        checks=[e for e in doc['events'] if e['kind']=='verification']
        self.assertEqual([f['code'] for f in checks[0]['findings']],['missing_class'])
        self.assertEqual(checks[1]['findings'],[])
        shared=[r for r in doc['state']['candidate_assignments'] if r['shared']]
        self.assertEqual(shared[0]['services'],self.config['services'])
        self.assertEqual(doc['run_config']['pilot'],self.config)
        self.assertEqual(doc['state']['budget'],{'decisions':0,'tool_calls':0,'revisions':0})
        self.assertNotIn('offline-placeholder',(self.path/'simulated.json').read_text())

    def test_required_dependency_evidence_cannot_be_skipped(self):
        evidence={'E1':{'class':'fixture.A','tool':'inspect_source'}}
        output={'assignments':[{'class':'fixture.A','services':['a'],'shared':False,'evidence':['E1']}]}
        self.assertEqual(validate_output(output,['fixture.A'],['a','b'],evidence),[])
        result=validate_output(output,['fixture.A'],['a','b'],evidence,['inspect_source','inspect_dependencies'])
        self.assertEqual(result,[{'code':'required_evidence_missing','class_name':'fixture.A','tool':'inspect_dependencies'}])

    def test_fresh_progress_preserves_history_and_full_scope(self):
        workflow=make_workflow(self.config,ScriptedProvider([]))
        base=next(n for n in self.config['scope'] if n.endswith('.BaseEntity'))
        workflow.state.evidence['E1']=workflow.store.inspect_source(base)
        workflow.state.candidate_assignments=[{'class':base,'services':self.config['services'],
                                               'shared':True,'evidence':['E1']}]
        historical=validate_output({'assignments':workflow.state.candidate_assignments},
                                   workflow.state.scope,workflow.state.services,workflow.state.evidence,
                                   workflow.required_evidence_tools)
        workflow.state.verification_findings=copy.deepcopy(historical)
        before={r['class']:r for r in workflow.context()['per_class_progress']}
        self.assertEqual(before[base]['pending_evidence_tools'],['inspect_dependencies'])
        workflow.state.evidence['E2']=workflow.store.inspect_dependencies(base)
        workflow.state.evidence['E3']=workflow.store.inspect_dependencies(base)
        context=workflow.context()
        rows={r['class']:r for r in context['per_class_progress']}
        self.assertEqual(rows[base]['pending_evidence_tools'],[])
        self.assertEqual(rows[base]['duplicate_result_ids'],['E3'])
        self.assertTrue(rows[base]['candidate_record_present'])
        for name in set(self.config['scope'])-{base}:
            self.assertEqual(rows[name]['pending_evidence_tools'],['inspect_dependencies','inspect_source'])
            self.assertFalse(rows[name]['candidate_record_present'])
        self.assertEqual(context['state']['verification_findings'],historical)
        self.assertNotEqual(context['action_schema']['inspect_source']['class'],base)
        self.assertNotEqual(context['action_schema']['inspect_dependencies']['class'],base)
        # Available evidence is not automatically cited or used to fill assignments.
        self.assertIn('required_evidence_missing',[f['code'] for f in context['current_candidate_findings']])
        workflow.state.candidate_assignments[0]['evidence']=['E1','E2']
        current=workflow.context()['current_candidate_findings']
        self.assertEqual([f['code'] for f in current],['missing_class','missing_class'])
        self.assertEqual(workflow.state.verification_findings,historical)
        self.assertEqual(vars(workflow.state.budget),{'decisions':8,'tool_calls':6,'revisions':1})

    def test_latest_real_failure_replayed_offline_with_fresh_progress(self):
        saved=json.loads((ROOT/'results/groq_live/pilot_structured_1.json').read_text())
        actions=[e['action'] for e in saved['events'] if e['kind']=='decision_received']
        doc=make_workflow(self.config,ScriptedProvider(actions)).run(self.path/'replayed.json')
        self.assertFalse(doc['live_model_run'])
        self.assertEqual(doc['state']['termination_reason'],'revision_budget_exhausted')
        contexts=[e['context'] for e in doc['events'] if e['kind']=='decision_requested']
        final=contexts[-1]['per_class_progress']
        base=next(r for r in final if r['class'].endswith('.BaseEntity'))
        self.assertEqual(base['pending_evidence_tools'],[])
        self.assertEqual(base['duplicate_result_ids'],['E3'])
        self.assertEqual(sum(bool(r['pending_evidence_tools']) for r in final),2)
        self.assertEqual([f['code'] for f in doc['state']['verification_findings']],['missing_class','missing_class'])

    def test_progress_handles_rejected_non_list_assignments(self):
        workflow=make_workflow(self.config,ScriptedProvider([
            {'type':'submit','output':{'assignments':17}}]))
        doc=workflow.run(self.path/'bad_assignments.json')
        self.assertEqual(doc['state']['termination_reason'],'script_exhausted')
        self.assertEqual(doc['state']['verification_findings'],[{'code':'invalid_output_schema'}])
        self.assertTrue(all(not r['candidate_record_present'] for r in workflow.context()['per_class_progress']))

    def test_revision_exhaustion_preserves_failed_findings(self):
        actions=scripted_actions(self.config)
        actions[-1]=copy.deepcopy(actions[-2])
        doc=make_workflow(self.config,ScriptedProvider(actions)).run(self.path/'invalid.json')
        self.assertEqual(doc['state']['termination_reason'],'revision_budget_exhausted')
        self.assertEqual([f['code'] for f in doc['state']['verification_findings']],['missing_class'])
        self.assertEqual(len(doc['state']['revisions']),1)

    def test_infeasible_or_unknown_config_rejected(self):
        for variant in ['too_few_requests','unknown_field','one_service']:
            config=copy.deepcopy(self.config)
            if variant=='too_few_requests': config['limits']['model_requests']=6
            elif variant=='unknown_field': config['unexpected']='not accepted'
            else: config['services']=['only_one']
            path=self.path/(variant+'.json'); path.write_text(json.dumps(config))
            with self.assertRaises(ValueError): load_config(path)


if __name__=='__main__': unittest.main()

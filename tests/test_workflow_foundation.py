import json
import tempfile
import unittest
from pathlib import Path

from tracemicro.evidence import EvidenceStore
from tracemicro.providers import GroqConfig, GroqProvider, ScriptedProvider
from tracemicro.workflow import Budget, Workflow, validate_output

ROOT = Path(__file__).resolve().parents[1]


class FoundationTests(unittest.TestCase):
    def setUp(self):
        temp_root=ROOT/'results/workflow_foundation/test-tmp'
        temp_root.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        src=self.root/'app/src/main/java'
        src.mkdir(parents=True)
        (src/'A.java').write_text('package fixture;\npublic class A extends B {}\n',encoding='utf-8')
        (src/'B.java').write_text('package fixture;\npublic class B {}\n',encoding='utf-8')
        self.graph=self.root/'graph.json'
        self.graph.write_text(json.dumps({'classes':{'fixture.A':{'relationships':{'EXTENDS':{'fixture.B':1}}},
                                                   'fixture.B':{'relationships':{'EXTENDED_BY':{'fixture.A':1}}}}}))
        self.store=EvidenceStore(self.root,'app','graph.json')

    def row(self,name='fixture.A',evidence='E1',services=None,shared=False):
        return {'class':name,'services':services or ['alpha'],'shared':shared,'evidence':[evidence]}

    def test_source_lines_and_dependencies(self):
        evidence=self.store.inspect_source('fixture.A',2,2)
        self.assertEqual(evidence['path'],'app/src/main/java/A.java')
        self.assertEqual(evidence['lines'],[{'line':2,'text':'public class A extends B {}'}])
        dependencies=self.store.inspect_dependencies('fixture.A')
        self.assertEqual([(e['target'],e['type']) for e in dependencies['outgoing']],[('fixture.B','EXTENDS')])
        self.assertIsNone(dependencies['source_edge_line_references'])
        with self.assertRaises(ValueError): self.store.inspect_source('fixture.A',0,2)

    def test_snapshot_and_scope_path_guards(self):
        with self.assertRaises(ValueError): EvidenceStore(self.root,'app','graph.json',expected_snapshot='wrong')
        with self.assertRaises(ValueError): EvidenceStore(self.root,'app','graph.json',expected_graph_hash='wrong')
        with self.assertRaises(ValueError): self.store._inside(self.root.parent/'outside')
        with self.assertRaises(ValueError): Workflow(self.store,ScriptedProvider([]),['unknown'],['alpha'])

    def test_shared_classes_accepted_and_duplicate_rows_rejected(self):
        evidence={'E1':self.store.inspect_source('fixture.A')}
        row=self.row(services=['alpha','beta'],shared=True)
        self.assertEqual(validate_output({'assignments':[row]},['fixture.A'],['alpha','beta'],evidence),[])
        row['shared']=False
        self.assertIn('invalid_shared_declaration',[f['code'] for f in validate_output({'assignments':[row]},['fixture.A'],['alpha','beta'],evidence)])
        row['shared']=True
        self.assertIn('duplicate_class_record',[f['code'] for f in validate_output({'assignments':[row,row]},['fixture.A'],['alpha','beta'],evidence)])

    def test_invalid_unknown_missing_and_fabricated_evidence(self):
        evidence={'E1':self.store.inspect_source('fixture.A')}
        self.assertEqual(validate_output('not json',[],[],{}),[{'code':'invalid_output_schema'}])
        bad=self.row('unknown','made_up')
        codes={f['code'] for f in validate_output({'assignments':[bad]},['fixture.A'],['alpha'],evidence)}
        self.assertEqual(codes,{'unknown_or_out_of_scope_class','missing_class','invalid_or_missing_evidence'})

    def test_scripted_revision_and_saved_trace(self):
        actions=[{'type':'inspect_source','class':'fixture.A'}, {'type':'inspect_source','class':'fixture.B'},
                 {'type':'submit','output':{'assignments':[self.row()]}},
                 {'type':'submit','output':{'assignments':[self.row(),self.row('fixture.B','E2',['alpha','beta'],True)]}}]
        path=self.root/'trace.json'
        doc=Workflow(self.store,ScriptedProvider(actions),self.store.classes,['alpha','beta'],Budget(4,2,1)).run(path)
        self.assertEqual(doc['state']['termination_reason'],'basic_checks_passed')
        self.assertEqual(len(doc['state']['revisions']),1)
        self.assertEqual([f['code'] for f in next(e for e in doc['events'] if e['kind']=='verification')['findings']],['missing_class'])
        self.assertFalse(json.loads(path.read_text())['live_model_run'])
        self.assertEqual(doc['run_kind'],'scripted_test_only')

    def test_budget_limits_and_invalid_action_are_saved(self):
        actions=[{'type':'inspect_source','class':'fixture.A'}]*2
        doc=Workflow(self.store,ScriptedProvider(actions),self.store.classes,['alpha'],Budget(3,1,0)).run(self.root/'budget.json')
        self.assertEqual(doc['state']['termination_reason'],'tool_budget_exhausted')
        self.assertEqual(len(doc['state']['evidence']),1)
        doc=Workflow(self.store,ScriptedProvider([{'type':'delete_files'}]),self.store.classes,['alpha']).run(self.root/'invalid.json')
        self.assertEqual(doc['state']['termination_reason'],'action_or_provider_error')
        doc=Workflow(self.store,ScriptedProvider([]),self.store.classes,['alpha'],Budget(0,0,0)).run(self.root/'zero.json')
        self.assertEqual(doc['state']['termination_reason'],'decision_budget_exhausted')

    def test_revision_budget_and_stale_trace_guard(self):
        flow=Workflow(self.store,ScriptedProvider([{'type':'submit','output':{'assignments':[]}}]),self.store.classes,['alpha'],Budget(1,0,0))
        path=self.root/'trace.json'
        doc=flow.run(path)
        self.assertEqual(doc['state']['termination_reason'],'revision_budget_exhausted')
        with self.assertRaises(ValueError): flow.run(path)

    def test_groq_interface_never_calls_network_or_reads_keys(self):
        provider=GroqProvider(GroqConfig(model='test-placeholder'))
        request=provider.prepare_request([{'role':'user','content':'fixture'}])
        self.assertFalse(request['transport_enabled'])
        self.assertEqual(request['body']['model'],'test-placeholder')
        with self.assertRaises(RuntimeError): provider.decide({})
        with self.assertRaises(ValueError): GroqConfig('','http://invalid')


if __name__ == '__main__': unittest.main()

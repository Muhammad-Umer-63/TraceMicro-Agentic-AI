import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from petclinic_batch_prototype import collect
from petclinic_critic import run as criticize, should_review, validate_critique
from petclinic_global_plan import PlanSessionBudget, save
from tracemicro.evaluation import evaluate
from tracemicro.pilot import ROOT, make_store
from tracemicro.runtime_evidence import ScenarioEvidence


class EvaluationTests(unittest.TestCase):
    def test_label_renaming_and_shared_associations(self):
        reference = [{'class': 'A', 'decision': 'domain', 'services': ['x']},
                     {'class': 'B', 'decision': 'domain', 'services': ['y']},
                     {'class': 'S', 'decision': 'shared', 'services': ['x', 'y']}]
        predicted = [{'class': 'A', 'services': ['one'], 'shared': False},
                     {'class': 'B', 'services': ['two'], 'shared': False},
                     {'class': 'S', 'services': ['one', 'two'], 'shared': True}]
        result = evaluate(reference, predicted, ['A', 'B', 'S'])
        self.assertIsNone(result['domain_pairs']['f1'])
        self.assertEqual(result['shared_identification']['f1'], 1)
        self.assertEqual(result['shared_domain_anchor_associations']['tp'], 2)
        self.assertEqual(result['coverage'], 1)
        predicted.pop()
        result = evaluate(reference, predicted, ['A', 'B', 'S'])
        self.assertEqual(result['missing_predictions'], ['S'])
        self.assertEqual(result['shared_domain_anchor_associations']['fn'], 2)

    def test_missing_domain_classes_and_exclusions(self):
        reference = [{'class': 'A', 'decision': 'domain', 'services': ['x']},
                     {'class': 'B', 'decision': 'domain', 'services': ['x']},
                     {'class': 'U', 'decision': 'uncertain', 'services': []},
                     {'class': 'X', 'decision': 'exclude', 'services': []}]
        result = evaluate(reference, [{'class': 'A', 'services': ['p'], 'shared': False}], ['A', 'B', 'U', 'X'])
        self.assertEqual(result['domain_pairs']['fn'], 1)
        self.assertEqual(result['domain_pairs']['f1'], 0)
        self.assertEqual(result['coverage'], 0.5)
        with self.assertRaises(ValueError): evaluate(reference[:-1], [], ['A', 'B', 'U', 'X'])

    def test_duplicate_unknown_and_inconsistent_sharing_rejected(self):
        ref = [{'class': 'A', 'decision': 'domain', 'services': ['x']}]
        for rows in [[{'class': 'Z', 'services': ['x'], 'shared': False}],
                     [{'class': 'A', 'services': ['x', 'y'], 'shared': False}],
                     [{'class': 'A', 'services': ['x'], 'shared': False}]*2]:
            with self.assertRaises(ValueError): evaluate(ref, rows, ['A'])


class RuntimePlumbingTests(unittest.TestCase):
    def test_masks_whole_scenarios_and_charges_recovery(self):
        scenarios = {f's{i}': [{'synthetic_event': i}] for i in range(4)}
        for availability, count in [(0, 0), (0.5, 2), (1, 4)]:
            pool = ScenarioEvidence(scenarios, availability)
            self.assertEqual(len(pool.read_visible()), count)
            returned = pool.recover('s3')
            returned.clear()
            self.assertEqual(pool.recovery_calls, 1)
            self.assertEqual(pool.read_visible()['s3'], scenarios['s3'])
            with self.assertRaises(ValueError): pool.recover('heldout_assessment')
            self.assertEqual(pool.recovery_calls, 2)


class AnnotationPackageTests(unittest.TestCase):
    def test_blank_package_has_only_neutral_evidence(self):
        import csv
        from tools.prepare_petclinic_annotation import prepare
        base = ROOT/'results/course_development_20261123_2201/test-temp'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as name:
            folder = Path(name)/'package'
            prepare(folder)
            self.assertEqual(len(list((folder/'source').rglob('*.java'))), 25)
            for sheet in ['reviewer_A.csv', 'reviewer_B.csv', 'adjudication.csv']:
                with (folder/sheet).open(encoding='utf-8', newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 25)
                self.assertTrue(all(not row['decision'] and not row['services'] for row in rows))
            self.assertNotIn('candidate_1', (folder/'static_dependencies.json').read_text())


class CriticTests(unittest.TestCase):
    def setUp(self):
        base = ROOT/'results/course_development_20261123_2201/test-temp'
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        env = patch.dict('os.environ', {'GROQ_API_KEY': 'synthetic-only'}, clear=True)
        env.start(); self.addCleanup(env.stop)
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('No network'))
        guard.start(); self.addCleanup(guard.stop)
        self.now = [0.0]
        self.store = make_store()
        self.evidence, self.ledger = collect(self.store)

    def source(self, path, groups=1):
        path.mkdir()
        names = self.store.classes
        rows = [{'class': name, 'services': ['candidate_2'] if groups == 2 and i == 0 else ['candidate_1'],
                 'shared': False, 'evidence': [eid for eid, e in self.evidence.items() if e['class'] == name]}
                for i, name in enumerate(names)]
        save(path/'summary.json', {'source_fingerprint': self.store.snapshot['eligible_java_files_sha256'],
            'dependency_json_sha256': self.store.graph_sha256, 'status': 'synthetic_fixture',
            'run_kind': 'synthetic_test_only', 'accepted_assignments': rows,
            'allowed_service_labels': ['candidate_1', 'candidate_2']})
        save(path/'precollection.json', {'evidence': self.evidence, 'ledger': self.ledger})
        return path

    def budget(self):
        return PlanSessionBudget(self.folder/'budget.json', clock=lambda: self.now[0],
                                 sleeper=lambda wait: self.now.__setitem__(0, self.now[0]+wait))

    def transport(self, fail=False):
        def reply(method, url, headers, body, timeout):
            context = json.loads(json.loads(body)['messages'][1]['content'])
            self.assertNotIn('generator_dialogue', context)
            self.assertEqual(len(context['proposed_assignments']), 25)
            if fail: raise OSError('synthetic')
            issue = {'class': self.store.classes[0], 'kind': 'insufficient_evidence',
                'evidence': ['E1'], 'explanation': 'Synthetic fixture concern',
                'proposed_services': [], 'proposed_shared': False}
            return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(
                {'action': {'type': 'submit', 'output': {'issues': [issue]}}})}}], 'usage': {'total_tokens': 20}}).encode()
        return reply

    def test_fixed_selective_and_off_routing(self):
        source = self.source(self.folder/'source', groups=2)
        for mode, expected in [('fixed', 1), ('selective', 0), ('off', 0)]:
            result = criticize(source, self.folder/mode, self.budget(), mode, transport=self.transport())
            self.assertEqual(result['global_transport_attempts'], expected)
            self.assertFalse(result['corrections_applied'])
        self.assertTrue(should_review('selective', [{'services': ['x']}], []))

    def test_failure_count_and_reference_rejection(self):
        source = self.source(self.folder/'source')
        result = criticize(source, self.folder/'failure', self.budget(), 'fixed', transport=self.transport(fail=True))
        self.assertEqual(result['status'], 'critic_failed')
        self.assertEqual(result['global_transport_attempts'], 1)
        self.assertIsNone(result['reported_tokens']['total_tokens'])
        issue = {'class': self.store.classes[0], 'kind': 'boundary_concern', 'evidence': ['E999'],
                 'explanation': 'Synthetic', 'proposed_services': ['invented'], 'proposed_shared': False}
        errors = validate_critique({'issues': [issue]}, self.store.classes, ['candidate_1'], self.evidence)
        self.assertIn('invalid_issue_evidence', errors)
        self.assertIn('invalid_proposal_labels', errors)

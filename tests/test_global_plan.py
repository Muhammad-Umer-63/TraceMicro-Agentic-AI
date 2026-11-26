import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from petclinic_global_plan import PlanSessionBudget, planning_context, run, validate_plan
from petclinic_batch_prototype import collect
from tracemicro.pilot import make_store
from tracemicro.pilot import ROOT


class GlobalPlanTests(unittest.TestCase):
    def test_compact_payload_is_deterministic_and_traceable(self):
        evidence, ledger = collect(make_store())
        context, provenance = planning_context(evidence, ledger)
        self.assertEqual((context, provenance), planning_context(evidence, ledger))
        self.assertEqual(set(context['state']['evidence']), set(evidence))
        self.assertEqual(set(provenance), set(evidence))
        observed_edges = sum(len(r.get('outgoing', [])) for r in context['state']['evidence'].values())
        expected_edges = sum(len({(e['target'], e['type']) for e in r['outgoing']})
                             for r in evidence.values() if r['tool'] == 'inspect_dependencies')
        self.assertEqual(observed_edges, expected_edges)
        for eid, record in context['state']['evidence'].items():
            self.assertNotIn('lines', record)
            if 'declaration' in record:
                self.assertLessEqual(len(record['declaration'] or ''), 160)
                self.assertEqual(provenance[eid]['sha256'], evidence[eid]['sha256'])
                if record['line'] is not None:
                    original = next(line['text'].strip() for line in evidence[eid]['lines'] if line['line'] == record['line'])
                    self.assertEqual(record['declaration'], original[:160])

    def test_oversized_summary_fails_before_transport(self):
        from petclinic_global_plan import planning_context as build_context
        def oversized(evidence, ledger):
            context, provenance = build_context(evidence, ledger)
            context['oversized_fixture'] = 'x'*20000
            return context, provenance
        with patch('petclinic_global_plan.planning_context', side_effect=oversized):
            summary = run(self.folder/'oversized', self.budget(), transport=self.transport())
        self.assertEqual(summary['status'], 'failed_plan')
        self.assertEqual(summary['global_transport_attempts'], 0)
        doc = json.loads((self.folder/'oversized/planning.json').read_text())
        self.assertEqual(doc['error_code'], 'input_size_cap')

    def setUp(self):
        base = ROOT/'results/global_plan_development_20261123/test-temp'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.env = patch.dict('os.environ', {'GROQ_API_KEY': 'synthetic-only'}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('No network'))
        guard.start(); self.addCleanup(guard.stop)
        self.now = [0.0]

    def budget(self):
        return PlanSessionBudget(self.folder/'ledger.json', clock=lambda: self.now[0],
                                 sleeper=lambda wait: self.now.__setitem__(0, self.now[0]+wait))

    def transport(self, mode='valid'):
        def reply(method, url, headers, body, timeout):
            wire = json.loads(body)
            context = json.loads(wire['messages'][1]['content'])
            if wire['response_format']['json_schema']['name'] == 'tracemicro_plan_v1':
                if mode == 'plan_network_failure':
                    raise OSError('synthetic')
                self.assertEqual(len(context['state']['evidence']), 50)
                self.assertEqual(sum(r['source_excerpt_is_partial'] for r in context['source_excerpt_coverage']), 6)
                plan = {'services': [{'label': 'candidate_2', 'responsibility': 'Synthetic test role', 'evidence': ['E1']},
                                     {'label': 'candidate_4', 'responsibility': 'Second synthetic role', 'evidence': ['E2']}]}
                if mode == 'bad_plan': plan['services'][0]['evidence'] = ['UNKNOWN']
                output = plan
            else:
                self.assertNotIn('assignments', context['action_schema']['submit'])
                self.assertEqual(context['allowed_service_labels'], ['candidate_2', 'candidate_4'])
                self.assertEqual(context['global_service_plan']['services'][0]['label'], 'candidate_2')
                evidence = context['state']['evidence']
                rows = [{'class': name, 'services': ['candidate_2', 'candidate_4'], 'shared': True,
                         'evidence': [eid for eid, record in evidence.items() if record['class'] == name]}
                        for name in context['state']['scope']]
                if mode == 'incomplete': rows = rows[:-1]
                if mode == 'unplanned_label': rows[0]['services'] = ['candidate_1']; rows[0]['shared'] = False
                if mode == 'wrong_citation': rows[0]['evidence'] = ['E999']
                if mode == 'network_failure': raise OSError('synthetic')
                output = {'assignments': rows}
            return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(
                {'action': {'type': 'submit', 'output': output}})}}], 'usage': {'total_tokens': 10}}).encode()
        return reply

    def test_full_variant_shared_memberships_and_exact_context(self):
        summary = run(self.folder/'valid', self.budget(), transport=self.transport())
        self.assertEqual(summary['status'], 'basic_checks_passed')
        self.assertEqual(len(summary['accepted_assignments']), 25)
        self.assertTrue(all(row['shared'] for row in summary['accepted_assignments']))
        self.assertEqual(summary['global_transport_attempts'], 10)
        self.assertEqual(summary['reported_tokens']['total_tokens'], 100)

    def test_bad_plan_stops_before_assignments(self):
        summary = run(self.folder/'bad', self.budget(), transport=self.transport('bad_plan'))
        self.assertEqual(summary['status'], 'failed_plan')
        self.assertEqual(summary['planning_findings'], ['invalid_plan_evidence'])
        self.assertEqual(summary['global_transport_attempts'], 1)

    def test_unplanned_label_and_unknown_citation_fail_local_validation(self):
        for mode in ['unplanned_label', 'wrong_citation']:
            summary = run(self.folder/mode, self.budget(), transport=self.transport(mode))
            self.assertEqual(summary['status'], 'failed_batch')
            self.assertEqual(summary['accepted_assignments'], [])

    def test_failed_planning_transport_is_counted_and_usage_unknown(self):
        summary = run(self.folder/'plan_failure', self.budget(), transport=self.transport('plan_network_failure'))
        self.assertEqual(summary['status'], 'failed_plan')
        self.assertEqual(summary['global_transport_attempts'], 1)
        self.assertIsNone(summary['reported_tokens']['total_tokens'])

    def test_single_service_plan_is_valid(self):
        self.assertEqual(validate_plan({'services': [{'label': 'candidate_3',
            'responsibility': 'Synthetic whole application role', 'evidence': ['E1']}]}, {'E1': {}}), [])

    def test_incomplete_and_transport_failure_remain_explicit(self):
        for mode in ['incomplete', 'network_failure']:
            summary = run(self.folder/mode, self.budget(), transport=self.transport(mode))
            self.assertEqual(summary['status'], 'failed_batch')
            self.assertEqual(summary['accepted_assignments'], [])
            self.assertEqual(len(summary['combined_findings']), 25)
        self.assertEqual(summary['records_missing_token_fields']['total_tokens'], 1)

    def test_plan_duplicates_and_empty_roles_rejected(self):
        self.assertTrue(validate_plan({'services': []}, {}))
        self.assertTrue(validate_plan({'services': [
            {'label': 'candidate_1', 'responsibility': ' ', 'evidence': ['bad']}]*2}, {}))

    def test_session_restores_deadline_counts_and_cooldown(self):
        first = self.budget()
        first.acquire(); first.finish()
        self.now[0] = 10
        second = self.budget()
        self.assertEqual(second.deadline_monotonic, 3600)
        self.assertEqual(second.requests, 1)
        second.acquire()
        self.assertEqual(second.requests, 2)
        self.assertEqual(second.wait_total, 50)
        second.requests = 40
        from tracemicro.providers import ProviderError
        with self.assertRaises(ProviderError): second.acquire()

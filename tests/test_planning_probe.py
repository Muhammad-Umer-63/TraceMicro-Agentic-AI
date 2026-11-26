import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from annotation_evaluate import reference_metadata
from petclinic_global_plan import PlanSessionBudget
from planning_schema_probe import reduced_context, run
from tracemicro.pilot import ROOT


class ProbeTests(unittest.TestCase):
    def setUp(self):
        base = ROOT/'results/compact_failure_review_20261123_2225/test-temp'
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.source = ROOT/'results/course_live_20261123_2201/compact_run_1'
        env = patch.dict('os.environ', {'GROQ_API_KEY': 'synthetic-only'}, clear=True)
        env.start(); self.addCleanup(env.stop)
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('No network'))
        guard.start(); self.addCleanup(guard.stop)
        self.now = [0.0]

    def budget(self):
        return PlanSessionBudget(self.folder/'ledger.json', clock=lambda: self.now[0],
                                 sleeper=lambda wait: self.now.__setitem__(0, self.now[0]+wait))

    def transport(self, fail=False):
        def reply(method, url, headers, body, timeout):
            wire = json.loads(body)
            original = json.loads((self.source/'planning.json').read_text())
            self.assertEqual(wire['response_format'], original['model_usage'][0]['response_format'])
            context = json.loads(wire['messages'][1]['content'])
            self.assertEqual(len(context['state']['scope']), 1)
            self.assertEqual(set(context['state']['evidence']), {'E1', 'E2'})
            self.assertLess(len(body), 9464)
            if fail: raise OSError('synthetic network failure')
            return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(
                {'action': {'type': 'submit', 'output': {'services': [{'label': 'candidate_1',
                    'responsibility': 'Synthetic test responsibility', 'evidence': ['E1']}]}}})}}],
                'usage': {'total_tokens': 10}}).encode()
        return reply

    def test_one_request_probe_preserves_schema_and_reduces_context(self):
        result = run(self.source, self.folder/'probe', self.budget(), transport=self.transport())
        self.assertEqual(result['status'], 'probe_passed')
        self.assertEqual(result['global_transport_attempts'], 1)
        self.assertTrue(result['diagnostic_only'])
        self.assertFalse(result['full_scope_decomposition'])

    def test_failed_transport_unknown_usage_and_expired_budget(self):
        budget = self.budget()
        result = run(self.source, self.folder/'failed', budget, transport=self.transport(fail=True))
        self.assertEqual(result['status'], 'probe_failed')
        self.assertEqual(result['global_transport_attempts'], 1)
        self.assertIsNone(result['reported_tokens']['total_tokens'])
        self.now[0] = 3601
        result = run(self.source, self.folder/'expired', budget, transport=self.transport())
        self.assertEqual(result['error_code'], 'session_wall_time_limit')
        self.assertEqual(result['global_transport_attempts'], 0)

    def test_reduced_records_are_exact_saved_summaries(self):
        original = json.loads((self.source/'planning.json').read_text())['context']
        context = reduced_context(original)
        for eid, row in context['state']['evidence'].items():
            self.assertEqual(row, original['state']['evidence'][eid])
        self.assertEqual(len(original['state']['scope']), 25)

    def test_solo_reference_has_explicit_bias_label(self):
        metadata = reference_metadata('author-reviewed-development')
        self.assertTrue(metadata['reviewer_has_seen_model_outputs'])
        self.assertFalse(metadata['fulfills_two_independent_annotators'])
        self.assertEqual(metadata['reference_label'], 'Author-reviewed development reference; reviewer has seen model outputs.')

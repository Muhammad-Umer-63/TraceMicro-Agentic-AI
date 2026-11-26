import unittest

from petclinic_global_plan import BoundedPlanProvider, PlanProvider, validate_bounded_plan, validate_plan
from petclinic_batch_groq import GlobalBudget
from tracemicro.providers import GroqConfig


class BoundedPlanTests(unittest.TestCase):
    def test_bounds_and_distinct_citations_without_repair(self):
        evidence = {'E1': {}, 'E2': {}, 'E3': {}}
        row = {'label': 'candidate_1', 'responsibility': 'x'*160, 'evidence': ['E1', 'E2']}
        plan = {'services': [row]}
        self.assertEqual(validate_bounded_plan(plan, evidence), [])
        row['responsibility'] += 'x'
        self.assertIn('plan_responsibility_too_long', validate_bounded_plan(plan, evidence))
        self.assertEqual(len(row['responsibility']), 161)
        row['responsibility'] = 'Brief role'
        for refs in [['E1', 'E2', 'E3'], ['E1', 'E1']]:
            row['evidence'] = refs
            self.assertIn('plan_citations_not_bounded_distinct', validate_bounded_plan(plan, evidence))
        self.assertEqual(validate_plan(plan, evidence), [])

    def test_wire_schema_and_generation_settings_unchanged(self):
        config = GroqConfig('openai/gpt-oss-20b', structured_outputs=True)
        old = PlanProvider(config, GlobalBudget())
        new = BoundedPlanProvider(config, GlobalBudget())
        self.assertEqual(old.prepare_request([]), new.prepare_request([]))
        self.assertEqual(new.config.max_output_tokens, old.config.max_output_tokens)
        self.assertIn('at most160characters', new.structured_instructions()[0])

    def test_malformed_or_unknown_evidence_and_single_service(self):
        self.assertTrue(validate_bounded_plan(None, {}))
        plan = {'services': [{'label': 'candidate_3', 'responsibility': 'One whole application', 'evidence': ['E1']}]}
        self.assertEqual(validate_bounded_plan(plan, {'E1': {}}), [])
        self.assertIn('invalid_plan_evidence', validate_bounded_plan(plan, {}))

import unittest

from petclinic_full_scope_review import dependency_diagnostics, membership_signatures, pairs


class MembershipComparisonTests(unittest.TestCase):
    def test_shared_dependency_and_missing_endpoint(self):
        rows = [{'class': 'A', 'services': ['x', 'y']}, {'class': 'B', 'services': ['y']},
                {'class': 'C', 'services': ['z']}]
        edges = [{'source': 'A', 'target': 'B'}, {'source': 'A', 'target': 'C'},
                 {'source': 'A', 'target': 'Missing'}]
        result = dependency_diagnostics(rows, edges)
        self.assertEqual(result['typed_edges_with_both_classes_assigned'], 2)
        self.assertEqual(result['typed_edges_without_common_service'], 1)

    def test_label_renames_preserve_shared_membership(self):
        rows = [{'class': 'A', 'services': ['x', 'y']},
                {'class': 'B', 'services': ['x']},
                {'class': 'C', 'services': ['y']}]
        renamed = [{'class': 'A', 'services': ['two', 'one']},
                   {'class': 'B', 'services': ['one']},
                   {'class': 'C', 'services': ['two']}]
        self.assertEqual(membership_signatures(rows), membership_signatures(renamed))
        self.assertEqual(pairs(rows), {('A', 'B'), ('A', 'C')})
        renamed[0]['services'] = ['one']
        self.assertNotEqual(membership_signatures(rows), membership_signatures(renamed))


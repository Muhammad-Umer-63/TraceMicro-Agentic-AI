import json
import unittest
from pathlib import Path

from dependency_baseline import load_graph, cluster, structural_counts


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.raw = {'classes': {
            'A': {'relationships': {'EXTENDS': {'B':1}}},
            'B': {'relationships': {'EXTENDED_BY': {'A':1}}},
            'C': {'relationships': {'EXTENDS': {'D':1}}},
            'D': {'relationships': {'EXTENDED_BY': {'C':1}}}}}

    def test_manual_pairs_and_inverse_deduplication(self):
        nodes, edges = load_graph(self.raw)
        groups, history = cluster(nodes, edges, 2)
        self.assertEqual(list(groups.values()), [['A','B'],['C','D']])
        self.assertEqual(len(edges),2)
        stats = structural_counts(nodes, edges, groups)
        self.assertEqual(stats['cross_group_directed_pairs'],0)
        self.assertEqual(stats['unique_undirected_pair_count'],2)

    def test_actual_java_fixture(self):
        p = Path(__file__).resolve().parents[1]/'results/dependency_baseline/fixture_raw.json'
        nodes, edges = load_graph(json.loads(p.read_text()))
        self.assertEqual({(e['source'],e['target'],e['type']) for e in edges},
                         {('fixture.A','fixture.B','EXTENDS'),('fixture.C','fixture.D','EXTENDS')})
        self.assertEqual(list(cluster(nodes,edges,2)[0].values()),
                         [['fixture.A','fixture.B'],['fixture.C','fixture.D']])

    def test_order_invariance_and_zero_link_ties(self):
        nodes, edges = load_graph(self.raw)
        self.assertEqual(cluster(nodes,edges,2),cluster(list(reversed(nodes)),list(reversed(edges)),2))
        groups, history = cluster(['C','B','A'],[],2)
        self.assertEqual(list(groups.values()),[['A','B'],['C']])
        self.assertTrue(history[0]['zero_link_merge'])

    def test_invalid_graph_and_grouping_rejected(self):
        self.raw['classes']['A']['relationships']['EXTENDS']['Missing']=1
        with self.assertRaises(ValueError): load_graph(self.raw)
        with self.assertRaises(ValueError): cluster(['A'],[],0)
        with self.assertRaises(ValueError): cluster(['A'],[],2)
        with self.assertRaises(ValueError): structural_counts(['A','B'],[],{'x':['A','A']})

    def test_direction_type_and_occurrence_counts_are_distinct(self):
        self.raw['classes']['A']['relationships']['USES']={'B':3}
        nodes, edges = load_graph(self.raw)
        groups={'x':['A','C'],'y':['B','D']}
        s=structural_counts(nodes,edges,groups)
        self.assertEqual((s['typed_direct_edge_count'],s['unique_directed_pair_count'],s['analyzer_reported_occurrences']),(3,2,5))
        self.assertEqual(s['cross_group_directed_pairs'],2)


if __name__ == '__main__':
    unittest.main()

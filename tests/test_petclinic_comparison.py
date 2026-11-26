import copy
import unittest
from unittest.mock import patch

from petclinic_comparison import group_rows, recorded_resources, summarize_assignments, compare_saved


class ComparisonTests(unittest.TestCase):
    def test_shared_row_is_preserved_and_not_a_duplicate(self):
        rows=[{'class':'A','services':['owners','vets'],'shared':True,'evidence':['E1','E2']},
              {'class':'B','services':['owners'],'shared':False}]
        before=copy.deepcopy(rows)
        result=summarize_assignments(rows,['A','B'],{'A','B'})
        self.assertEqual(result['assignment_coverage'],1)
        self.assertEqual(result['duplicate_class_records'],{})
        self.assertEqual(result['assignments'],before)
        self.assertEqual(rows,before)
        self.assertEqual(result['represented_group_count'],2)

    def test_missing_duplicate_unknown_and_known_exclusions_are_distinct(self):
        rows=[{'class':n,'services':['g'],'shared':False} for n in ['A','A','C','invented']]
        result=summarize_assignments(rows,['A','B'],{'A','B','C'})
        self.assertEqual(result['assignment_coverage'],0.5)
        self.assertEqual(result['missing_class_records'],['B'])
        self.assertEqual(result['duplicate_class_records'],{'A':2})
        self.assertEqual(result['unknown_classes_in_input'],['invented'])
        self.assertEqual(result['known_out_of_scope_classes_excluded'],['C'])
        self.assertEqual(len(result['assignments']),2)

    def test_group_conversion_does_not_hide_duplicate_memberships(self):
        rows=group_rows({'g1':['A','B'],'g2':['A']})
        result=summarize_assignments(rows,['A','B'],{'A','B'})
        self.assertEqual(result['duplicate_class_records'],{'A':2})
        self.assertEqual(group_rows({'pkg':['src/main/java/pkg/A.java']},source_paths=True)[0]['class'],'pkg.A')

    def test_presence_is_not_coverage_or_validity(self):
        rows=[{'class':'A','services':[],'shared':False},
              {'class':'B','services':['x','y'],'shared':False},None]
        result=summarize_assignments(rows,['A','B'],{'A','B'})
        self.assertEqual(result['missing_class_records'],[])
        self.assertEqual(result['unassigned_classes'],['A'])
        self.assertEqual(result['assignment_coverage'],0.5)
        self.assertEqual({r['code'] for r in result['invalid_records']},
                         {'invalid_services','invalid_shared_declaration','invalid_class_record'})

    def test_missing_usage_stays_unknown_and_does_not_become_zero(self):
        trace={'state':{},'model_usage':[{'status':'error','usage':None}], 'events':[]}
        result=recorded_resources(trace)
        self.assertEqual(result['model_request_records'],1)
        self.assertIsNone(result['reported_tokens']['total_tokens'])
        self.assertEqual(result['records_missing_token_fields']['total_tokens'],1)
        self.assertIsNone(result['reported_pacing_wait_seconds'])
        self.assertIsNone(result['recorded_elapsed_seconds_including_pacing'])

    def test_partial_recorded_usage_timing_and_pacing_not_double_counted(self):
        trace={'state':{'revisions':[]},'model_usage':[
            {'status':'parsed','usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15},
             'pacing_wait_seconds':0,'pacing_wait_total_seconds':0},
            {'status':'error','usage':None,'pacing_wait_seconds':60,'pacing_wait_total_seconds':60}],
            'events':[{'kind':'started','timestamp_utc':'2026-01-01T00:00:00+00:00'},
                      {'kind':'tool_result'},
                      {'kind':'terminated','timestamp_utc':'2026-01-01T00:01:05+00:00'}]}
        result=recorded_resources(trace)
        self.assertEqual(result['reported_tokens']['total_tokens'],15)
        self.assertEqual(result['records_missing_token_fields']['total_tokens'],1)
        self.assertEqual(result['reported_pacing_wait_seconds'],60)
        self.assertEqual(result['recorded_elapsed_seconds_including_pacing'],65)
        self.assertEqual(result['tool_results'],1)
        self.assertIsNone(result['billing_cost'])

    def test_saved_partition_used_without_clustering(self):
        with patch('dependency_baseline.cluster',side_effect=AssertionError('Must not recluster')):
            report=compare_saved()
        methods=report['methods']
        self.assertEqual([m['represented_group_count'] for m in methods.values()],[3,1,2])
        self.assertTrue(all(m['assignment_coverage']==1 for m in methods.values()))
        self.assertFalse(report['architectural_quality_evaluated'])
        shared=[r for r in methods['tracemicro_saved_live']['assignments'] if r['shared']]
        self.assertEqual(len(shared),1)
        self.assertEqual(shared[0]['evidence'],['E1','E2'])
        self.assertEqual(report['recorded_live_resources']['model_request_records'],7)

    def test_source_mismatch_fails_closed(self):
        with patch('petclinic_comparison.analyze',return_value={
                'snapshot':{'eligible_java_files_sha256':'synthetic-wrong-hash'}}):
            with self.assertRaisesRegex(ValueError,'fingerprint mismatch'):
                compare_saved()


if __name__=='__main__': unittest.main()

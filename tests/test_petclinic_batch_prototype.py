import copy
import unittest

from petclinic_batch_prototype import batches, collect, combine


class BatchPrototypeTests(unittest.TestCase):
    def test_batch_partition_is_complete_and_deterministic(self):
        names=[str(i) for i in range(25)]
        result=batches(names)
        self.assertEqual([len(b) for b in result],[3]*8+[1])
        self.assertEqual([n for b in result for n in b],names)

    def test_merge_preserves_shared_and_detects_missing_duplicate_wrong_evidence(self):
        evidence={'E1':{'class':'A','tool':'inspect_source'},'E2':{'class':'A','tool':'inspect_dependencies'}}
        row={'class':'A','services':['candidate_1','candidate_2'],'shared':True,'evidence':['E1','E2']}
        self.assertEqual(combine([row],['A'],evidence),[])
        self.assertIn('missing_class',[f['code'] for f in combine([row],['A','B'],evidence)])
        self.assertIn('duplicate_class_record',[f['code'] for f in combine([row,row],['A'],evidence)])
        changed=copy.deepcopy(row); changed['class']='B'
        self.assertIn('invalid_or_missing_evidence',[f['code'] for f in combine([changed],['B'],evidence)])

    def test_precollection_has_two_real_provenance_records_per_class(self):
        class FakeStore:
            classes=['A']; files={'A':{'lines':['x']*100}}
            def inspect_source(self,name):
                return {'class':name,'tool':'inspect_source','end_line':80,'sha256':'synthetic-source'}
            def inspect_dependencies(self,name):
                return {'class':name,'tool':'inspect_dependencies','sha256':'synthetic-dependency'}
        evidence,ledger=collect(FakeStore())
        self.assertEqual(len(evidence),2)
        self.assertTrue(ledger[0]['source_excerpt_is_partial'])
        self.assertEqual(ledger[0]['source_total_lines'],100)
        self.assertEqual(evidence['E1']['sha256'],'synthetic-source')

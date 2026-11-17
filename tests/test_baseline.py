import tempfile
import unittest
from pathlib import Path
from baseline import analyze, compare_archived


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / 'src/main/java'
        self.src.mkdir(parents=True)

    def write(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')

    def test_package_noise_and_unassigned(self):
        self.write('src/main/java/A.java', '/* package wrong; */ package right; class A { String s="package fake;"; }')
        self.write('src/main/java/B.java', 'class B { String s="package fake;"; }')
        r = analyze(self.root)
        self.assertEqual(list(r['candidate_services']), ['right'])
        self.assertEqual(r['state']['assignment_coverage'], 0.5)
        self.assertEqual(r['state']['unassigned_files'], ['src/main/java/B.java'])

    def test_nested_copy_tests_and_metadata_excluded(self):
        self.write('src/main/java/A.java', 'package a; class A {}')
        self.write('src/main/java/package-info.java', 'package a;')
        self.write('src/test/java/T.java', 'package test; class T {}')
        self.write('duplicate/src/main/java/A.java', 'package a; class A {}')
        self.assertEqual(analyze(self.root)['state']['files_discovered'], 1)

    def test_fingerprint_tracks_content(self):
        self.write('src/main/java/A.java', 'package a; class A {}')
        first = analyze(self.root)
        self.assertEqual(first, analyze(self.root))
        self.write('src/main/java/A.java', 'package a; class A { int added; }')
        self.assertNotEqual(first['snapshot'], analyze(self.root)['snapshot'])

    def test_membership_change_detected_without_count_change(self):
        self.write('src/main/java/A.java', 'package a; class A {}')
        r = analyze(self.root)
        wrong = dict(r, candidate_services={'other': ['src/main/java/A.java']})
        self.assertTrue(compare_archived(r, wrong)['state'])
        self.assertFalse(compare_archived(r, wrong)['candidate_services'])

    def test_missing_and_empty_inputs_fail(self):
        with self.assertRaises(ValueError):
            analyze(self.root / 'missing')
        with self.assertRaises(ValueError):
            analyze(self.root)

    def test_inventory_order_is_not_a_scientific_difference(self):
        self.write('src/main/java/A.java', 'package a; class A {}')
        self.write('src/main/java/B.java', 'package a; class B {}')
        r = analyze(self.root)
        reordered = dict(r, source_inventory=list(reversed(r['source_inventory'])))
        self.assertTrue(all(compare_archived(r, reordered).values()))

    def test_unassigned_order_normalized_but_duplicates_detected(self):
        self.write('src/main/java/A.java', 'class A {}')
        self.write('src/main/java/B.java', 'class B {}')
        r = analyze(self.root)
        reordered = dict(r, state=dict(r['state'], unassigned_files=list(reversed(r['state']['unassigned_files']))))
        self.assertTrue(all(compare_archived(r, reordered).values()))
        duplicated = dict(r, state=dict(r['state'], unassigned_files=[r['state']['unassigned_files'][0]] * 2))
        self.assertFalse(compare_archived(r, duplicated)['state'])


if __name__ == '__main__':
    unittest.main()

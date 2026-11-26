"""Real node/control tests; actual graph integration is skipped if not installed."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tracemicro.langgraph_workflow import LangGraphWorkflow
from tracemicro.pilot import ROOT, load_config, make_workflow, scripted_actions
from tracemicro.providers import ScriptedProvider


def drive_nodes(runner):
    """Plain Python node harness, explicitly NOT a substitute LangGraph runtime."""
    state = runner.initial_state()
    limit = 2*state['workflow']['budget']['decisions']+4
    for _ in range(limit):
        node = state['next_node']
        state = getattr(runner, node)(state)
        if node == 'finish':
            return state
    raise AssertionError('Node routing exceeded decision-derived bound')


class GraphNodeTests(unittest.TestCase):
    def setUp(self):
        base = ROOT/'results/langgraph_development/test-tmp'
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.config = load_config('configs/petclinic_pilot.json')
        # Replace, rather than read, the real environment. Guard all socket I/O.
        self.env = patch('os.environ', {'TMP':str(base), 'TEMP':str(base),
                                       'LANGSMITH_TRACING':'false', 'LANGCHAIN_TRACING_V2':'false'})
        self.env.start()
        self.addCleanup(self.env.stop)
        for target in ['socket.create_connection','socket.socket.connect','socket.socket.connect_ex']:
            guard = patch(target, side_effect=AssertionError('Offline test attempted network'))
            guard.start()
            self.addCleanup(guard.stop)

    def runner(self, actions):
        return LangGraphWorkflow(make_workflow(self.config, ScriptedProvider(copy.deepcopy(actions))))

    def assert_matches_original(self, actions):
        original = make_workflow(self.config, ScriptedProvider(copy.deepcopy(actions))).run(self.path/'original.json')
        runner = self.runner(actions)
        final = drive_nodes(runner)
        self.assertEqual(final['workflow'], original['state'])
        # Original event semantics retained, apart from added node events/timestamps.
        def normalized(events):
            return [{k:v for k,v in e.items() if k not in {'sequence','timestamp_utc'}}
                    for e in events if e['kind'] != 'graph_node']
        self.assertEqual(normalized(final['events']), normalized(original['events']))
        return runner, final

    def test_complete_shared_correction_matches_original(self):
        runner, final = self.assert_matches_original(scripted_actions(self.config))
        self.assertEqual(final['workflow']['termination_reason'], 'basic_checks_passed')
        self.assertEqual(final['workflow']['budget'], {'decisions':0,'tool_calls':0,'revisions':0})
        self.assertEqual(len(final['workflow']['revisions']), 1)
        nodes = [e['node'] for e in final['events'] if e['kind']=='graph_node']
        self.assertEqual(nodes.count('inspect_source'), 3)
        self.assertEqual(nodes.count('inspect_dependencies'), 3)
        self.assertEqual(nodes.count('validate_submission'), 2)
        doc = runner.save(final, self.path/'harness.json', execution_engine='node_harness_not_langgraph')
        self.assertFalse(doc['live_model_run'])
        self.assertIsNone(doc['architectural_accuracy'])
        with self.assertRaises(FileExistsError):
            runner.save(final, self.path/'harness.json', execution_engine='node_harness_not_langgraph')

    def test_successful_real_actions_replayed_only_as_simulation(self):
        trace = json.loads((ROOT/'results/groq_live/pilot_progress_1.json').read_text())
        actions = [e['action'] for e in trace['events'] if e['kind']=='decision_received']
        runner, final = self.assert_matches_original(actions)
        self.assertEqual(final['workflow']['budget'], {'decisions':1,'tool_calls':0,'revisions':1})
        self.assertEqual(final['workflow']['candidate_assignments'], trace['state']['candidate_assignments'])
        self.assertEqual(final['workflow']['revisions'], [])

    def test_incomplete_failure_stays_rejected(self):
        actions = scripted_actions(self.config)
        actions[-1] = copy.deepcopy(actions[-2])
        _, final = self.assert_matches_original(actions)
        self.assertEqual(final['workflow']['termination_reason'], 'revision_budget_exhausted')
        self.assertEqual([f['code'] for f in final['workflow']['verification_findings']], ['missing_class'])

    def test_duplicate_inspection_exhausts_tool_budget(self):
        action = {'type':'inspect_dependencies','class':self.config['scope'][0]}
        _, final = self.assert_matches_original([action]*7)
        self.assertEqual(final['workflow']['termination_reason'], 'tool_budget_exhausted')
        self.assertEqual(len(final['workflow']['evidence']), 6)
        self.assertEqual(final['workflow']['budget']['decisions'], 1)

    def test_invalid_schema_and_decision_exhaustion(self):
        actions = [{'type':'submit','output':{'assignments':17}}]
        _, final = self.assert_matches_original(actions)
        self.assertEqual(final['workflow']['termination_reason'], 'script_exhausted')
        self.assertEqual(final['workflow']['verification_findings'], [{'code':'invalid_output_schema'}])
        runner = self.runner([])
        runner.core.state.budget.decisions = 0
        final = drive_nodes(runner)
        self.assertEqual(final['workflow']['termination_reason'], 'decision_budget_exhausted')

    def test_invalid_action_and_out_of_scope_are_safe(self):
        for action in [[], {'type':'unknown'}, {'type':'inspect_source','class':'invented'}]:
            runner = self.runner([action])
            final = drive_nodes(runner)
            self.assertEqual(final['workflow']['termination_reason'], 'action_or_provider_error')
            self.assertEqual(final['workflow']['evidence'], {})

    def test_node_input_is_not_mutated_and_fresh_progress_is_returned(self):
        actions = [{'type':'inspect_source','class':self.config['scope'][0]}]
        runner = self.runner(actions)
        state = runner.initial_state()
        before = copy.deepcopy(state)
        decided = runner.decide_action(state)
        self.assertEqual(state, before)
        inspected = runner.inspect_source(decided)
        self.assertEqual(len(inspected['workflow']['evidence']), 1)
        self.assertEqual(decided['workflow']['evidence'], {})

    def test_provider_error_text_not_saved(self):
        class BrokenScript(ScriptedProvider):
            def decide(self, context):
                raise RuntimeError('sensitive-test-sentinel')
        runner = LangGraphWorkflow(make_workflow(self.config, BrokenScript([])))
        final = drive_nodes(runner)
        self.assertNotIn('sensitive-test-sentinel', json.dumps(final))
        self.assertEqual(final['workflow']['termination_reason'], 'action_or_provider_error')

    def test_missing_evidence_and_invalid_shared_remain_rejected(self):
        for defect in ['missing_dependency', 'invalid_shared', 'duplicate', 'wrong_class_evidence']:
            actions = scripted_actions(self.config)
            # Submit only once; zero corrections so findings remain observable.
            complete = copy.deepcopy(actions[-1])
            if defect == 'missing_dependency':
                complete['output']['assignments'][0]['evidence'] = ['E1']
                expected = 'required_evidence_missing'
            elif defect == 'invalid_shared':
                complete['output']['assignments'][-1]['shared'] = False
                expected = 'invalid_shared_declaration'
            elif defect == 'duplicate':
                complete['output']['assignments'].append(copy.deepcopy(complete['output']['assignments'][0]))
                expected = 'duplicate_class_record'
            else:
                complete['output']['assignments'][0]['evidence'] = ['E3','E4']
                expected = 'invalid_or_missing_evidence'
            runner = self.runner(actions[:6]+[complete])
            runner.core.state.budget.revisions = 0
            final = drive_nodes(runner)
            self.assertEqual(final['workflow']['termination_reason'], 'revision_budget_exhausted')
            self.assertIn(expected, [f['code'] for f in final['workflow']['verification_findings']])

    def test_non_scripted_provider_rejected_before_any_decision(self):
        class UnexpectedProvider:
            kind = 'groq_live'
            def decide(self, context):
                raise AssertionError('Must not call provider')
        with self.assertRaises(ValueError):
            LangGraphWorkflow(make_workflow(self.config, UnexpectedProvider()))

    def test_existing_path_refused_before_compile_or_decisions(self):
        runner = self.runner(scripted_actions(self.config))
        path = self.path/'keep.json'
        path.write_text('keep')
        with patch.object(runner, 'compile', side_effect=AssertionError('must not compile')):
            with self.assertRaises(ValueError):
                runner.run(path)
        self.assertEqual(path.read_text(), 'keep')
        self.assertEqual(runner.core.state.budget.decisions, 8)

    @unittest.skipUnless(importlib.util.find_spec('langgraph'), 'LangGraph not installed: actual runtime UNVERIFIED')
    def test_actual_langgraph_corrected_and_direct_success(self):
        for index, actions in enumerate([scripted_actions(self.config), scripted_actions(self.config)[:-2]+scripted_actions(self.config)[-1:]]):
            doc = self.runner(actions).run(self.path/f'graph{index}.json')
            self.assertEqual(doc['execution_engine'], 'langgraph')
            self.assertEqual(doc['state']['termination_reason'], 'basic_checks_passed')
            self.assertFalse(doc['live_model_run'])

    @unittest.skipUnless(importlib.util.find_spec('langgraph'), 'LangGraph not installed: actual runtime UNVERIFIED')
    def test_actual_langgraph_budget_stop_and_failure(self):
        action = {'type':'inspect_dependencies','class':self.config['scope'][0]}
        doc = self.runner([action]*7).run(self.path/'graph_budget.json')
        self.assertEqual(doc['state']['termination_reason'], 'tool_budget_exhausted')
        actions = scripted_actions(self.config)
        actions[-1] = copy.deepcopy(actions[-2])
        doc = self.runner(actions).run(self.path/'graph_failure.json')
        self.assertEqual(doc['state']['termination_reason'], 'revision_budget_exhausted')


if __name__ == '__main__':
    unittest.main()

"""Run credential-free tests and save an explicitly labelled node-harness trace.

This works before LangGraph installation. It never claims to run StateGraph.
Actual StateGraph integration tests run only when the dependency is installed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, help='New workspace-local results directory')
    args = parser.parse_args()
    folder = (ROOT/args.output_dir).resolve()
    folder.relative_to(ROOT)
    # Atomic create: preserve every earlier run, including its logs.
    folder.mkdir(parents=True, exist_ok=False)
    tmp = folder/'test-tmp'
    tmp.mkdir()
    tempfile.tempdir = str(tmp)
    originals = [ROOT/'tracemicro/workflow.py', ROOT/'tracemicro/evidence.py',
                 ROOT/'tracemicro/pilot.py', ROOT/'pilot_workflow.py',
                 *sorted((ROOT/'results/groq_live').glob('*.json'))]
    def hashes():
        return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in originals}
    before = hashes()
    # clear=True via replacement: never inspect the real key/environment values.
    with patch('os.environ', {'TMP':str(tmp), 'TEMP':str(tmp),
                             'LANGSMITH_TRACING':'false', 'LANGCHAIN_TRACING_V2':'false'}):
        with (folder/'tests.log').open('x', encoding='utf-8') as log:
            suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'))
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
        from test_langgraph_workflow import drive_nodes
        from tracemicro.langgraph_workflow import LangGraphWorkflow
        from tracemicro.pilot import load_config, make_workflow, scripted_actions
        from tracemicro.providers import ScriptedProvider
        config = load_config('configs/petclinic_pilot.json')
        scenarios = {'corrected':scripted_actions(config)}
        saved = json.loads((ROOT/'results/groq_live/pilot_progress_1.json').read_text())
        scenarios['replayed_success'] = [e['action'] for e in saved['events'] if e['kind']=='decision_received']
        failed = json.loads((ROOT/'results/groq_live/pilot_structured_1.json').read_text())
        scenarios['replayed_failure'] = [e['action'] for e in failed['events'] if e['kind']=='decision_received']
        outcomes = {}
        with patch('socket.socket', side_effect=AssertionError('Offline harness attempted network')):
            for name, actions in scenarios.items():
                runner = LangGraphWorkflow(make_workflow(config, ScriptedProvider(actions)))
                final = drive_nodes(runner)
                doc = runner.save(final, folder/(name+'.json'), execution_engine='node_harness_not_langgraph')
                outcomes[name] = {'termination_reason':doc['state']['termination_reason'],
                                  'remaining_budget':doc['state']['budget']}
    after = hashes()
    summary = {'discovered':result.testsRun,
               'passed':result.testsRun-len(result.skipped)-len(result.errors)-len(result.failures),
               'skipped':len(result.skipped), 'failures':len(result.failures), 'errors':len(result.errors),
               'simulated_node_harness_outcomes':outcomes,
               'preserved':before == after, 'before_sha256':before, 'after_sha256':after}
    (folder/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if not k.endswith('sha256')},indent=2))
    if not result.wasSuccessful() or before != after:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

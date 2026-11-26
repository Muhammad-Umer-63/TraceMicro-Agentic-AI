"""Small configurable development pilot, not reference-scored evaluation."""
import copy
from dataclasses import asdict
import json
from pathlib import Path

from .evidence import EvidenceStore
from .workflow import Budget, Workflow
from .providers import GroqConfig

ROOT=Path(__file__).resolve().parents[1]


def inside(path):
    path=Path(path)
    path=(ROOT/path).resolve() if not path.is_absolute() else path.resolve()
    path.relative_to(ROOT)
    return path


def load_config(path):
    config=json.loads(inside(path).read_text(encoding='utf-8'))
    if not isinstance(config,dict): raise ValueError('Pilot config must be an object')
    if set(config) != {'name','scope','services','required_evidence_tools','limits'}:
        raise ValueError('Unknown/missing pilot fields; credentials do not belong in pilot config')
    scope,services=config['scope'],config['services']
    if not isinstance(scope,list) or not 2<=len(scope)<=3 or any(not isinstance(c,str) for c in scope) or len(set(scope))!=len(scope):
        raise ValueError('Pilot scope requires two or three unique classes')
    if not isinstance(services,list) or len(services)<2 or any(not isinstance(s,str) or not s.strip() for s in services) or len(set(services))!=len(services):
        raise ValueError('Pilot requires at least two unique candidate labels')
    if not isinstance(config['required_evidence_tools'],list) or sorted(config['required_evidence_tools']) != ['inspect_dependencies','inspect_source']:
        raise ValueError('Pilot requires both source and dependency evidence')
    limits=config['limits']
    if not isinstance(limits,dict): raise ValueError('Pilot limits must be an object')
    if set(limits) != {'model_requests','tool_calls','max_output_tokens','revisions','timeout_seconds','max_input_bytes'}:
        raise ValueError('Unknown/missing limit fields')
    GroqConfig(model='configuration-check-only',max_output_tokens=limits['max_output_tokens'],
               timeout_seconds=limits['timeout_seconds'],max_requests=limits['model_requests'],
               max_input_bytes=limits['max_input_bytes'])
    Budget(limits['model_requests'],limits['tool_calls'],limits['revisions'])
    if limits['tool_calls']<2*len(scope) or limits['tool_calls']>limits['model_requests']:
        raise ValueError('Tool budget must cover both tools per class within request budget')
    if limits['model_requests']<2*len(scope)+1+limits['revisions']:
        raise ValueError('Request budget must allow required inspections, submission and configured corrections')
    return config


def make_store():
    saved=json.loads((ROOT/'results/dependency_baseline/petclinic_k5.json').read_text())
    return EvidenceStore(ROOT,'sample_petclinic','results/dependency_baseline/petclinic_raw.json',
                         saved['snapshot']['eligible_java_files_sha256'],saved['raw_analyzer_sha256'])


def make_workflow(config,provider):
    limits=config['limits']
    return Workflow(make_store(),provider,config['scope'],config['services'],
                    Budget(limits['model_requests'],limits['tool_calls'],limits['revisions']),
                    required_evidence_tools=config['required_evidence_tools'],
                    run_metadata={'pilot':config,'scope_status':'Development subset; candidate labels are not ground truth',
                                  'provider_kind':provider.kind,
                                  'provider_config':asdict(provider.config) if hasattr(provider,'config') else None})


def scripted_actions(config):
    """Hand-authored protocol pattern: intentionally incomplete, then corrected.

    Labels are synthetic; this is not a classifier or a ground-truth mapping.
    """
    actions=[]
    rows=[]
    for index,name in enumerate(config['scope']):
        actions.extend([{'type':'inspect_source','class':name},
                        {'type':'inspect_dependencies','class':name}])
        shared=index==len(config['scope'])-1
        services=config['services'][:2] if shared else [config['services'][index%len(config['services'])]]
        rows.append({'class':name,'services':services,'shared':shared,
                     'evidence':['E'+str(2*index+1),'E'+str(2*index+2)]})
    actions.append({'type':'submit','output':{'assignments':copy.deepcopy(rows[:-1])}})
    actions.append({'type':'submit','output':{'assignments':rows}})
    return actions

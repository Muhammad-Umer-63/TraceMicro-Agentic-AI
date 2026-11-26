"""Optional LangGraph orchestration; tools/validation remain the existing core.

Imports LangGraph only when compiling. Node methods are independently testable
without substituting a fake LangGraph runtime. No checkpoint/resume or retries.
"""
import copy
import json
from dataclasses import asdict
from importlib.metadata import version
from typing import TypedDict

from .providers import GroqProvider, ProviderError, ScriptedProvider
from .workflow import Budget, State, Workflow, validate_output


class GraphState(TypedDict):
    # JSON-shaped copies; graph state is authoritative between nodes.
    workflow: dict
    events: list
    action: object
    next_node: str


class LangGraphWorkflow:
    def __init__(self, core: Workflow, *, allow_live=False):
        if type(allow_live) is not bool:
            raise ValueError('allow_live must be boolean')
        if not isinstance(core.provider, (ScriptedProvider, GroqProvider)):
            raise ValueError('Use the existing scripted or Groq provider')
        if core.provider.kind == 'groq_live' and not allow_live:
            raise ValueError('Live graph execution requires explicit allow_live=True')
        if core.state.status != 'ready' or core.events:
            raise ValueError('Use a fresh, unstarted workflow')
        self.core = core
        self._used = False

    def initial_state(self):
        return {'workflow':asdict(self.core.state), 'events':[],
                'action':None, 'next_node':'decide_action'}

    def _load(self, graph_state):
        values = copy.deepcopy(graph_state['workflow'])
        values['budget'] = Budget(**values['budget'])
        self.core.state = State(**values)
        self.core.events = copy.deepcopy(graph_state['events'])

    def _enter(self, name, graph_state):
        self._load(graph_state)
        self.core.event('graph_node', node=name)

    def _pack(self, action=None, next_node='decide_action'):
        if self.core.state.status == 'stopped' and next_node != 'end':
            next_node = 'finish'
        return {'workflow':asdict(self.core.state),
                'events':copy.deepcopy(self.core.events),
                'action':copy.deepcopy(action), 'next_node':next_node}

    def _error(self, error):
        # Same safe error policy as Workflow.run: never save exception text.
        if isinstance(error, StopIteration):
            self.core.stop('script_exhausted')
            return
        details = {}
        if isinstance(error, ProviderError):
            details = {'code':error.code, 'http_status':error.status,
                       'error_source':error.source}
            if error.provider_error is not None:
                details['provider_error'] = error.provider_error
        self.core.event('error', error_type=type(error).__name__, **details)
        self.core.stop('action_or_provider_error')

    def decide_action(self, graph_state):
        self._enter('decide_action', graph_state)
        state = self.core.state
        if state.status == 'ready':
            state.status = 'investigating'
            self.core.event('started', mode=self.core.provider.kind,
                            scope=state.scope, budget=asdict(state.budget))
        if state.budget.decisions == 0:
            self.core.stop('decision_budget_exhausted')
            return self._pack()
        state.budget.decisions -= 1
        context = self.core.context()  # includes fresh per-class progress
        self.core.event('decision_requested', context=context)
        try:
            action = self.core.provider.decide(copy.deepcopy(context))
            self.core.event('decision_received', action=action)
            if not isinstance(action, dict):
                raise ValueError('Action must be an object')
            routes = {'inspect_source':'inspect_source',
                      'inspect_dependencies':'inspect_dependencies',
                      'submit':'validate_submission'}
            if action.get('type') not in routes:
                raise ValueError('Unknown action type')
            return self._pack(action, routes[action['type']])
        except Exception as error:
            self._error(error)
            return self._pack()

    def _inspect(self, graph_state, tool):
        self._enter(tool, graph_state)
        action = graph_state['action']
        try:
            allowed = {'type','class','start_line','end_line'} if tool == 'inspect_source' else {'type','class'}
            if action.get('type') != tool or set(action)-allowed or not {'type','class'} <= set(action):
                raise ValueError('Invalid tool arguments')
            if self.core.state.budget.tool_calls == 0:
                self.core.stop('tool_budget_exhausted')
                return self._pack()
            self.core.state.budget.tool_calls -= 1
            if action['class'] not in self.core.state.scope:
                raise ValueError('Class outside investigation scope')
            if tool == 'inspect_source':
                result = self.core.store.inspect_source(action['class'], action.get('start_line',1), action.get('end_line'))
            else:
                result = self.core.store.inspect_dependencies(action['class'])
            evidence_id = 'E'+str(len(self.core.state.evidence)+1)
            self.core.state.evidence[evidence_id] = result
            self.core.event('tool_result', arguments=action, evidence_id=evidence_id, result=result)
        except Exception as error:
            self._error(error)
        return self._pack()

    def inspect_source(self, graph_state):
        return self._inspect(graph_state, 'inspect_source')

    def inspect_dependencies(self, graph_state):
        return self._inspect(graph_state, 'inspect_dependencies')

    def validate_submission(self, graph_state):
        self._enter('validate_submission', graph_state)
        action = graph_state['action']
        state = self.core.state
        try:
            if set(action) != {'type','output'} or action['type'] != 'submit':
                raise ValueError('Invalid submit action')
            findings = validate_output(action['output'], state.scope, state.services,
                                       state.evidence, self.core.required_evidence_tools)
            previous = copy.deepcopy(state.candidate_assignments)
            candidate = action['output'].get('assignments',[]) if isinstance(action['output'],dict) else []
            state.candidate_assignments = copy.deepcopy(candidate)
            state.verification_findings = findings
            self.core.event('verification', candidate=action['output'], findings=findings,
                            interpretation='Basic schema/evidence-reference checks only, not architectural correctness')
            if previous:
                state.revisions.append({'before':previous, 'after':copy.deepcopy(candidate)})
            if not findings:
                self.core.stop('basic_checks_passed')
            elif state.budget.revisions == 0:
                self.core.stop('revision_budget_exhausted')
            else:
                state.budget.revisions -= 1
        except Exception as error:
            self._error(error)
        return self._pack()

    def finish(self, graph_state):
        self._enter('finish', graph_state)
        return self._pack(next_node='end')

    def compile(self):
        from langgraph.graph import END, START, StateGraph
        graph = StateGraph(GraphState)
        graph.add_node('decide_action', self.decide_action)
        graph.add_node('inspect_source', self.inspect_source)
        graph.add_node('inspect_dependencies', self.inspect_dependencies)
        graph.add_node('validate_submission', self.validate_submission)
        graph.add_node('finish', self.finish)
        graph.add_edge(START, 'decide_action')
        action_routes = {name:name for name in ['inspect_source',
                         'inspect_dependencies','validate_submission','finish']}
        graph.add_conditional_edges('decide_action', lambda state: state['next_node'], action_routes)
        continuation = {'decide_action':'decide_action', 'finish':'finish'}
        for name in ['inspect_source','inspect_dependencies','validate_submission']:
            graph.add_conditional_edges(name, lambda state: state['next_node'], continuation)
        graph.add_edge('finish', END)
        # No persistence, cache, retry policy or LangSmith service is configured.
        return graph.compile()

    def document(self, graph_state, *, execution_engine):
        """Shared trace writer input for real graph vs explicitly labelled harness."""
        self._load(graph_state)
        return {'run_kind':self.core.provider.kind,
                'live_model_run':self.core.provider.kind == 'groq_live' and getattr(self.core.provider,'http_requests_sent',0)>0,
                'execution_engine':execution_engine,
                'langgraph_version':version('langgraph') if execution_engine == 'langgraph' else None,
                'provenance':{'source_snapshot':self.core.store.snapshot,
                              'dependency_json_sha256':self.core.store.graph_sha256,
                              'identity_limit':'filename/package mapping, not compiler resolution'},
                'state':asdict(self.core.state), 'events':self.core.events,
                'run_config':copy.deepcopy(self.core.run_metadata),
                'model_usage':copy.deepcopy(getattr(self.core.provider,'records',None)),
                'architectural_accuracy':None}

    def save(self, graph_state, output_path, *, execution_engine):
        target = self.core.store._inside(output_path)
        document = self.document(graph_state, execution_engine=execution_engine)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as stream:
            json.dump(document, stream, indent=2)
            stream.write('\n')
        return document

    def run(self, output_path):
        target = self.core.store._inside(output_path)
        if target.exists():
            raise ValueError('Refusing to overwrite trace: '+str(target))
        if self._used:
            raise ValueError('Graph runner is single-use')
        compiled = self.compile()  # missing dependency fails before any decisions
        self._used = True
        # Each decision needs <=2 nodes; allow the budget check and finish too.
        limit = 2*self.core.state.budget.decisions+4
        # LangSmith is a transitive dependency; explicitly disable tracing even
        # if a caller has externally enabled it. No client/key is constructed.
        from langsmith import tracing_context
        with tracing_context(enabled=False):
            final = compiled.invoke(self.initial_state(), {'recursion_limit':limit,
                                                          'callbacks':[]})
        return self.save(final, target, execution_engine='langgraph')

"""Groq chat adapter; live network and environment-key access require explicit opt-in."""
from dataclasses import dataclass
from typing import Protocol
import json
import os
import socket
import time
import re
from email.utils import parsedate_to_datetime
from datetime import timezone
from .action_schema import response_schema
import urllib.error
import urllib.request


class Provider(Protocol):
    kind: str
    def decide(self, context: dict) -> dict: ...


class ScriptedProvider:
    kind = 'scripted_test_only'
    def __init__(self, actions):
        self.actions = iter(actions)

    def decide(self, context):
        return next(self.actions)


CHAT_ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions'
MODELS_ENDPOINT = 'https://api.groq.com/openai/v1/models'
USER_AGENT = 'TraceMicro-Diagnostic/1.0'


class ProviderError(RuntimeError):
    def __init__(self, code, status=None, source='provider', rate_limits=None, provider_error=None):
        self.code, self.status, self.source = code, status, source
        self.rate_limits = rate_limits or {}
        self.provider_error = provider_error
        super().__init__(code)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError('redirect_refused', code, source='http_response')


RATE_COUNT_HEADERS = ('x-ratelimit-limit-requests','x-ratelimit-remaining-requests',
                      'x-ratelimit-limit-tokens','x-ratelimit-remaining-tokens')


def safe_rate_limits(headers):
    """Read only allowlisted names; retain typed counts/durations, never all headers."""
    result={}
    if headers is None: return result
    for name in RATE_COUNT_HEADERS:
        value=headers.get(name)
        if isinstance(value,str) and re.fullmatch(r'[0-9]{1,12}',value.strip()):
            result[name]=int(value.strip())
    for name in ('x-ratelimit-reset-requests','x-ratelimit-reset-tokens'):
        value=headers.get(name)
        if isinstance(value,str) and len(value)<=64 and re.fullmatch(r'(?:[0-9]+(?:\.[0-9]+)?(?:ms|s|m|h))+',value.strip()):
            result[name]=value.strip()
    value=headers.get('retry-after')
    if isinstance(value,str) and len(value)<=64:
        value=value.strip()
        if re.fullmatch(r'[0-9]{1,8}(?:\.[0-9]{1,3})?',value):
            result['retry_after_seconds']=float(value)
        else:
            try:
                parsed=parsedate_to_datetime(value)
                if parsed.tzinfo is not None:
                    result['retry_after_utc']=parsed.astimezone(timezone.utc).isoformat()
            except (ValueError,TypeError,OverflowError): pass
    return result


@dataclass(frozen=True)
class HTTPResult:
    body: bytes
    rate_limits: dict


ERROR_CODES = {'json_validate_failed','tool_use_failed','context_length_exceeded',
               'invalid_api_key','model_not_found','rate_limit_exceeded','invalid_parameter',
               'invalid_json_schema','unsupported_schema','unsupported_response_format'}
ERROR_TYPES = {'invalid_request_error','authentication_error','permission_error',
               'rate_limit_error','server_error','invalid_request','invalid_api_key'}


def rejected_generation_structure(value, constraints=None):
    """Return only capped counts, booleans and fixed enums; never content/keys."""
    result = {'present':True}
    if not isinstance(value,str):
        return {**result,'representation':'non_string','parsed':False}
    result.update(representation='string',characters_capped=min(len(value),8192))
    if not value.strip():
        return {**result,'parsed':False,'reason':'empty_generation'}
    if len(value)>8192:
        return {**result,'parsed':False,'reason':'size_limit'}
    try:
        root=json.loads(value)
    except (ValueError,RecursionError):
        return {**result,'parsed':False,'reason':'json_syntax_or_depth'}
    result.update(parsed=True,root_is_object=isinstance(root,dict))
    if not isinstance(root,dict): return result
    result['root_keys_count_capped']=min(len(root),32)
    result['exact_action_envelope']=set(root)=={'action'}
    action=root.get('action')
    result['inner_action_is_object']=isinstance(action,dict)
    if not isinstance(action,dict): return result
    kind=action.get('type')
    result['action_type']=kind if isinstance(kind,str) and kind in {'inspect_source','inspect_dependencies','submit'} else 'other_or_missing'
    result['action_fields_match']=set(action)==({'type','output'} if kind=='submit' else {'type','class'})
    output=action.get('output')
    rows=output.get('assignments') if isinstance(output,dict) else None
    result['assignments_is_array']=isinstance(rows,list)
    if not isinstance(rows,list): return result
    result['assignment_count_capped']=min(len(rows),32)
    result['row_scan_capped']=len(rows)>32
    scope=set((constraints or {}).get('scope',[]))
    services=set((constraints or {}).get('services',[]))
    evidence=(constraints or {}).get('evidence',{})
    result['constraints_available']=constraints is not None
    counts={'invalid_row_shapes':0,'out_of_scope_classes':0,'invalid_service_values':0,
            'invalid_evidence_references':0,'invalid_shared_declarations':0}
    seen=set()
    for row in rows[:32]:
        if not isinstance(row,dict) or set(row)!={'class','services','shared','evidence'}:
            counts['invalid_row_shapes']+=1; continue
        name=row['class']
        if isinstance(name,str): seen.add(name)
        if scope and (not isinstance(name,str) or name not in scope): counts['out_of_scope_classes']+=1
        labels=row['services']
        valid_labels=isinstance(labels,list) and bool(labels) and all(isinstance(s,str) for s in labels[:32]) and len(labels)<=32
        if not valid_labels:
            counts['invalid_service_values']+=1
        else:
            counts['invalid_service_values']+=sum(bool(services) and s not in services for s in labels)
            if type(row['shared']) is not bool or row['shared']!=(len(set(labels))>1): counts['invalid_shared_declarations']+=1
        refs=row['evidence']
        if not isinstance(refs,list) or len(refs)>32:
            counts['invalid_evidence_references']+=1
        elif constraints is not None:
            counts['invalid_evidence_references']+=sum(not isinstance(e,str) or evidence.get(e)!=name for e in refs)
    result.update({key:min(value,1024) for key,value in counts.items()})
    if scope: result['missing_scoped_classes_capped']=min(len(scope-seen),32)
    return result


def safe_provider_error(error, secret, constraints=None):
    """Bounded in-memory read; return fixed classifications/enum values only."""
    try:
        raw=error.read(16385)
        if not isinstance(raw,bytes): return {'classification':'error_body_unavailable'}
        if len(raw)>16384: return {'classification':'error_body_too_large'}
        if not raw: return {'classification':'error_body_empty'}
        try: body=json.loads(raw.decode('utf-8'))
        except (ValueError,UnicodeError): return {'classification':'error_body_not_json'}
        detail=body.get('error') if isinstance(body,dict) else None
        if not isinstance(detail,dict): return {'classification':'error_object_unavailable'}
        result={'classification':'unrecognized_provider_error'}
        for field,allowed in [('code',ERROR_CODES),('type',ERROR_TYPES)]:
            value=detail.get(field)
            if isinstance(value,str) and value in allowed and secret not in value:
                result[field]=value
        if result.get('code')=='json_validate_failed': result['classification']='json_output_rejected'
        elif result.get('code') in {'invalid_json_schema','unsupported_schema','unsupported_response_format'}:
            result['classification']='schema_request_rejected'
        elif result.get('code')=='context_length_exceeded': result['classification']='context_limit_reported'
        elif len(result)>1: result['classification']='allowlisted_provider_error'
        if 'failed_generation' in detail:
            result['rejected_generation_structure']=rejected_generation_structure(detail['failed_generation'],constraints)
        elif 'failed_generation' in body:
            result['rejected_generation_structure']=rejected_generation_structure(body['failed_generation'],constraints)
        return result
    except Exception:
        return {'classification':'error_body_unavailable'}
    finally:
        try: error.close()
        except Exception: pass


def http_transport(method, url, headers, body, timeout):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    # No redirects or implicit environment proxy forwarding of the credential.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ProviderError('response_too_large')
        return HTTPResult(raw,safe_rate_limits(response.headers))


@dataclass(frozen=True)
class GroqConfig:
    model: str
    endpoint: str = CHAT_ENDPOINT
    temperature: float = 0.0
    max_output_tokens: int = 512
    timeout_seconds: float = 15.0
    max_requests: int = 2
    max_input_bytes: int = 24000
    min_interval_seconds: float = 0
    max_pacing_wait_seconds: float = 0
    structured_outputs: bool = False

    def __post_init__(self):
        if not isinstance(self.model,str) or not self.model.strip() or self.endpoint != CHAT_ENDPOINT:
            raise ValueError('Explicit model and official Groq chat endpoint required')
        if type(self.structured_outputs) is not bool:
            raise ValueError('structured_outputs must be boolean')
        if self.structured_outputs and self.model != 'openai/gpt-oss-20b':
            raise ValueError('This strict workflow adapter is enabled only for the documented openai/gpt-oss-20b model')
        if not 0 <= self.temperature <= 2 or type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 2048:
            raise ValueError('Invalid generation settings')
        if not 0 < self.timeout_seconds <= 30 or type(self.max_requests) is not int or not 1 <= self.max_requests <= 8:
            raise ValueError('Invalid timeout or request cap')
        if type(self.max_input_bytes) is not int or not 1 <= self.max_input_bytes <= 64000:
            raise ValueError('Invalid request-body cap')
        if not 0 <= self.min_interval_seconds <= 60 or not 0 <= self.max_pacing_wait_seconds <= 420:
            raise ValueError('Pacing interval must be 0..60s and total wait budget 0..420s')
        if self.min_interval_seconds and self.max_pacing_wait_seconds < self.min_interval_seconds:
            raise ValueError('Pacing wait budget must cover at least one interval')


class GroqProvider:
    def __init__(self, config, *, allow_live=False, transport=None, clock=None, sleeper=None):
        self.config = config
        self._transport = transport or http_transport
        self._enabled = allow_live or transport is not None
        self.kind = 'groq_simulated_http' if transport is not None else ('groq_live' if allow_live else 'groq_unconnected')
        self.records = []
        self.request_count = 0
        self.model_list_requests = 0
        self.http_requests_sent = 0
        self._clock = clock or time.monotonic
        self._sleep = sleeper or time.sleep
        self._last_finished = None
        self.pacing_wait_total = 0
        self.last_pacing_wait = 0
        self.last_rate_limits = {}

    def prepare_request(self, messages):
        return {'provider':'groq','endpoint':self.config.endpoint,
                'body':{'model':self.config.model,'messages':messages,
                        'temperature':self.config.temperature,
                        'max_completion_tokens':self.config.max_output_tokens,
                        'response_format':response_schema() if self.config.structured_outputs else {'type':'json_object'}, 'stream':False},
                'transport_enabled':self._enabled}

    def _pace(self):
        self.last_pacing_wait=0
        if not self.config.min_interval_seconds or self._last_finished is None: return
        wait=max(0,self.config.min_interval_seconds-(self._clock()-self._last_finished))
        if self.pacing_wait_total+wait > self.config.max_pacing_wait_seconds:
            raise ProviderError('pacing_wait_budget_exhausted')
        if wait:
            self._sleep(wait)
            self.pacing_wait_total+=wait
            self.last_pacing_wait=wait

    def _request(self, method, url, body=None):
        self.last_rate_limits={}
        self.last_pacing_wait=0
        if not self._enabled:
            raise ProviderError('live_transport_not_authorized')
        # Read only this named environment variable, only when a request is requested.
        key = os.environ.get('GROQ_API_KEY')
        if not key or not key.strip():
            raise ProviderError('missing_api_key')
        if '\r' in key or '\n' in key:
            raise ProviderError('invalid_api_key_format')
        headers = {'Authorization':'Bearer '+key,'Content-Type':'application/json',
                   'User-Agent':USER_AGENT}
        self.last_rate_limits={}
        self.last_pacing_wait=0
        try:
            self._pace()
            self.http_requests_sent += 1
            try:
                raw = self._transport(method,url,headers,body,self.config.timeout_seconds)
            finally:
                self._last_finished=self._clock()
            if isinstance(raw,HTTPResult):
                self.last_rate_limits={k:v for k,v in raw.rate_limits.items() if key not in str(v)}
                raw=raw.body
            # A service or simulation might echo credentials; never propagate them.
            text = raw.decode('utf-8').replace(key,'[REDACTED]')
            decoded = json.loads(text)
            def redact(value):
                if isinstance(value,str): return value.replace(key,'[REDACTED]')
                if isinstance(value,list): return [redact(v) for v in value]
                if isinstance(value,dict): return {redact(k):redact(v) for k,v in value.items()}
                return value
            return redact(decoded)
        except ProviderError:
            raise
        except urllib.error.HTTPError as error:
            code={400:'bad_request',401:'authentication_failed',403:'permission_denied',404:'not_found',
                  429:'rate_limited'}.get(error.code,'http_error')
            # HTTP status does not establish which service/intermediary generated it.
            raise ProviderError(code,error.code,source='http_response',
                                rate_limits={k:v for k,v in safe_rate_limits(error.headers).items() if key not in str(v)},
                                provider_error=safe_provider_error(error,key,getattr(self,'_diagnostic_constraints',None))) from None
        except PermissionError:
            raise ProviderError('local_permission_denied',source='local_os') from None
        except (TimeoutError,socket.timeout):
            raise ProviderError('timeout',source='transport') from None
        except urllib.error.URLError as error:
            if isinstance(error.reason,PermissionError):
                raise ProviderError('local_permission_denied',source='local_os') from None
            raise ProviderError('timeout' if isinstance(error.reason,TimeoutError) else 'network_error',source='transport') from None
        except (UnicodeError,json.JSONDecodeError):
            raise ProviderError('invalid_response_json') from None
        except Exception:
            raise ProviderError('transport_error') from None

    def list_models(self):
        if self.model_list_requests >= 1:
            raise ProviderError('model_list_request_cap')
        self.model_list_requests += 1
        response = self._request('GET',MODELS_ENDPOINT)
        if not isinstance(response,dict) or not isinstance(response.get('data'),list):
            raise ProviderError('invalid_model_list')
        return sorted({r['id'] for r in response['data'] if isinstance(r,dict) and isinstance(r.get('id'),str)})

    def structured_instructions(self):
        return (
            'Return exactly {"action": <one action object>}. The action examples describe only the inner object. Its mandatory type is inspect_source, inspect_dependencies or submit. Inspection objects contain only type/class and use default source ranges. Use exact class names and real tool evidence IDs; preserve shared-class rules.',
            'Return the strict-schema envelope {"action": <one workflow action>}. The mandatory type field belongs to the inner action object. Follow the provided JSON schema and inner action examples. No markdown, hidden reasoning, invented evidence IDs or extra fields. Shared classes use one record with shared=true and multiple services.')

    def decide(self, context):
        if not self._enabled: raise ProviderError('live_transport_not_authorized')
        if self.request_count >= self.config.max_requests: raise ProviderError('provider_request_cap')
        state=context.get('state',{})
        self._diagnostic_constraints={'scope':state.get('scope',[]),'services':state.get('services',[]),
            'evidence':{eid:record.get('class') for eid,record in state.get('evidence',{}).items()}}
        if self.config.structured_outputs:
            context=dict(context)
            context['instruction']=self.structured_instructions()[0]
        messages=[{'role':'system','content':'Return exactly one JSON action object with a mandatory top-level string field "type", equal to inspect_source, inspect_dependencies or submit. No markdown or hidden reasoning. Follow action_schema object examples, not the whole examples map. Tools are local actions, not native function calls. No invented evidence IDs. Shared classes use one record with shared=true and multiple service labels.'},
                  {'role':'user','content':json.dumps(context,separators=(',',':'))}]
        if self.config.structured_outputs:
            messages[0]['content']=self.structured_instructions()[1]
        body=json.dumps(self.prepare_request(messages)['body']).encode('utf-8')
        if len(body)>self.config.max_input_bytes: raise ProviderError('input_size_cap')
        self.request_count += 1
        record={'request_number':self.request_count,'requested_model':self.config.model,
                'max_completion_tokens':self.config.max_output_tokens,'input_bytes':len(body),
                'temperature':self.config.temperature,'timeout_seconds':self.config.timeout_seconds,
                'system_instruction':messages[0]['content'],
                'response_format':self.prepare_request([])['body']['response_format'],
                'wire_instruction':context.get('instruction'),
                'usage':None,'status':'started','response_json_received':False,
                'action_json_received':False}
        start=time.monotonic()
        try:
            response=self._request('POST',self.config.endpoint,body)
            record['response_json_received']=True
            if not isinstance(response,dict): raise ProviderError('invalid_response_shape')
            usage=response.get('usage')
            if isinstance(usage,dict):
                record['usage']={k:v for k,v in usage.items() if k in {'prompt_tokens','completion_tokens','total_tokens'} and type(v) is int and v>=0}
            returned=response.get('model')
            if isinstance(returned,str): record['returned_model']=returned
            choices=response.get('choices')
            if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict):
                raise ProviderError('invalid_response_shape')
            choice=choices[0]
            finish=choice.get('finish_reason')
            record['finish_reason']=finish if finish in ('stop','length','content_filter','tool_calls') else 'other'
            message=choice.get('message')
            if choice.get('finish_reason')=='content_filter' or (isinstance(message,dict) and message.get('refusal')):
                record['refusal']=True
                raise ProviderError('provider_refusal')
            if choice.get('finish_reason') != 'stop':
                raise ProviderError('truncated_or_nonstop_response')
            record['finish_reason']='stop'
            if not isinstance(message,dict) or message.get('tool_calls') or not isinstance(message.get('content'),str):
                raise ProviderError('invalid_response_content')
            try: action=json.loads(message['content'])
            except json.JSONDecodeError: raise ProviderError('invalid_action_json') from None
            record['action_json_received']=True
            if self.config.structured_outputs:
                if not isinstance(action,dict) or set(action)!={'action'} or not isinstance(action['action'],dict):
                    raise ProviderError('invalid_structured_envelope')
                action=action['action']
            # Record structural facts only, never arbitrary rejected content or keys.
            record['action_shape'] = {
                'is_object':isinstance(action,dict),
                'has_type':isinstance(action,dict) and 'type' in action,
                'type_is_string':isinstance(action,dict) and isinstance(action.get('type'),str),
                'type_allowed':isinstance(action,dict) and isinstance(action.get('type'),str)
                               and action['type'] in {'inspect_source','inspect_dependencies','submit'}}
            if not record['action_shape']['type_allowed']:
                raise ProviderError('invalid_action_shape')
            record['status']='parsed'
            return action
        except ProviderError as error:
            self.last_rate_limits=error.rate_limits or self.last_rate_limits
            record.update(status='failed',error_code=error.code,http_status=error.status,error_source=error.source)
            if error.provider_error is not None:
                record['provider_error']=error.provider_error
            if self.config.structured_outputs and error.status==400:
                record['structured_output_status']='request_rejected_no_fallback'
            raise
        finally:
            record['rate_limits']=self.last_rate_limits
            record['pacing_wait_seconds']=self.last_pacing_wait
            record['pacing_wait_total_seconds']=self.pacing_wait_total
            record['elapsed_seconds']=round(time.monotonic()-start,6)
            self.records.append(record)

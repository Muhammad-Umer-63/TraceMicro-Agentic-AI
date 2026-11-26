"""Strict Groq wire schema; workflow still validates semantic/action arguments."""


def closed(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def response_schema(allowed_services=None, *, allowed_actions=None):
    actions = ('inspect_source','inspect_dependencies','submit') if allowed_actions is None else allowed_actions
    if not isinstance(actions,(list,tuple)) or not actions or \
       any(a not in ('inspect_source','inspect_dependencies','submit') for a in actions) or \
       len(set(actions)) != len(actions):
        raise ValueError('Unknown or duplicate allowed action')
    service = {'type':'string'}
    if allowed_services is not None:
        if not isinstance(allowed_services,(list,tuple)) or not allowed_services or \
           any(not isinstance(s,str) or not s.strip() for s in allowed_services) or \
           len(set(allowed_services)) != len(allowed_services):
            raise ValueError('Allowed services must be unique nonempty strings')
        service['enum'] = list(allowed_services)
    row=closed({'class':{'type':'string'},
                'services':{'type':'array','items':service},
                'shared':{'type':'boolean'},
                'evidence':{'type':'array','items':{'type':'string'}}})
    branches=[closed({'type':{'type':'string','enum':[name]},'class':{'type':'string'}})
              for name in ['inspect_source','inspect_dependencies'] if name in actions]
    if 'submit' in actions:
        branches.append(closed({'type':{'type':'string','enum':['submit']},
                                'output':closed({'assignments':{'type':'array','items':row}})}))
    action_schema=branches[0] if len(branches)==1 else {'anyOf':branches}
    return {'type':'json_schema','json_schema':{'name':'tracemicro_action_v1','strict':True,
            'schema':closed({'action':action_schema})}}

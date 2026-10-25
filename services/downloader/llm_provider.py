"""Optional LLM providers. The default OpenAI path never loads an adapter.

Register installed adapters in services/llm_providers/registry.json. Missing or
removed providers fail closed; they must never fall back to another endpoint.
"""
import hashlib,importlib.util,json,re
from pathlib import Path
from functools import lru_cache

DIRECTORY=Path(__file__).resolve().parents[1]/'llm_providers'

def provider_id(profile):return profile.get('provider') or 'openai'
def manifest(profile):
    ident=provider_id(profile)
    if ident=='openai':return None
    if not isinstance(ident,str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}',ident):raise ValueError('模型供应商标识无效')
    try:
        registered=json.loads((DIRECTORY/'registry.json').read_text())['providers']
        if ident not in registered:raise ValueError()
        data=json.loads((DIRECTORY/ident/'manifest.json').read_text())
        if data['id']!=ident or not (DIRECTORY/ident/'adapter.py').is_file():raise ValueError()
        return data
    except (OSError,ValueError,KeyError,TypeError):raise ValueError('此模型供应商已停用或未安装，请选择其他模型配置') from None

@lru_cache(maxsize=16)
def _load(ident):
    spec=importlib.util.spec_from_file_location('scholarnotelm_provider_'+ident,DIRECTORY/ident/'adapter.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def adapter(profile):
    if provider_id(profile)=='openai':
        import llm_thinking
        return llm_thinking if llm_thinking.selection(profile) else None
    data=manifest(profile)
    return _load(data['id']) if data else None

def endpoint(profile,default):
    module=adapter(profile)
    return module.endpoint(profile) if module else default(profile.get('baseUrl',''))

def with_session(profile,scope,*identifiers):
    if provider_id(profile)=='openai':return profile
    value=json.dumps([scope,*identifiers],ensure_ascii=False,separators=(',',':'))
    return {**profile,'_session':'snlm-'+hashlib.sha256(value.encode()).hexdigest()}

def signature_fields(profile,fields):
    """Keep legacy signature dictionaries byte-for-byte compatible."""
    result={k:profile.get(k) for k in fields}
    if provider_id(profile)=='openai':
        import llm_thinking
        selected=llm_thinking.selection(profile)
        if selected:result['thinkingPreset']=selected
    if provider_id(profile)!='openai':
        result['provider']=provider_id(profile)
        # Only the selected model affects this run. Absent/default preserves
        # existing Go caches; changing another model must not invalidate them.
        level=(profile.get('reasoningByModel') or {}).get(profile.get('model'))
        if level:result['reasoningLevel']=level
    return result


def semantic_fields(profile):
    """Only parameters that affect delivered model input/output; never credentials."""
    result=signature_fields(profile,('model','temperature'))
    result['endpoint']=profile.get('endpoint') or endpoint(profile,lambda url:url.rstrip('/') if url.rstrip('/').endswith('/chat/completions') else url.rstrip('/')+'/chat/completions')
    result['vision']=profile.get('model') in (profile.get('visionModels') or [])
    return result

def legacy_vision_profiles(profile):
    """Bounded exact replay of old image lists, with selected capability unchanged.

    Hash-only history cannot recover deleted model names. Never guess capability
    or accept a hash without matching all the other original signature fields.
    """
    from itertools import permutations,islice
    selected=profile.get('model');enabled=selected in (profile.get('visionModels') or [])
    names=list(dict.fromkeys([*(profile.get('visionModels') or []),*(profile.get('models') or [])]))
    if enabled and selected not in names:names.append(selected)
    if not enabled:names=[n for n in names if n!=selected]
    candidates=[profile.get('visionModels'),[selected] if enabled else None]
    if not enabled:candidates.append([])
    # Most historic profiles contain a small handful of models. Bound work even
    # for providers advertising hundreds of models; exact current lists still work.
    names=names[:6]
    candidates.extend(list(seq) for size in range(len(names)+1) for seq in islice(permutations(names,size),720) if (selected in seq)==enabled)
    for vision in candidates:yield {**profile,'visionModels':vision}

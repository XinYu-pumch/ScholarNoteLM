"""Official hosts backed by the same explicit presets as ordinary profiles."""
import llm_provider
import llm_thinking


def endpoint(profile):
    meta = llm_provider.manifest(profile)
    base = profile.get('baseUrl', '').strip().rstrip('/')
    if not meta or not meta.get('defaultThinkingPreset') or base not in meta.get('baseUrls', [meta['baseUrl']]):
        raise ValueError('请选择此供应商支持的官方 API 地址')
    return llm_thinking.endpoint(profile)


def prepare(profile, messages):
    url = endpoint(profile)
    if llm_thinking.selection(profile):
        return llm_thinking.prepare(profile, messages)
    # Explicit "server default" remains available after automatic initialization.
    body = {'model': profile['model'], 'messages': messages, 'stream': True}
    if isinstance(profile.get('temperature'), (int, float)):
        body['temperature'] = profile['temperature']
    headers = {'Authorization': 'Bearer ' + profile['apiKey']} if profile.get('apiKey') else {}
    return url, body, headers, llm_thinking.Decoder(False)

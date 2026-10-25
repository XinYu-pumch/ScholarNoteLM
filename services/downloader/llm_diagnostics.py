"""Connection diagnostics using the same adapters as research calls.

Only synthetic prompts are sent. Negative probes are explicit, never persisted,
never retried with a different setting, and never claim to prove effort execution.
"""
import copy
import time
import uuid
import llm_provider
import llm_thinking

INVALID = '__invalid_probe__'
FIELDS = ('reasoning_effort', 'thinking', 'enable_thinking', 'reasoning',
          'generationConfig', 'extra_body')


def thinking_fields(body):
    """Expose only thinking fields, never messages, headers, keys or whole bodies."""
    result = {k: copy.deepcopy(body[k]) for k in FIELDS[:4] if k in body}
    for key, path in [('generationConfig', ('thinkingConfig',)), ('extra_body', ('google', 'thinking_config'))]:
        value = body.get(key, {})
        for part in path:
            value = value.get(part, {}) if isinstance(value, dict) else {}
        if value:
            result['.'.join((key, *path))] = copy.deepcopy(value)
    return result


def probe_path(body):
    for path in [('reasoning_effort',), ('extra_body','google','thinking_config','thinking_level'),
                 ('generationConfig','thinkingConfig','thinkingLevel'),
                 ('thinking','type'), ('enable_thinking',)]:
        value = body
        for part in path:
            value = value.get(part) if isinstance(value, dict) else None
        if value is not None:
            return path
    return None


def token_count(event):
    """Usage chunks often have no choices and arrive after finish_reason."""
    usage = event.get('usage') or event.get('response', {}).get('usage') or {}
    for value in [usage.get('completion_tokens_details', {}).get('reasoning_tokens'),
                  usage.get('output_tokens_details', {}).get('reasoning_tokens'),
                  event.get('usageMetadata', {}).get('thoughtsTokenCount')]:
        if type(value) is int and value >= 0:
            return value
    return None


async def test_connection(profile):
    import review_llm as llm
    p = {**profile, 'endpoint': llm_provider.endpoint(profile, llm.endpoint)}
    p = llm_provider.with_session(p, 'connection-test', uuid.uuid4().hex)
    if not p.get('model'):
        raise ValueError('请选择要测试的模型')
    selected = llm_thinking.selection(p)
    # Reject malformed preset choices before any request goes out.
    preset = llm_thinking.PRESETS[selected['preset']] if selected else None
    started = time.monotonic()
    content = 'Reply only: connection OK'
    expected = None
    if profile.get('testVision'):
        import base64, secrets, struct, zlib
        expected, rgb = secrets.choice([('red',(255,0,0)),('green',(0,180,0)),('blue',(0,0,255))])
        def part(kind,data):
            return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
        png = b'\x89PNG\r\n\x1a\n'+part(b'IHDR',struct.pack('!2I5B',64,64,8,2,0,0,0))+part(b'IDAT',zlib.compress((b'\0'+bytes(rgb)*64)*64))+part(b'IEND',b'')
        content = [{'type':'text','text':'Name the solid color in this image. Reply with one English color word only.'},
                   {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(png).decode()}}]
    elif selected:
        content = 'A box has 17 red and 23 blue beads. Remove 8 red beads and add 6 blue beads. What fraction of the beads is red? Return only the final fraction.'
    connection = {}
    observation = {'reasoningCharacters': 0, 'reasoningTokens': None}
    sent = {}
    path = None
    def capture(body):
        nonlocal path
        sent.update(thinking_fields(body))
        path = probe_path(body)
        return body
    def thought(text):
        observation['reasoningCharacters'] = len(text)
    def event(value):
        tokens = token_count(value)
        if tokens is not None:
            observation['reasoningTokens'] = max(observation['reasoningTokens'] or 0, tokens)
    messages = [{'role':'user','content':content}]
    reply = await llm.chat(p, messages, lambda:False, progress=lambda **kw:connection.update(kw),
                           on_reasoning=thought, on_response=event, request_transform=capture)
    if expected and reply.strip().lower().strip('.。!') != expected:
        raise ValueError('服务接受了图片，但识别结果未通过；请核对该模型是否支持图片')
    result = {'reply':reply[:200], 'seconds':round(time.monotonic()-started,2), 'model':p['model'],
              'client':'qa-stream', 'networkMode':connection.get('networkMode','direct'), 'imageVerified':bool(expected),
              'thinking':{'parameters':sent, **observation,
                          'outputKind':preset.get('output',{}).get('kind','provider_defined') if preset else 'provider_defined',
                          'probe':{'status':'not_requested'}}}
    if not profile.get('testThinkingProbe'):
        return result
    if expected or not selected or not path:
        result['thinking']['probe'] = {'status':'not_applicable'}
        return result
    def invalid(body):
        # Modify exactly one field in the prepared request; keep all else equal.
        body = copy.deepcopy(body)
        target = body
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = INVALID if path[-1] != 'enable_thinking' else {'invalid':INVALID}
        return body
    probe = {'status':'inconclusive', 'parameter':'.'.join(path)}
    try:
        await llm.chat(p, messages, lambda:False, request_transform=invalid)
        probe['status'] = 'accepted'
    except llm.UpstreamFailure as exc:
        probe['httpStatus'] = exc.status
        # A generic HTTP 400, auth error, quota failure or timeout is not evidence.
        if exc.status in (400,422) and ('.'.join(path) in exc.rejected_fields or path[-1] in exc.rejected_fields):
            probe['status'] = 'rejected'
    except (ValueError, llm.Cancelled):
        pass
    result['thinking']['probe'] = probe
    result['seconds'] = round(time.monotonic()-started,2)
    return result

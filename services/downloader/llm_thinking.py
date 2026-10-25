"""Explicit per-model thinking presets for user-defined providers.

Independent of optional provider modules. Never infer a protocol from model names
or send Go session headers. Endpoint conversion preserves the configured host.
"""
import copy
import json
import re
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

PRESETS = {p['id']: p for p in json.loads(Path(__file__).with_name('thinking_presets.json').read_text())}


def selection(profile):
    if (profile.get('provider') or 'openai') != 'openai':
        from llm_provider import manifest
        if not manifest(profile).get('defaultThinkingPreset'):
            return None
    settings = profile.get('thinkingByModel', {})
    if not isinstance(settings, dict):
        raise ValueError('模型思考预设格式无效')
    value = settings.get(profile.get('model'))
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get('preset'), str) or value['preset'] not in PRESETS:
        raise ValueError('模型思考预设无效，请重新选择')
    preset = PRESETS[value['preset']]
    level = value.get('level', preset['defaultLevel'])
    if not isinstance(level, str) or level not in preset['levels']:
        raise ValueError('此思考预设不支持所选档位，请重新选择')
    output = value.get('output', 'default')
    if not isinstance(output, str) or output not in preset.get('output', {}).get('modes', ['default']):
        raise ValueError('此思考预设不支持所选输出方式')
    result = {'preset': preset['id'], 'level': level, **({'output': output} if output != 'default' else {})}
    if level == 'budget':
        spec = preset.get('budget', {})
        budget = value.get('budget')
        if type(budget) is not int or not spec or not spec['min'] <= budget <= spec['max']:
            raise ValueError('请填写此预设支持的整数思考 token 预算')
        result['budget'] = budget
    # Missing/default and inactive budgets preserve historic signatures exactly.
    return result


def endpoint(profile):
    from review_llm import endpoint as chat_endpoint
    selected = selection(profile)
    url = chat_endpoint(profile.get('baseUrl', ''))  # shared HTTPS / local validation
    protocol = PRESETS[selected['preset']]['protocol'] if selected else 'chat'
    if protocol == 'chat':
        return url
    parts = urlsplit(url)
    path = parts.path.removesuffix('/chat/completions').rstrip('/')
    if protocol in ('messages', 'responses'):
        path = path.removesuffix('/messages').removesuffix('/responses')
        return urlunsplit((parts.scheme, parts.netloc, path + '/' + protocol, '', ''))
    # Accept standard /v1, native /v1beta, or Google's /v1beta/openai base.
    if path.endswith('/v1beta/openai'):
        path = path.removesuffix('/openai')
    elif path.endswith('/v1'):
        path = path[:-3] + '/v1beta'
    elif not path.endswith('/v1beta'):
        raise ValueError('Gemini 原生预设的 API 地址须以 /v1 或 /v1beta 结尾，可保留中转路径前缀')
    model = profile.get('model', '')
    if not isinstance(model, str) or not model.strip():
        raise ValueError('请选择模型')
    path += '/models/' + quote(model.removeprefix('models/'), safe='') + ':streamGenerateContent'
    return urlunsplit((parts.scheme, parts.netloc, path, 'alt=sse', ''))


def google_parts(content):
    if isinstance(content, str):
        return [{'text': content}]
    if not isinstance(content, list):
        raise ValueError('Gemini 消息内容格式无效')
    parts = []
    for part in content:
        if part.get('type') == 'text':
            parts.append({'text': part['text']})
        elif part.get('type') == 'image_url':
            match = re.fullmatch(r'data:(image/(?:png|jpeg|gif|webp));base64,([A-Za-z0-9+/=\s]+)', part.get('image_url', {}).get('url', ''))
            if not match:
                raise ValueError('Gemini 原生预设图片须使用受支持的内嵌图片')
            parts.append({'inlineData': {'mimeType': match[1], 'data': match[2]}})
        else:
            raise ValueError('Gemini 原生预设不支持此消息内容类型')
    return parts


def prepare(profile, messages):
    selected = selection(profile)
    if not selected:
        raise ValueError('未选择模型思考预设')
    native = selected['preset'] == 'gemini4_native'
    preset = PRESETS[selected['preset']]
    if preset['protocol'] in ('messages', 'responses'):
        from llm_native import prepare as prepare_native
        return prepare_native(profile, messages, selected, preset, endpoint(profile))
    if native:
        body = {'contents': [], 'generationConfig': {'thinkingConfig': {
            'thinkingLevel': selected['level'], 'includeThoughts': True}}}
        system = []
        for message in messages:
            role = message['role']
            if role not in ('system', 'user', 'assistant'):
                raise ValueError('Gemini 原生预设不支持此消息角色')
            parts = google_parts(message['content'])
            if role == 'system':
                system.extend(parts)
                continue
            role = 'model' if role == 'assistant' else 'user'
            if body['contents'] and body['contents'][-1]['role'] == role:
                body['contents'][-1]['parts'].extend(parts)
            else:
                body['contents'].append({'role': role, 'parts': parts})
        if system:
            body['systemInstruction'] = {'parts': system}
    else:
        body = {'model': profile['model'], 'messages': messages, 'stream': True}
        # Only reviewed local presets can supply request fields.
        body.update(copy.deepcopy(preset['options'][selected['level']]))
        if selected['level'] == 'budget':
            body[preset['budget']['field']] = selected['budget']
    output = selected.get('output', 'default')
    if output != 'default':
        if native:
            body['generationConfig']['thinkingConfig']['includeThoughts'] = output == 'summary'
        else:
            # Google REST extension is genuinely nested in extra_body. Unlike
            # Python SDK extra_body, it must not be flattened on the wire.
            body.pop('reasoning_effort', None)
            body['extra_body'] = {'google': {'thinking_config': {
                'thinking_level': selected['level'], 'include_thoughts': output == 'summary'}}}
    temperature = profile.get('temperature')
    if isinstance(temperature, (int, float)) and not preset.get('omitTemperature'):
        (body['generationConfig'] if native else body)['temperature'] = temperature
    headers = {'Authorization': 'Bearer ' + profile['apiKey']} if profile.get('apiKey') else {}
    return endpoint(profile), body, headers, Decoder(native)


class Decoder:
    def __init__(self, native):
        self.native = native

    def decode(self, value):
        if value.get('error'):
            raise ValueError('模型服务返回错误，请检查思考预设、档位和服务支持情况')
        if not self.native:
            for choice in value.get('choices', []):
                if choice.get('finish_reason') and choice['finish_reason'] != 'stop':
                    raise ValueError('模型未完整返回正文（输出上限、过滤或工具调用）')
            return value
        if value.get('promptFeedback', {}).get('blockReason'):
            raise ValueError('Gemini 拒绝了输入，未生成正文')
        candidate = next((c for c in value.get('candidates', []) if c.get('index', 0) == 0), {})
        text, thoughts = '', ''
        for part in candidate.get('content', {}).get('parts', []):
            if 'functionCall' in part:
                raise ValueError('Gemini 返回了应用不支持的工具调用')
            if part.get('thought'):
                thoughts += part.get('text', '')
            else:
                text += part.get('text', '')
        finish = candidate.get('finishReason')
        if finish and finish != 'STOP':
            raise ValueError('Gemini 未完整返回正文（输出上限、过滤或未知结束状态）')
        choice = {'delta': {'content': text, 'reasoning_content': thoughts}}
        if finish:
            choice['finish_reason'] = 'stop'
        return {'choices': [choice]}

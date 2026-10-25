"""Opt-in ordinary-provider Messages/Responses support, independent of Go.

Only textual answers and exposed thinking are consumed. Tool calls, refusals and
incomplete streams fail closed. Encrypted/signature fields are never answer text.
"""
import copy
import re


def parts(content, protocol, role):
    content = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
    if not isinstance(content, list):
        raise ValueError('原生预设消息内容格式无效')
    result = []
    for part in content:
        if part.get('type') == 'text':
            kind = 'text' if protocol == 'messages' else ('output_text' if role == 'assistant' else 'input_text')
            result.append({'type': kind, 'text': part['text']})
        elif part.get('type') == 'image_url' and role == 'user':
            url = part.get('image_url', {}).get('url', '')
            match = re.fullmatch(r'data:(image/(?:png|jpeg|gif|webp));base64,([A-Za-z0-9+/=\s]+)', url)
            if not match:
                raise ValueError('原生预设图片须使用受支持的内嵌图片')
            result.append({'type': 'image', 'source': {'type': 'base64', 'media_type': match[1], 'data': match[2]}}
                          if protocol == 'messages' else {'type': 'input_image', 'image_url': url})
        else:
            raise ValueError('原生预设不支持此消息内容类型')
    return result


def prepare(profile, messages, selected, preset, url):
    protocol = preset['protocol']
    body = {'model': profile['model'], 'stream': True}
    headers = {'Authorization': 'Bearer ' + profile['apiKey']} if profile.get('apiKey') else {}
    converted, system = [], []
    for message in messages:
        role = message['role']
        if role not in ('system', 'assistant', 'user'):
            raise ValueError('原生预设不支持此消息角色')
        content = parts(message['content'], protocol, role)
        if protocol == 'messages' and role == 'system':
            system.extend(content)
        elif protocol == 'messages' and converted and converted[-1]['role'] == role:
            converted[-1]['content'].extend(content)
        else:
            converted.append({'role': role, 'content': content})
    if protocol == 'messages':
        headers['anthropic-version'] = '2023-06-01'
        if profile.get('apiKey'):
            headers['x-api-key'] = profile['apiKey']
        body.update(messages=converted, max_tokens=preset['maxOutputTokens'])
        if system:
            body['system'] = system
    else:
        body.update(input=converted, store=False)
    body.update(copy.deepcopy(preset['options'][selected['level']]))
    if protocol == 'messages' and selected.get('output', 'default') != 'default':
        body['thinking']['display'] = 'summarized' if selected['output'] == 'summary' else 'omitted'
    return url, body, headers, Decoder(protocol)


def chunk(text='', thought='', finished=False):
    choice = {'delta': {'content': text, 'reasoning_content': thought}}
    if finished:
        choice['finish_reason'] = 'stop'
    return {'choices': [choice]}


class Decoder:
    def __init__(self, protocol):
        self.protocol = protocol
        self.completed = False
        self.stop_reason = None
        self.seen = {}

    def piece(self, value, family, text, complete=False):
        key = (value.get('output_index', 0), family, value.get('summary_index', value.get('content_index', 0)))
        previous = self.seen.get(key, '')
        if complete:
            if previous and not text.startswith(previous):
                raise ValueError('模型最终响应与已接收的流式内容不一致')
            self.seen[key] = text
            return text[len(previous):]
        self.seen[key] = previous + text
        return text

    def finish(self, reason):
        if reason not in ('end_turn', 'stop_sequence', 'completed'):
            raise ValueError('模型未完整返回正文（输出上限、过滤、工具调用或未知结束状态）')
        self.completed = True

    def finalize(self):
        if not self.completed:
            raise ValueError('原生模型连接中断，缺少有效完成状态')

    def decode(self, value):
        kind = value.get('type', '')
        if value.get('error') or kind == 'error':
            raise ValueError('模型服务返回流式错误，请检查服务支持情况')
        if self.protocol == 'responses':
            families = {'output_text': 'answer', 'reasoning_text': 'content', 'reasoning_summary_text': 'summary'}
            for event, family in families.items():
                if kind in ('response.' + event + '.delta', 'response.' + event + '.done'):
                    complete = kind.endswith('.done')
                    text = self.piece(value, family, value.get('text' if complete else 'delta', ''), complete)
                    return chunk(text=text) if family == 'answer' else chunk(thought=text)
            if kind in ('response.failed', 'response.incomplete', 'response.refusal.delta', 'response.refusal.done'):
                raise ValueError('Responses 未完整返回正文或拒绝了请求')
            if kind in ('response.output_item.added', 'response.output_item.done'):
                if value.get('item', {}).get('type') not in ('message', 'reasoning'):
                    raise ValueError('模型返回了应用不支持的输出类型')
            if kind == 'response.completed' or value.get('object') == 'response':
                response = value.get('response', value)
                self.finish(response.get('status'))
                text, thought = '', ''
                for i, item in enumerate(response.get('output', [])):
                    if item.get('type') not in ('message', 'reasoning'):
                        raise ValueError('模型返回了应用不支持的输出类型')
                    for family in ('content', 'summary'):
                        for j, part in enumerate(item.get(family, [])):
                            if part.get('type') == 'refusal':
                                raise ValueError('模型拒绝了请求')
                            if part.get('type') in ('output_text', 'reasoning_text', 'summary_text', 'text'):
                                answer = item['type'] == 'message' and part['type'] == 'output_text'
                                delta = self.piece({'output_index': i, 'content_index': j}, 'answer' if answer else family, part.get('text', ''), True)
                                if answer:
                                    text += delta
                                else:
                                    thought += delta
                return chunk(text, thought, True)
            return chunk()
        if kind == 'message' and 'content' in value:
            self.finish(value.get('stop_reason'))
            text, thought = '', ''
            for part in value['content']:
                if part.get('type') == 'text':
                    text += part.get('text', '')
                elif part.get('type') == 'thinking':
                    thought += part.get('thinking', '')
                elif part.get('type') != 'redacted_thinking':
                    raise ValueError('模型返回了应用不支持的输出类型')
            return chunk(text, thought, True)
        if kind == 'content_block_start':
            block = value.get('content_block', {})
            if block.get('type') not in ('text', 'thinking', 'redacted_thinking'):
                raise ValueError('模型返回了应用不支持的输出类型')
            return chunk(block.get('text', ''), block.get('thinking', ''))
        if kind == 'content_block_delta':
            delta = value.get('delta', {})
            if delta.get('type') not in ('text_delta', 'thinking_delta', 'signature_delta'):
                raise ValueError('模型返回了应用不支持的输出类型')
            return chunk(delta.get('text', ''), delta.get('thinking', ''))
        if kind == 'message_delta':
            self.stop_reason = value.get('delta', {}).get('stop_reason') or self.stop_reason
        if kind == 'message_stop':
            self.finish(self.stop_reason)
            return chunk(finished=True)
        return chunk()

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
import llm_provider
import llm_thinking as thinking
import review_llm


class ThinkingTests(unittest.IsolatedAsyncioTestCase):
    def profile(self, preset='gemini4_native', level='high'):
        return {'model': 'gemini-4-argon', 'baseUrl': 'https://relay.invalid/prefix/v1',
                'apiKey': 'fixture-only', 'temperature': 0.2,
                'thinkingByModel': {'gemini-4-argon': {'preset': preset, 'level': level}}}

    def test_chat_presets_and_ordinary_isolation(self):
        for preset, levels in [('deepseek_openai', ['low', 'high', 'max'])]:
            for level in levels:
                p = self.profile(preset, level)
                url, body, headers, _ = thinking.prepare(p, [{'role': 'user', 'content': 'hi'}])
                self.assertEqual(url, 'https://relay.invalid/prefix/v1/chat/completions')
                self.assertEqual(body['reasoning_effort'], level)
                self.assertNotIn('x-opencode-session', headers)
                self.assertEqual(body['thinking'], {'type': 'enabled'})
                self.assertNotIn('temperature', body)
        p = self.profile();p.pop('thinkingByModel')
        self.assertIsNone(llm_provider.adapter(p))
        with patch.object(llm_provider, 'DIRECTORY', Path('/nonexistent/providers')):
            self.assertIs(llm_provider.adapter(self.profile()), thinking)

    def test_new_chat_wire_formats_and_defaults(self):
        cases = [
            ('gpt6_astra_chat', 'xhigh', {'reasoning_effort': 'xhigh'}),
            ('generic_thinking_toggle', 'disabled', {'thinking': {'type': 'disabled'}}),
            ('generic_thinking_toggle', 'enabled', {'thinking': {'type': 'enabled'}}),
            ('qwen_openai', 'xhigh', {'enable_thinking': True, 'reasoning_effort': 'xhigh'}),
            ('qwen_openai', 'disabled', {'enable_thinking': False}),
            ('glm_openai', 'max', {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'max'}),
        ]
        for preset, level, expected in cases:
            with self.subTest(preset=preset, level=level):
                p = self.profile(preset, level)
                _, body, headers, _ = thinking.prepare(p, [])
                expected = {'model': p['model'], 'messages': [], 'stream': True, **expected}
                if preset in ('qwen_openai', 'glm_openai'): expected['temperature'] = .2
                self.assertEqual(body, expected)
                self.assertNotIn('x-opencode-session', headers)
        for preset in ('generic_thinking_toggle', 'qwen_openai', 'glm_openai'):
            p = self.profile(preset, 'default')
            body = thinking.prepare(p, [])[1]
            self.assertFalse({'thinking', 'enable_thinking', 'reasoning_effort'} & body.keys())
        for preset, level in [('qwen_openai', 'high'), ('glm_openai', 'medium'), ('generic_thinking_toggle', 'low')]:
            with self.assertRaises(ValueError):thinking.prepare(self.profile(preset, level), [])

    def test_native_endpoint_and_messages(self):
        p = self.profile()
        messages = [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': 'hi'},
                    {'role': 'assistant', 'content': 'hello'}, {'role': 'user', 'content': [
                        {'type': 'text', 'text': 'image'}, {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,YQ=='}}]}]
        url, body, headers, _ = thinking.prepare(p, messages)
        self.assertEqual(url, 'https://relay.invalid/prefix/v1beta/models/gemini-4-argon:streamGenerateContent?alt=sse')
        self.assertEqual(body['generationConfig']['thinkingConfig'], {'thinkingLevel': 'high', 'includeThoughts': True})
        self.assertEqual(body['contents'][1]['role'], 'model')
        self.assertEqual(body['systemInstruction']['parts'], [{'text': 'system'}])
        self.assertEqual(body['contents'][2]['parts'][1]['inlineData']['mimeType'], 'image/png')
        self.assertEqual(headers, {'Authorization': 'Bearer fixture-only'})
        for base in ['https://relay.invalid/prefix/v1beta', 'https://relay.invalid/prefix/v1beta/openai', 'https://relay.invalid/prefix/v1/chat/completions']:
            self.assertEqual(thinking.endpoint({**p, 'baseUrl': base}), url)
        for base in ['https://user:secret@relay.invalid/v1', 'http://relay.invalid/v1', 'https://relay.invalid/unknown']:
            with self.assertRaises(ValueError):thinking.endpoint({**p, 'baseUrl': base})

    def test_validation_and_selected_model_signature(self):
        p = self.profile();plain = {**p, 'thinkingByModel': {}}
        fields = ('model', 'baseUrl', 'temperature')
        legacy = {k: plain[k] for k in fields}
        self.assertEqual(llm_provider.signature_fields(plain, fields), legacy)
        other = {**plain, 'thinkingByModel': {'another-model': {'preset': 'deepseek_openai', 'level': 'max'}}}
        self.assertEqual(llm_provider.signature_fields(other, fields), legacy)
        self.assertNotEqual(llm_provider.signature_fields(p, fields), legacy)
        self.assertNotEqual(llm_provider.signature_fields(p, fields), llm_provider.signature_fields(self.profile(level='low'), fields))
        for invalid in [[], {'gemini-4-argon': 'wrong'}, {'gemini-4-argon': {'preset': 'missing'}}, {'gemini-4-argon': {'preset': 'gemini4_native', 'level': 'max'}}]:
            with self.assertRaises(ValueError):thinking.selection({**p, 'thinkingByModel': invalid})
        self.assertIsNone(thinking.selection({**p, 'provider': 'opencode_go'}))

    async def test_native_stream_summary_and_failure(self):
        p = self.profile();p['endpoint'] = thinking.endpoint(p)
        client = httpx.AsyncClient
        for finish in ['STOP', 'MAX_TOKENS']:
            async def handler(request):
                body = json.loads(request.content)
                self.assertEqual(body['generationConfig']['thinkingConfig']['thinkingLevel'], 'high')
                events = [{'candidates': [{'content': {'parts': [{'text': 'summary', 'thought': True}]}}]},
                          {'candidates': [{'content': {'parts': [{'text': 'answer'}]}, 'finishReason': finish}]}]
                return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=''.join('data: '+json.dumps(v)+'\n\n' for v in events))
            thoughts = []
            with patch.object(review_llm.httpx, 'AsyncClient', side_effect=lambda **kwargs: client(transport=httpx.MockTransport(handler))), patch.object(review_llm, 'system_proxy', return_value=None):
                if finish == 'STOP':
                    self.assertEqual(await review_llm.chat(p, [{'role': 'user', 'content': 'hi'}], lambda: False, on_reasoning=thoughts.append), 'answer')
                    self.assertEqual(thoughts, ['summary'])
                else:
                    with self.assertRaises(ValueError):await review_llm.chat(p, [], lambda: False)


if __name__ == '__main__':
    unittest.main()

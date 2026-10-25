import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
import llm_thinking as thinking
import llm_native
import llm_provider
import llm_diagnostics
import review_llm


def profile(preset, level, **extra):
    return {'model':'fixture','baseUrl':'https://relay.invalid/prefix/v1','apiKey':'fixture-key','temperature':.4,
            'thinkingByModel':{'fixture':{'preset':preset,'level':level,**extra}}}


class VendorThinkingTests(unittest.IsolatedAsyncioTestCase):
    def test_responses_vendor_protocols(self):
        cases = [
            ('gpt6_astra_responses', 'xhigh', 'xhigh'),
            ('deepseek_v4_responses', 'none', 'none'),
            ('qwen38_responses', 'medium', 'medium'),
            ('glm53_responses', 'high', 'high'),
            ('kimi_k3_responses', 'low', 'low'),
            ('mimo_v26_responses', 'enabled', 'high'),
            ('mimo_v26_responses', 'disabled', 'none'),
            ('minimax_m31_responses', 'max', 'max'),
            ('meta_muse_responses', 'minimal', 'minimal'),
        ]
        for preset, level, effort in cases:
            with self.subTest(preset=preset, level=level):
                url, body, headers, _ = thinking.prepare(profile(preset, level), [{'role':'user','content':'hello'}])
                self.assertEqual(url, 'https://relay.invalid/prefix/v1/responses')
                self.assertEqual(body, {'model':'fixture', 'stream':True, 'store':False,
                                       'input':[{'role':'user','content':[{'type':'input_text','text':'hello'}]}],
                                       'reasoning':{'effort':effort}})
                self.assertEqual(headers, {'Authorization':'Bearer fixture-key'})
        for preset, bad in [('gpt6_astra_responses','none'), ('kimi_k3_responses','medium'),
                            ('glm53_responses','low'), ('minimax_m31_responses','none'),
                            ('qwen38_responses','budget'), ('mimo_v26_responses','high')]:
            with self.assertRaises(ValueError): thinking.prepare(profile(preset,bad), [])

    def test_official_output_switch_is_protocol_specific(self):
        for preset in ['gpt6_astra_responses','meta_muse_responses']:
            for mode in ['summary','off','default']:
                body = thinking.prepare(profile(preset,'high',output=mode), [])[1]
                expected = {'effort':'high', **({'summary':'auto'} if mode=='summary' else {})}
                self.assertEqual(body['reasoning'],expected)
        for preset in ['deepseek_v4_responses','qwen38_responses','glm53_responses',
                       'kimi_k3_responses','mimo_v26_responses','minimax_m31_responses']:
            with self.assertRaises(ValueError):
                thinking.prepare(profile(preset,thinking.PRESETS[preset]['defaultLevel'],output='summary'), [])
        body = thinking.prepare(profile('claude55_chat','adaptive'), [])[1]
        self.assertEqual(body, {'model':'fixture','messages':[],'stream':True,'thinking':{'type':'adaptive'}})
        for preset in ['gpt6_astra_chat','meta_muse_chat']:
            self.assertEqual(thinking.prepare(profile(preset,'high'), [])[1],
                             {'model':'fixture','messages':[],'stream':True,'reasoning_effort':'high'})
            with self.assertRaises(ValueError): thinking.prepare(profile(preset,'high',output='summary'), [])

    def test_official_wire_parameters(self):
        for preset, level, fields in [
            ('kimi_k3_openai','low',{'reasoning_effort':'low'}),
            ('grok47_chat','xhigh',{'reasoning_effort':'xhigh'}),
            ('mimo_v26_openai','enabled',{'thinking':{'type':'enabled'}}),
            ('mimo_v26_openai','disabled',{'thinking':{'type':'disabled'}}),
            ('minimax_m31_openai','max',{'reasoning_effort':'max','reasoning_split':True})]:
            p=profile(preset,level)
            url,body,headers,_=thinking.prepare(p,[])
            self.assertEqual(url,'https://relay.invalid/prefix/v1/chat/completions')
            self.assertEqual(body,{'model':'fixture','messages':[],'stream':True,**fields})
            self.assertEqual(headers,{'Authorization':'Bearer fixture-key'})
        with self.assertRaises(ValueError):thinking.prepare(profile('mimo_v26_openai','high'),[])
        with self.assertRaises(ValueError):thinking.prepare(profile('kimi_k3_openai','medium'),[])

    def test_budget_validation_exclusivity_and_signature(self):
        for budget in [0,4096,262144]:
            p=profile('qwen_openai','budget',budget=budget)
            body=thinking.prepare(p,[])[1]
            self.assertEqual(body['thinking_budget'],budget)
            self.assertNotIn('reasoning_effort',body)
            self.assertEqual(llm_diagnostics.probe_path(body),('thinking_budget',))
            self.assertEqual(thinking.selection(p)['budget'],budget)
        for bad in [None,False,1.5,'4096',-1,262145]:
            with self.assertRaises(ValueError):thinking.prepare(profile('qwen_openai','budget',budget=bad),[])
        self.assertEqual(thinking.selection(profile('qwen_openai','low',budget=4000)),thinking.selection(profile('qwen_openai','low')))
        self.assertNotEqual(llm_provider.signature_fields(profile('qwen_openai','budget',budget=1),()),llm_provider.signature_fields(profile('qwen_openai','budget',budget=2),()))

    def test_native_encoding_headers_and_output_selection(self):
        messages=[{'role':'system','content':'rules'},{'role':'user','content':'hello'},
                  {'role':'assistant','content':'hi'},{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,YQ=='}}]}]
        with patch.object(llm_provider,'DIRECTORY',Path('/missing/go')):
            for preset,protocol in [('claude55_messages','messages'),('grok47_responses','responses')]:
                p=profile(preset,'high',output='summary') if protocol=='messages' else profile(preset,'high')
                self.assertIs(llm_provider.adapter(p),thinking)
                url,b,h,_=thinking.prepare(p,messages)
                self.assertEqual(url,'https://relay.invalid/prefix/v1/'+protocol)
                self.assertNotIn('temperature',b);self.assertNotIn('x-opencode-session',h)
                self.assertNotIn('max_completion_tokens',b)
                if protocol=='messages':
                    self.assertEqual(b['thinking'],{'type':'adaptive','display':'summarized'})
                    self.assertEqual(b['output_config'],{'effort':'high'})
                    self.assertEqual(b['max_tokens'],128000)
                    self.assertEqual(h['x-api-key'],'fixture-key')
                    self.assertEqual(b['system'],[{'type':'text','text':'rules'}])
                    self.assertEqual(b['messages'][-1]['content'][0]['source']['media_type'],'image/png')
                    self.assertEqual(llm_diagnostics.probe_path(b),('output_config','effort'))
                else:
                    self.assertEqual(b['reasoning'],{'effort':'high'});self.assertFalse(b['store'])
                    self.assertEqual(b['input'][2]['content'][0]['type'],'output_text')
                    self.assertEqual(llm_diagnostics.probe_path(b),('reasoning','effort'))
        for mode,display in [('default',None),('off','omitted')]:
            b=thinking.prepare(profile('claude55_messages','medium',output=mode),[])[1]
            self.assertEqual(b['thinking'].get('display'),display)

    async def stream(self,p,events):
        client=httpx.AsyncClient;thoughts=[];p['endpoint']=thinking.endpoint(p)
        async def handler(request):
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=''.join('data: '+json.dumps(v)+'\n\n' for v in events))
        with patch.object(review_llm.httpx,'AsyncClient',side_effect=lambda **kw:client(transport=httpx.MockTransport(handler))),patch.object(review_llm,'system_proxy',return_value=None):
            answer=await review_llm.chat(p,[{'role':'user','content':'fixture'}],lambda:False,on_reasoning=thoughts.append)
        return answer,thoughts

    async def test_messages_stream_separation_and_missing_finish(self):
        p=profile('claude55_messages','medium',output='summary')
        events=[{'type':'content_block_start','content_block':{'type':'thinking','thinking':''}},
                {'type':'content_block_delta','delta':{'type':'thinking_delta','thinking':'summary'}},
                {'type':'content_block_delta','delta':{'type':'signature_delta','signature':'opaque'}},
                {'type':'content_block_start','content_block':{'type':'text','text':'answer'}},
                {'type':'message_delta','delta':{'stop_reason':'end_turn'}},{'type':'message_stop'}]
        self.assertEqual(await self.stream(p,events),('answer',['summary']))
        for bad in [events[:-1],events[:-2]+[{'type':'message_delta','delta':{'stop_reason':'max_tokens'}},{'type':'message_stop'}]]:
            with self.assertRaises(ValueError):await self.stream(p,bad)

    async def test_responses_stream_and_final_deduplication(self):
        p=profile('grok47_responses','high')
        final={'type':'response.completed','response':{'status':'completed','output':[
            {'type':'reasoning','summary':[{'type':'summary_text','text':'summary'}],'encrypted_content':'opaque'},
            {'type':'message','content':[{'type':'output_text','text':'answer'}]}]}}
        events=[{'type':'response.reasoning_summary_text.delta','output_index':0,'delta':'summary'},
                {'type':'response.reasoning_summary_text.done','output_index':0,'text':'summary'},
                {'type':'response.output_text.delta','output_index':1,'delta':'answer'},
                {'type':'response.output_text.done','output_index':1,'text':'answer'},final]
        self.assertEqual(await self.stream(p,events),('answer',['summary']))
        self.assertEqual(await self.stream(p,[final]),('answer',['summary']))
        with self.assertRaises(ValueError):await self.stream(p,events[:-1])
        for value in [{'object':'response','status':'incomplete','output':[]},
                      {'type':'response.output_item.added','item':{'type':'function_call'}},
                      {'type':'response.refusal.delta','delta':'no'}]:
            with self.assertRaises(ValueError):llm_native.Decoder('responses').decode(value)

    async def test_nullable_responses_content_and_reasoning_mirrors(self):
        p=profile('mimo_v26_responses','enabled')
        final={'type':'response.completed','response':{'status':'completed','output':[
            {'type':'reasoning','content':None,'summary':[{'type':'summary_text','text':'thought'}]},
            {'type':'message','summary':None,'content':[{'type':'output_text','text':'answer'}]}]}}
        self.assertEqual(await self.stream(p,[final]),('answer',['thought']))
        events=[{'type':'response.reasoning_text.delta','output_index':0,'delta':'thought'},
                {'type':'response.reasoning_text.done','output_index':0,'text':'thought'},
                {'type':'response.output_text.delta','output_index':1,'delta':'answer'},final]
        self.assertEqual(await self.stream(p,events),('answer',['thought']))
        # Distinct summaries must survive even when raw reasoning was streamed.
        final['response']['output'][0]['summary'][0]['text']='different summary'
        answer, thoughts=await self.stream(p,events)
        self.assertEqual(answer,'answer')
        self.assertEqual(thoughts[-1],'thoughtdifferent summary')
        final['response']['output'][0].update(content=None,summary=None)
        self.assertEqual(await self.stream(p,[final]),('answer',[]))
        # Optional null usage details must not abort an otherwise valid stream.
        self.assertIsNone(llm_diagnostics.token_count({'usage':{'output_tokens_details':None,'completion_tokens_details':None}}))

    def test_native_parameter_error_evidence(self):
        for field in ['output_config.effort','reasoning.effort','thinking_budget']:
            e=review_llm.UpstreamFailure(400,json.dumps({'error':{'param':field,'message':'invalid parameter'}}))
            self.assertEqual(e.rejected_fields,{field})
        self.assertFalse(review_llm.UpstreamFailure(400,'{"error":{"message":"quota exceeded"}}').rejected_fields)

if __name__=='__main__':unittest.main()

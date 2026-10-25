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

    def test_native_parameter_error_evidence(self):
        for field in ['output_config.effort','reasoning.effort','thinking_budget']:
            e=review_llm.UpstreamFailure(400,json.dumps({'error':{'param':field,'message':'invalid parameter'}}))
            self.assertEqual(e.rejected_fields,{field})
        self.assertFalse(review_llm.UpstreamFailure(400,'{"error":{"message":"quota exceeded"}}').rejected_fields)

if __name__=='__main__':unittest.main()

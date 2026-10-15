"""OpenCode Go only: official routes, session headers and native API translation.

No sockets/credentials/global HTTP defaults are modified here. The shared client
owns TLS, system proxy resolution, idle timeouts and cancellation.
"""
import copy,json,re
from pathlib import Path

MANIFEST=json.loads(Path(__file__).with_name('manifest.json').read_text())
BASE=MANIFEST['baseUrl']

def route(profile):
    model=profile.get('model','')
    if model not in MANIFEST['models']:raise ValueError('opencode_go 尚未收录此模型的官方端点，请更新供应商模块后再使用')
    return MANIFEST['models'][model]

def endpoint(profile):
    base=profile.get('baseUrl','').strip().rstrip('/') or BASE
    if base!=BASE:raise ValueError('opencode_go 使用官方 Go 地址，请勿填写其他供应商或单个模型端点')
    protocol=route(profile)['protocol']
    suffix={'chat':'/chat/completions','responses':'/responses','messages':'/messages','google':'/models/'+profile['model']+':streamGenerateContent?alt=sse'}[protocol]
    return BASE+suffix

def image(part):
    value=part.get('image_url',{}).get('url','')
    match=re.fullmatch(r'data:(image/(?:png|jpeg|gif|webp));base64,([A-Za-z0-9+/=\s]+)',value)
    if not match:raise ValueError('opencode_go 图片须使用受支持的内嵌图片')
    return match[1],match[2]

def parts(content,protocol,role):
    content=[{'type':'text','text':content}] if isinstance(content,str) else content
    result=[]
    for p in content:
        if p.get('type')=='text':
            result.append({'text':p['text']} if protocol=='google' else {'type':('output_text' if role=='assistant' else 'input_text') if protocol=='responses' else 'text','text':p['text']})
        elif p.get('type')=='image_url':
            mime,data=image(p)
            if protocol=='google':result.append({'inlineData':{'mimeType':mime,'data':data}})
            elif protocol=='messages':result.append({'type':'image','source':{'type':'base64','media_type':mime,'data':data}})
            else:result.append({'type':'input_image','image_url':p['image_url']['url']})
        else:raise ValueError('opencode_go 收到不支持的消息内容类型')
    return result

def apply_reasoning(profile,body):
    selected=profile.get('reasoningByModel',{})
    if not isinstance(selected,dict):raise ValueError('模型思考强度配置格式无效')
    level=selected.get(profile['model'],'')
    if level=='':return
    options=route(profile).get('reasoning',{}).get('options',{})
    if not isinstance(level,str) or level not in options:raise ValueError('此模型不支持所选思考强度，请重新选择')
    def merge(target,patch):
        for key,value in patch.items():
            if isinstance(value,dict):merge(target.setdefault(key,{}),value)
            else:target[key]=copy.deepcopy(value)
    # Patches come only from this installed provider's reviewed manifest.
    merge(body,options[level])

def prepare(profile,messages):
    url=endpoint(profile);model=profile['model'];settings=route(profile);protocol=settings['protocol'];session=profile.get('_session','')
    if not re.fullmatch(r'snlm-[a-f0-9]{64}',session):raise ValueError('模型请求缺少稳定的会话上下文')
    headers={'User-Agent':MANIFEST['userAgent'],'x-opencode-session':session}
    if profile.get('apiKey'):headers['Authorization']='Bearer '+profile['apiKey']
    if protocol=='chat':body={'model':model,'messages':messages,'stream':True}
    elif protocol=='responses':
        body={'model':model,'input':[{'role':m['role'],'content':parts(m['content'],protocol,m['role'])} for m in messages],'stream':True,'store':False}
    elif protocol=='messages':
        headers['anthropic-version']='2023-06-01'
        # Messages requires max_tokens. Use the model's published native output
        # limit rather than imposing the app's former short answer cap.
        body={'model':model,'stream':True,'max_tokens':settings['maxOutputTokens'],'messages':[]}
        system=[]
        for m in messages:
            if m['role']=='system':system.extend(parts(m['content'],protocol,'user'));continue
            converted=parts(m['content'],protocol,m['role'])
            if body['messages'] and body['messages'][-1]['role']==m['role']:body['messages'][-1]['content'].extend(converted)
            else:body['messages'].append({'role':m['role'],'content':converted})
        if system:body['system']=system
    else:
        body={'contents':[{'role':'model' if m['role']=='assistant' else 'user','parts':parts(m['content'],protocol,m['role'])} for m in messages if m['role']!='system']}
        system=[p for m in messages if m['role']=='system' for p in parts(m['content'],protocol,'user')]
        if system:body['systemInstruction']={'parts':system}
    if isinstance(profile.get('temperature'),(int,float)):
        if protocol=='google':body['generationConfig']={'temperature':profile['temperature']}
        else:body['temperature']=profile['temperature']
    apply_reasoning(profile,body)
    if protocol=='google':
        # Go Gemini streams thought summaries only when explicitly requested.
        # Preserve the selected effort (or server default) and temperature.
        body.setdefault('generationConfig',{}).setdefault('thinkingConfig',{})['includeThoughts']=True
    return url,body,headers,Decoder(protocol)

def chunk(text='',thought='',finish=None):
    choice={'delta':{'content':text,'reasoning_content':thought}}
    if finish:choice['finish_reason']=finish
    return {'choices':[choice]}

def stop(reason):
    if reason in ('max_tokens','MAX_TOKENS','length'):raise ValueError('opencode_go 模型输出达到服务端上限，未发布完整正文')
    if reason not in ('stop','STOP','end_turn','stop_sequence','completed'):raise ValueError('opencode_go 模型未正常完成（过滤、工具调用或未知结束状态）')
    return 'stop'

class Decoder:
    def __init__(self,protocol):self.protocol=protocol;self.text_seen=False;self.stop_reason=None
    def decode(self,value):
        if value.get('error') or value.get('type')=='error':raise ValueError('opencode_go 服务返回流式错误，请检查订阅状态或稍后重试')
        if self.protocol=='chat':
            for c in value.get('choices',[]):
                if c.get('finish_reason'):stop(c['finish_reason'])
            return value
        if self.protocol=='google':
            if value.get('promptFeedback',{}).get('blockReason'):raise ValueError('opencode_go 模型拒绝了输入，未生成正文')
            candidate=next((c for c in value.get('candidates',[]) if c.get('index',0)==0),{})
            text='';thought=''
            for p in candidate.get('content',{}).get('parts',[]):
                if p.get('thought'):thought+=p.get('text','')
                else:text+=p.get('text','')
            finish=stop(candidate['finishReason']) if candidate.get('finishReason') else None
            return chunk(text,thought,finish)
        kind=value.get('type','')
        if self.protocol=='responses':
            if kind=='response.output_text.delta':self.text_seen=True;return chunk(value.get('delta',''))
            if kind in ('response.reasoning_summary_text.delta','response.reasoning_text.delta'):return chunk(thought=value.get('delta',''))
            if kind in ('response.failed','response.incomplete','response.refusal.delta'):raise ValueError('opencode_go Responses 未完整返回正文')
            if kind=='response.completed' or value.get('object')=='response':
                response=value.get('response',value);stop(response.get('status',''))
                text=''
                for item in response.get('output',[]):
                    if item.get('type') not in ('message','reasoning'):raise ValueError('opencode_go 返回了应用不支持的工具调用')
                    for part in item.get('content',[]):
                        if part.get('type')=='refusal':raise ValueError('opencode_go 模型拒绝了请求')
                        if part.get('type')=='output_text' and not self.text_seen:text+=part.get('text','')
                return chunk(text,finish='stop')
            return chunk()
        if kind=='message' and 'content' in value:
            text='';thought=''
            for p in value['content']:
                if p.get('type')=='text':text+=p.get('text','')
                elif p.get('type')=='thinking':thought+=p.get('thinking','')
                elif p.get('type')=='tool_use':raise ValueError('opencode_go 返回了应用不支持的工具调用')
            return chunk(text,thought,stop(value.get('stop_reason')))
        if kind=='content_block_start':
            block=value.get('content_block',{})
            if block.get('type')=='tool_use':raise ValueError('opencode_go 返回了应用不支持的工具调用')
            return chunk(block.get('text',''),block.get('thinking',''))
        if kind=='content_block_delta':
            delta=value.get('delta',{});return chunk(delta.get('text',''),delta.get('thinking',''))
        if kind=='message_delta':
            reason=value.get('delta',{}).get('stop_reason')
            if reason:self.stop_reason=stop(reason)
        if kind=='message_stop':
            if not self.stop_reason:raise ValueError('opencode_go Messages 缺少有效结束状态')
            return chunk(finish=self.stop_reason)
        return chunk()

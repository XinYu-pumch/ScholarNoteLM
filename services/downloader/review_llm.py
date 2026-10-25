"""Streaming chat client shared by review translation, writing and citation repair."""
import asyncio,json,time,socket,ssl
from urllib.parse import urlsplit
import httpx
import llm_provider
from network import system_proxy

class Cancelled(Exception):pass

class UpstreamFailure(ValueError):
    """Keep only safe diagnostics; upstream bodies may echo credentials/prompts."""
    def __init__(self,status,body):
        import re
        self.status=status
        self.rejected_fields=set()
        fields=('reasoning_effort','thinking_level','thinkingLevel','thinking.type','enable_thinking')
        try:
            data=json.loads(body);error=data.get('error',data)
            param=error.get('param','') if isinstance(error,dict) else ''
            message=error.get('message','') if isinstance(error,dict) else ''
            for field in fields:
                if isinstance(param,str) and (param==field or param.endswith('.'+field)):
                    self.rejected_fields.add(field)
                elif isinstance(message,str) and field in message and re.search(r'invalid|unsupported|not supported|must be|allowed|非法|无效|不支持',message,re.I):
                    self.rejected_fields.add(field)
        except (ValueError,TypeError,AttributeError):pass
        super().__init__(f'模型请求失败（HTTP {status}）；请检查模型、密钥及上下文长度')

class ConnectionFailure(ValueError):
    def __init__(self,exc,endpoint,phase,attempts,received,reasoning,network_mode='direct'):
        chain=[];current=exc
        while current is not None and len(chain)<8:
            chain.append(current);current=current.__cause__
        if any(isinstance(v,socket.gaierror) for v in chain):kind='DNS';label='模型域名解析失败'
        elif any(isinstance(v,ssl.SSLError) for v in chain):kind='TLS';label='模型 TLS 连接或证书校验失败'
        elif isinstance(exc,httpx.ProxyError):kind='proxy';label='模型代理连接失败'
        elif isinstance(exc,httpx.ConnectTimeout):kind='connect_timeout';label='建立模型连接超时'
        elif isinstance(exc,httpx.TimeoutException):kind='read_timeout';label='等待模型数据超时（连续无数据）'
        elif isinstance(exc,httpx.ConnectError):kind='connect';label='无法建立模型连接'
        else:kind='stream';label='模型流式连接中断'
        host=urlsplit(endpoint).hostname or '模型服务'
        self.diagnostics={'kind':kind,'type':type(exc).__name__,'causeTypes':[type(v).__name__ for v in chain],
            'host':host,'phase':phase,'attempts':attempts,'received':received,'reasoningCharacters':reasoning,'networkMode':network_mode,
            'osErrors':[{'type':type(v).__name__,'errno':v.errno} for v in chain if isinstance(v,OSError) and isinstance(v.errno,int)]}
        state=f'已接收正文 {received} 字、推理 {reasoning} 字' if received or reasoning else '尚未收到模型内容'
        route='系统代理' if network_mode=='system_proxy' else '直连 API'
        super().__init__(f'{label}（{type(exc).__name__} · {host} · {route} · 尝试 {attempts} 次）；{state}')

def endpoint(base):
    base=base.strip().rstrip('/');u=urlsplit(base)
    if u.username or u.password or u.query or u.fragment or not u.hostname:raise ValueError('模型地址无效')
    if u.scheme!='https' and not (u.scheme=='http' and u.hostname in ('localhost','127.0.0.1','::1')):raise ValueError('模型须使用 HTTPS，本机服务可使用 HTTP')
    for suffix in ('/chat/completions','/models'):
        if base.endswith(suffix):base=base[:-len(suffix)];break
    return base+('/v1' if not urlsplit(base).path.strip('/') else '')+'/chat/completions'

async def test_connection(profile):
    from llm_diagnostics import test_connection as diagnose
    return await diagnose(profile)


async def chat(profile,messages,cancelled,progress=lambda **kw:None,on_text=None,on_reasoning=None,*,on_response=None,request_transform=None):
    output='';reasoning=0;reasoning_text='';last=0;phase='connecting';attempts=0;network_mode='direct'
    provider=llm_provider.adapter(profile);decode=lambda value:value
    def receive(value):
        nonlocal output,reasoning,reasoning_text,last
        if value.get('error'):raise ValueError('模型服务返回错误，请检查配置与上下文长度')
        choices=value.get('choices') or []
        if not choices:return False
        choice=choices[0];delta=choice.get('delta') or choice.get('message') or {}
        def text(v):return v if isinstance(v,str) else ''.join(x.get('text','') for x in v if isinstance(x,dict)) if isinstance(v,list) else ''
        output+=text(delta.get('content'))
        thought=text(delta.get('reasoning_content')) or text(delta.get('reasoning'))
        if not thought and isinstance(delta.get('reasoning_details'),list):thought=''.join(text(v.get('text')) for v in delta['reasoning_details'] if isinstance(v,dict))
        reasoning+=len(thought)
        if on_reasoning is not None and thought:
            reasoning_text+=thought
            on_reasoning(reasoning_text)
        if on_text is not None:on_text(output)
        if choice.get('finish_reason') in ('length','content_filter'):raise ValueError('模型输出被截断或过滤，未发布正文')
        if time.monotonic()-last>.5:
            progress(received=len(output),reasoningCharacters=reasoning);last=time.monotonic()
        return bool(choice.get('finish_reason'))
    def receive_response(value):
        if on_response is not None:on_response(value)
        return receive(decode(value))
    async def request():
        nonlocal phase,network_mode,decode
        phase='connecting'
        body={'model':profile['model'],'messages':messages,'stream':True}
        if isinstance(profile.get('temperature'),(int,float)):body['temperature']=profile['temperature']
        timeout=max(10,min(600,int(profile.get('timeout',120))))
        headers={'Authorization':'Bearer '+profile['apiKey']} if profile.get('apiKey') else {}
        url=profile['endpoint']
        if provider:
            url,body,headers,decoder=provider.prepare(profile,messages);decode=decoder.decode
        if request_transform is not None:body=request_transform(body)
        proxy=system_proxy(url);network_mode='system_proxy' if proxy else 'direct'
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout,connect=min(25,timeout)),follow_redirects=False,trust_env=False,proxy=proxy) as client:
            async with client.stream('POST',url,json=body,headers=headers) as response:
                phase='response'
                progress(connectionStatus='connected',connectionAttempts=attempts,networkMode=network_mode)
                if not response.is_success:
                    data=b''
                    async for part in response.aiter_bytes():
                        data+=part[:max(0,16384-len(data))]
                        if len(data)>=16384:break
                    raise UpstreamFailure(response.status_code,data)
                if 'application/json' in response.headers.get('content-type',''):
                    receive_response(json.loads(await response.aread()));return
                phase='streaming'
                payload=[];finished=False;done=False
                async for line in response.aiter_lines():
                    if line.startswith('data:'):payload.append(line[5:].lstrip())
                    elif not line.strip() and payload:
                        data='\n'.join(payload);payload=[]
                        if data=='[DONE]':done=True;break
                        finished=receive_response(json.loads(data)) or finished
                if payload:
                    data='\n'.join(payload)
                    if data=='[DONE]':done=True
                    else:finished=receive_response(json.loads(data)) or finished
                if not done and not finished:raise ValueError('模型连接中断，未收到完成标志，未发布正文')
    async def connect():
        nonlocal attempts
        for attempt in range(2):
            attempts=attempt+1
            try:return await request()
            except (httpx.ConnectError,httpx.ConnectTimeout) as exc:
                problem=ConnectionFailure(exc,profile['endpoint'],phase,attempts,len(output),reasoning,network_mode)
                if attempt or phase!='connecting' or problem.diagnostics['kind']=='TLS':raise
                if cancelled():raise Cancelled('已取消')
                progress(connectionStatus='retrying',connectionAttempts=attempts+1,networkMode=network_mode)
                await asyncio.sleep(.5)
    task=asyncio.create_task(connect())
    try:
        while not task.done():
            if cancelled():raise Cancelled('已取消')
            await asyncio.wait({task},timeout=.15)
        await task
        if cancelled():raise Cancelled('已取消')
        if not output.strip():raise ValueError('模型只返回了推理内容，没有返回正文')
        progress(received=len(output),reasoningCharacters=reasoning)
        return output
    except httpx.HTTPError as exc:raise ConnectionFailure(exc,profile['endpoint'],phase,attempts,len(output),reasoning,network_mode) from None
    finally:
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)

def object_json(text):
    text=text.strip()
    if text.startswith('```'):
        lines=text.splitlines();text='\n'.join(lines[1:-1]) if lines[-1].strip()=='```' else text
    try:value=json.loads(text)
    except (ValueError,TypeError):raise ValueError('模型未返回完整、有效的 JSON') from None
    if not isinstance(value,dict):raise ValueError('模型 JSON 必须是对象')
    return value

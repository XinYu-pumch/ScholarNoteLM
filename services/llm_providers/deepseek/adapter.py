"""Official DeepSeek only; independent of OpenCode Go and its session protocol."""
import json
from pathlib import Path

MANIFEST=json.loads(Path(__file__).with_name('manifest.json').read_text())

def endpoint(profile):
    base=profile.get('baseUrl','').strip().rstrip('/') or MANIFEST['baseUrl']
    if base!=MANIFEST['baseUrl']:raise ValueError('DeepSeek 使用官方 API 地址')
    if profile.get('model') not in MANIFEST['models']:raise ValueError('DeepSeek 尚未收录此模型，请更新供应商模块')
    return base+'/chat/completions'

def prepare(profile,messages):
    url=endpoint(profile)
    selected=profile.get('reasoningByModel',{})
    if not isinstance(selected,dict):raise ValueError('模型思考强度配置格式无效')
    level=selected.get(profile['model'],'')
    levels=MANIFEST['models'][profile['model']]['reasoning']['levels']
    if not isinstance(level,str) or (level and level not in levels):raise ValueError('此模型不支持所选思考强度，请重新选择')
    body={'model':profile['model'],'messages':messages,'stream':True,'thinking':{'type':'enabled'}}
    if level:body['reasoning_effort']=level
    # The official API ignores temperature in thinking mode. Do not imply it is applied.
    headers={'Authorization':'Bearer '+profile['apiKey']} if profile.get('apiKey') else {}
    return url,body,headers,Decoder()

class Decoder:
    def decode(self,value):
        if value.get('error'):raise ValueError('DeepSeek 服务返回错误，请检查配置或稍后重试')
        for choice in value.get('choices',[]):
            reason=choice.get('finish_reason')
            if reason and reason!='stop':raise ValueError('DeepSeek 模型未完整返回正文（输出上限、过滤或工具调用）')
        return value

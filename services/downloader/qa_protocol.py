"""Strict, side-effect-free adapters for the QA model's public output protocol."""
import json,re
import xml.etree.ElementTree as ET

class ProtocolError(ValueError):
    def __init__(self,message,raw=''):
        super().__init__(message);self.raw=raw

PLANNING={'规划问题','判断证据缺口','回答前核对'}
FORMAT_RULES='本接口只接收正文中的单个 JSON 对象。工具是 JSON 的 tools 数组数据，不是原生 function call。不要输出 DSML、XML、工具标签、代码围栏或额外说明。严格使用本阶段给定字段；不要省略必需字段。'

def strict_json(text):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('重复 JSON 字段')
            result[key]=value
        return result
    def constant(value):raise ValueError('非有限 JSON 数值')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=constant)

def object_output(text):
    """Unwrap a single complete object; never synthesize syntax or salvage nested fragments."""
    text=text.strip().lstrip('\ufeff');note=''
    fence=re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```',text,re.S|re.I)
    if fence:text=fence[1].strip();note='已移除 JSON 代码围栏'
    try:value=strict_json(text)
    except (ValueError,RecursionError):
        # Scan top-level balanced braces, respecting quotes. A truncated outer
        # object must not cause an inner valid object to be mistaken for the plan.
        depth=0;quoted=False;escaped=False;start=0;blocks=[]
        for i,ch in enumerate(text):
            if quoted:
                if escaped:escaped=False
                elif ch=='\\':escaped=True
                elif ch=='"':quoted=False
                continue
            if ch=='"' and depth:quoted=True
            elif ch=='{':
                if not depth:start=i
                depth+=1
            elif ch=='}':
                depth-=1
                if depth<0:raise ProtocolError('JSON 括号不完整',text)
                if not depth:blocks.append(text[start:i+1])
        if depth or quoted or len(blocks)!=1:raise ProtocolError('模型未返回唯一、完整的 JSON 对象',text)
        # A top-level array is not a prose envelope.
        if text.startswith(('[','{')):raise ProtocolError('模型未返回有效的 JSON 对象',text)
        try:value=strict_json(blocks[0])
        except (ValueError,RecursionError):raise ProtocolError('模型 JSON 内容格式无效',text) from None
        note='已从说明文字中提取唯一完整 JSON 对象'
    if not isinstance(value,dict):raise ProtocolError('模型 JSON 必须是对象',text)
    return value,note

def dsml_output(text,stage,payload):
    if stage not in PLANNING:raise ProtocolError('此阶段不能返回工具调用标签',text)
    # Only the complete public wrapper observed in provider output is accepted.
    # No arbitrary XML, DTD/entity expansion, code execution or dynamic tool lookup.
    if '<!' in text or '<?' in text:raise ProtocolError('工具标签包含不支持的声明',text)
    normalized=re.sub(r'<(/?)｜｜DSML｜｜\s+(calls|invoke|parameter)\b',r'<\1\2',text.strip())
    try:root=ET.fromstring(normalized)
    except (ET.ParseError,ValueError):raise ProtocolError('工具调用标签不完整，未执行其中的调用',text) from None
    def whitespace(value):return not value or not value.strip()
    if root.tag!='calls' or root.attrib or not whitespace(root.text) or not len(root):raise ProtocolError('工具调用容器无效',text)
    actions=[]
    for node in root:
        if node.tag!='invoke' or set(node.attrib)!={'name'} or not whitespace(node.text) or not whitespace(node.tail):raise ProtocolError('工具调用标签结构无效',text)
        action={'tool':node.attrib['name']}
        for param in node:
            if param.tag!='parameter' or set(param.attrib)!={'name','string'} or len(param) or not whitespace(param.tail):raise ProtocolError('工具参数标签结构无效',text)
            key=param.attrib['name'];value=param.text or ''
            if key in action:raise ProtocolError('工具参数重复',text)
            if param.attrib['string']=='false':
                try:value=strict_json(value)
                except (ValueError,RecursionError):raise ProtocolError('工具参数不是有效 JSON 值',text) from None
            elif param.attrib['string']!='true':raise ProtocolError('工具参数 string 标识无效',text)
            action[key]=value
        actions.append(action)
    # This means only "more actions requested", never "evidence is sufficient".
    reason='模型返回了读取工具请求；已转换为待校验参数，证据是否充分尚未确认'
    value={'queries':[],'tools':actions,'reason':reason}
    if stage=='规划问题':value.update(aspects=[payload['question']],note=reason)
    else:value.update(enough=False,coverage=[])
    return value,'已兼容 DSML 工具标签；调用仍须通过工具白名单、参数和文献范围校验'

def validate(value,stage):
    if stage in ('拆解问答问题','判断问答材料','补充问答查询'):
        requests=value.get('historyRequests',[])
        if not isinstance(requests,list):raise ProtocolError('historyRequests 必须为数组')
        for request in requests:
            if not isinstance(request,dict) or request.get('tool')!='read_previous_evidence' or not isinstance(request.get('runId'),str) or not re.fullmatch('[a-f0-9]{32}',request['runId']):raise ProtocolError('历史证据工具须有有效 runId')
            for field,pattern in (('referenceIds','[ER][1-9][0-9]*'),('blockIds','[TR][1-9][0-9]*')):
                ids=request.get(field,[])
                if not isinstance(ids,list) or any(not isinstance(i,str) or not re.fullmatch(pattern,i) for i in ids):raise ProtocolError('历史证据选择编号无效')
        if stage=='拆解问答问题':
            route=value.get('route','research')
            if route not in ('chat','clarify','rewrite','evidence','research'):raise ProtocolError('问答意图无效')
            if value.get('route')=='research' and not value.get('queries'):raise ProtocolError('研究问题须给出结合历史、可独立理解的检索 query')
            if route in ('chat','clarify','rewrite') and (value.get('queries') or (route!='rewrite' and requests)):raise ProtocolError('普通交流、澄清、纯改写不能发起新检索')
            if route=='rewrite' and (not requests or any(r.get('referenceIds') for r in requests)):raise ProtocolError('纯改写须选择历史回答或具体图表的结构与引用绑定')
        if not isinstance(value.get('queries'),list) or any(not isinstance(q,dict) or not isinstance(q.get('query'),str) or not isinstance(q.get('purpose',''),str) for q in value['queries']):raise ProtocolError('queries 格式无效')
        if stage=='拆解问答问题':
            if not isinstance(value.get('aspects'),list) or any(not isinstance(x,str) for x in value['aspects']):raise ProtocolError('aspects 须为文本数组')
        else:
            if type(value.get('enough')) is not bool or not isinstance(value.get('reason'),str):raise ProtocolError('充分性判断格式无效')
            if not isinstance(value.get('coverage'),list):raise ProtocolError('coverage 必须为数组')
            for row in value['coverage']:
                if not isinstance(row,dict) or not isinstance(row.get('aspect'),str) or row.get('status') not in ('supported','partial','missing','conflicting') or not isinstance(row.get('gap',''),str):raise ProtocolError('coverage 条目无效')
                if not isinstance(row.get('evidenceIds',[]),list) or any(not isinstance(x,str) for x in row.get('evidenceIds',[])):raise ProtocolError('coverage 证据编号无效')
        return value
    def array(key):
        if not isinstance(value.get(key),list):raise ProtocolError(key+' 必须为数组')
    def string(key):
        if key in value and (not isinstance(value[key],str) or len(value[key])>4000):raise ProtocolError(key+' 必须为不超过 4000 字符的文本')
    if stage=='规划问题':
        array('aspects')
        if any(not isinstance(v,str) or len(v)>2000 for v in value['aspects']):raise ProtocolError('aspects 要点须为文本')
        if 'queries' not in value and 'tools' not in value:raise ProtocolError('规划缺少 queries 和 tools')
        string('note')
    if stage in ('判断证据缺口','回答前核对'):
        if type(value.get('enough')) is not bool:raise ProtocolError('enough 必须为布尔值')
        string('reason')
        if stage=='判断证据缺口' or 'coverage' in value:array('coverage')
        for item in value.get('coverage',[]):
            if not isinstance(item,dict) or not isinstance(item.get('aspect'),str) or item.get('status') not in ('supported','partial','missing','conflicting'):raise ProtocolError('coverage 条目格式无效')
            if not isinstance(item.get('evidenceIds',[]),list) or any(not isinstance(x,str) for x in item.get('evidenceIds',[])):raise ProtocolError('coverage 引用须为文本数组')
            if not isinstance(item.get('gap',''),str):raise ProtocolError('coverage 缺口须为文本')
    if stage in ('整理证据','修复证据摘录'):array('findings')
    if stage=='RCS 评估':
        if 'relation' not in value or 'score' not in value:raise ProtocolError('RCS 缺少 score 或 relation')
    if stage=='逐篇阅读':array('cards')
    return value

def parse(text,stage,payload):
    try:
        value,note=dsml_output(text,stage,payload) if text.lstrip().startswith('<｜｜DSML｜｜') else object_output(text)
        return validate(value,stage),note
    except ProtocolError as exc:
        exc.raw=text;raise

def fallback(stage,payload):
    if stage=='规划问题':return {'aspects':[payload['question']],'queries':[{'query':payload['question'],'purpose':'规划格式未恢复，使用原问题检索'}],'tools':[]}
    if stage in ('整理证据','修复证据摘录'):return {'findings':[]}
    if stage=='RCS 评估':return {'unassessed':True}
    if stage=='逐篇阅读':return {'cards':[],'incomplete':True}
    if stage in ('判断证据缺口','回答前核对'):
        return {'enough':False,'incomplete':True,'coverage':[],'queries':[],'tools':[],'reason':'规划格式未恢复，停止追加检索；证据充足性未确认，基于已有原文作有限回答'}
    return None

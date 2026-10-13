"""Deterministic table schema and document cross-references; no inference calls."""
import hashlib,re

VERSION='review-unit-object-refs-v3'
XREF=re.compile(r'\{\{ref:([RT][1-9][0-9]*)\}\}')
PREFIXED_XREF=re.compile(r'(?:(?:图|表|(?<![A-Za-z])(?:Figure|Fig\.?|Table))\s*)?'+XREF.pattern,re.I)
MANUAL_NUMBER=re.compile(r'(?:图|表)\s*[RT]?[0-9]+|\b(?:Fig(?:ure)?\.?|Table)\s*[RT]?[0-9]+',re.I)
TABLE_FIELDS={'type','table_id','title','columns','rows','notes'}

def validate_table(block):
    if set(block)!=TABLE_FIELDS or not isinstance(block['table_id'],str) or not re.fullmatch(r'T[1-9][0-9]*',block['table_id']):
        raise ValueError('生成表须包含 type、table_id（T1 等）、title、columns、rows、notes')
    if not isinstance(block['title'],str) or not block['title'].strip() or not isinstance(block['notes'],str):raise ValueError('生成表须有不带编号的标题，notes 须为字符串')
    cols=block['columns'];rows=block['rows']
    if not isinstance(cols,list) or not cols or any(not isinstance(c,str) or not c.strip() for c in cols):raise ValueError('生成表的列名不能为空')
    if not isinstance(rows,list) or not rows or any(not isinstance(r,list) or len(r)!=len(cols) or any(not isinstance(c,str) for c in r) for r in rows):raise ValueError('生成表每行单元格数必须与列数相等；单元格须为字符串')

def table_texts(block):
    return [block['title'],*block['columns'],*(c for row in block['rows'] for c in row),block['notes']]

def table_markdown(block):
    # Escape literal pipes/backslashes so cell content cannot change table shape.
    def cell(value):return value.replace('\\','\\\\').replace('|',r'\|').replace('\r','').replace('\n','<br>')
    rows=[block['columns'],['---']*len(block['columns']),*block['rows']]
    return '\n'.join('| '+' | '.join(cell(c) for c in row)+' |' for row in rows)

def key(block,node_id):
    if block['type']=='resource':return (block['kind'],block['resourceId'])
    if block['type']=='table':return ('table','generated:'+node_id+':'+block['table_id'])

def register(numbers,block,node_id):
    identity=key(block,node_id)
    if identity is not None and identity not in numbers:numbers[identity]=1+sum(k[0]==identity[0] for k in numbers)

def anchor(block,node_id,index):
    raw=repr((key(block,node_id),node_id,index)).encode()
    return 'obj_'+hashlib.sha256(raw).hexdigest()[:24]

def label(numbers,block,node_id,language='zh'):
    identity=key(block,node_id)
    return (('Figure ' if identity[0]=='figure' else 'Table ') if language=='en' else ('图 ' if identity[0]=='figure' else '表 '))+str(numbers[identity])

def resolve(text,targets,node_id):
    def replace(match):
        candidates=targets.get(match[1],[])
        if not candidates:raise ValueError('图表交叉引用没有对应的正文对象：'+match[1])
        target=next((v for v in candidates if v['node_id']==node_id),candidates[0])
        return '['+target['label']+'](#'+target['anchor']+')'
    # Consume a redundant type prefix only at a real, bound placeholder.
    result=PREFIXED_XREF.sub(replace,text)
    if '{{' in result or '}}' in result:raise ValueError('图表交叉引用标记无效')
    return result

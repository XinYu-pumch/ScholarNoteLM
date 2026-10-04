"""Conversation context and scoped, immutable historical evidence retrieval."""
import copy,json,re
import review_content
from pathlib import Path


def read(path,default=None):
    return json.loads(path.read_text(encoding='utf8')) if path.is_file() else default


def collect(root,run_ids):
    history=[]
    for rid in run_ids:
        job=read(root/rid/'job.json',{})
        item={'runId':rid,'question':job.get('question',''),'answer':'',
              'note':'历史回答仅用于理解对话，不是当前原文证据；旧引用须通过工具重新绑定。'}
        if job.get('state')=='done':
            item.update(answer=job.get('answer',''),citationRefs=job.get('citationRefs',[]),
                        canReadEvidence=bool(job.get('citationRefs') or job.get('usedEvidence')))
            section=read(root/rid/'answer-section.json',{})
            item['blocks']=[{'id':b.get('table_id',b.get('resource_id','')),'type':b['type'],
                             'title':b.get('title','')} for b in section.get('sourceBlocks',[]) if b['type']!='markdown']
        history.append(item)
    return history


def load(root,history,request,allowed_pmids):
    """Never accept arbitrary paths/runs, uncited pool IDs, or out-of-scope papers."""
    rid=request['runId']
    if not re.fullmatch('[a-f0-9]{32}',rid) or not any(h.get('runId')==rid and h.get('answer') for h in history):
        raise ValueError('历史回答不在当前对话的有效上下文中')
    path=root/rid
    if path.is_symlink() or path.resolve().parent!=root.resolve():raise ValueError('历史路径无效')
    job=read(path/'job.json',{})
    if job.get('state')!='done':raise ValueError('历史回答尚未成功完成')
    rows=read(path/'evidence.json',[]);bundle=read(path/'answer-bundle.json',{})
    section=read(path/'answer-section.json',{})
    refs=job.get('citationRefs') or [{'id':eid} for eid in job.get('usedEvidence',[])]
    cited={r['id'] for r in refs}
    ids=request.get('referenceIds') or [r['id'] for r in refs]
    source_blocks=section.get('sourceBlocks')
    if request.get('blockIds'):
        wanted=set(request['blockIds'])
        blocks=[b for b in source_blocks or [] if b.get('table_id',b.get('resource_id')) in wanted]
        if len(blocks)!=len(wanted):raise ValueError('历史图表编号不存在')
        ids=list(dict.fromkeys([*re.findall(r'\[([ER][1-9][0-9]*)\]',json.dumps(blocks,ensure_ascii=False)),
             *[b['resource_id'] for b in blocks if b['type']=='resource']]))
        source_blocks=blocks
    elif request.get('referenceIds'):
        source_blocks=None  # A partial selection is not a complete answer for rewriting.
    if not set(ids)<=cited:raise ValueError('只能取回此历史回答实际引用的证据')
    by_eid={r['eid']:r for r in rows};by_resource={r['id']:r for r in bundle.get('resources',[])}
    selected={};bindings={};missing=[]
    for ident in ids:
        if ident.startswith('E'):
            row=by_eid.get(ident)
            pool=next((r for r in bundle.get('evidencePool',[]) if r['id']==ident),None)
            if row and pool and (pool['chunkId']!=row['id'] or pool['documentVersion']!=row['metadata']['documentVersion'] or pool['text']!=row['text']):
                raise ValueError('历史证据编号与原文快照不一致')
        else:
            obj=by_resource.get(ident)
            row=next((r for r in rows if any(o['id']==obj['resourceId'] for o in r.get('resources',[]))),None) if obj else None
            if row:
                raw=next(o for o in row['resources'] if o['id']==obj['resourceId'])
                if raw.get('documentVersion')!=obj.get('documentVersion') or raw.get('content')!=obj.get('content') or raw.get('assetSha256')!=obj.get('assetSha256'):raise ValueError('历史资源编号与图表快照不一致')
        if not row or row['metadata']['pmid'] not in allowed_pmids:
            missing.append(ident);continue
        selected.setdefault(row['id'],copy.deepcopy(row))
        bindings[ident]={'kind':'chunk','stableId':row['id']} if ident.startswith('E') else {'kind':'resource','stableId':by_resource[ident]['resourceId']}
    return {'runId':rid,'rows':list(selected.values()),'bindings':bindings,'unavailable':missing,
            'sourceBlocks':source_blocks if not missing else None,'answer':job.get('answer',''),
            'hasCitations':bool(cited)}


def rebound(result,bundle,table_start=1):
    chunks={r['chunkId']:r['id'] for r in bundle['evidencePool']}
    objects={r['resourceId']:r['id'] for r in bundle['resources']}
    mapping={old:(chunks if b['kind']=='chunk' else objects)[b['stableId']] for old,b in result['bindings'].items()}
    blocks=result.get('sourceBlocks');tables={}
    for block in blocks or []:
        if block['type']=='table':tables[block['table_id']]='T'+str(table_start+len(tables))
    mapping.update(tables)
    def remap(value,key=''):
        if isinstance(value,list):return [remap(v) for v in value]
        if isinstance(value,dict):return {k:remap(v,k) for k,v in value.items()}
        if not isinstance(value,str):return value
        if key in ('resource_id','table_id'):
            if value not in mapping:raise ValueError('历史图表无法绑定到本轮材料')
            return mapping[value]
        def sub(m):
            ident=m[1]
            if ident not in mapping:raise ValueError('历史引用无法绑定到本轮材料')
            return '['+mapping[ident]+']'
        value=review_content.normalize_evidence_ids(value,mapping)
        value=re.sub(r'\[([ER][1-9][0-9]*)\]',sub,value)
        # Cross-references to omitted historical objects must not leak into this answer.
        return re.sub(r'\{\{ref:([ERT][1-9][0-9]*)\}\}',lambda m:'{{ref:'+mapping[m[1]]+'}}' if m[1] in mapping else '原回答中的图表',value)
    return {'runId':result['runId'],'referenceMap':mapping,'unavailable':result['unavailable'],
            'sourceBlocks':remap(blocks) if blocks is not None else None,
            'note':'编号已换为本轮编号。仅作改写来源，科学论断仍以 materialBundle 原文为依据。'}

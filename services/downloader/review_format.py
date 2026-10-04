"""Portable review-part format adapted from BADR core_logic.py.
App tracking stays in private sidecars; FORMAT feeds the writing-unit signature.
"""
import re
import evidence_resources as resources
from typing import Any,Dict
FORMAT='badr-pmid-scoped-resources-v2'

def _sections_to_markdown_content(data: Dict[str, Any]) -> str:
    parts = []
    for item in data.get("sections", []) or []:
        sid = str(item.get("node_id", "")).strip()
        title = str(item.get("title", "")).strip()
        md = str(item.get("markdown", "")).strip()
        if not sid or not md:
            continue
        level = min(len(sid.split(".")), 6)
        heading = f"{'#' * level} {sid} {title}".strip()
        parts.append(f"{heading}\n\n{md}")
    return "\n\n".join(parts).strip()

def materials(unit,evidence):
    scopes={n['serial']:set() for n in unit['nodes']};refs={};blocks={}
    for node in unit['leaves']:
        sid=node['serial'];refs[sid]={};seen_resources=set();lines=[f"[针对标题 {sid} {node['title']}]:"]
        for i,r in enumerate(evidence.get(node['id'],{}).get('chunks',[])):
            pmid=str(r['metadata']['pmid']);text=r['text']
            if not re.fullmatch(r'\d+',pmid):raise ValueError('素材 PMID 无效')
            scopes[sid].add(pmid);refs[sid].setdefault(pmid,[])
            if text not in refs[sid][pmid]:refs[sid][pmid].append(text)
            lines.append(f'- 素材 {i+1} (PMID: {pmid}): {text}')
            for obj in r.get('resources',[]):
                if obj['id'] in seen_resources:continue
                seen_resources.add(obj['id']);resource_text=resources.public_text(obj)
                lines.append(resource_text);refs[sid][pmid].append(resource_text)
        blocks[sid]='\n'.join(lines) if len(lines)>1 else f"[针对标题 {sid} {node['title']}]:\n无可用素材。"
    return scopes,refs,blocks

def public_part(unit,sections,evidence):
    if sections and all(s.get('citationPoolVersion') for s in sections):
        import review_bundle
        pool=review_bundle.make({'topic':'','config':{'language':'','requirements':''}},unit,evidence)
        by_id={s['node_id']:s for s in sections};pmids=sorted({r['pmid'] for r in pool['evidencePool']});leaves={n['id'] for n in unit['leaves']}
        result={'format':sections[0]['citationPoolVersion'],'unit_id':unit['serial'],
            'sections':[{**by_id[n['id']],'node_id':n['serial'],'title':n['title']} for n in unit['nodes']],
            'citation_validation':{'status':'passed','scope':'unit_shared_pool','problems':[]},
            'citation_scopes':{n['serial']:pmids if n['id'] in leaves else [] for n in unit['nodes']},
            **{k:pool[k] for k in ('evidencePool','resources','retrieval')}}
        result['markdown_content']=_sections_to_markdown_content(result)
        return result
    by_id={s['node_id']:s for s in sections};scopes,refs,_=materials(unit,evidence)
    result={'unit_id':unit['serial'],'sections':[{'node_id':n['serial'],'title':n['title'],'markdown':by_id[n['id']]['markdown']} for n in unit['nodes']],
            'citation_validation':{'status':'passed','problems':[]},'citation_scopes':{s:sorted(v) for s,v in scopes.items()},'reference_materials':refs}
    result['markdown_content']=_sections_to_markdown_content(result)
    return result

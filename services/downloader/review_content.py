"""Presentation of citations and explicit resource blocks, without altering provenance."""
import copy,re
import review_objects as objects
from text_presentation import strip_source_links

PMID=r'\(PMID:\s*\d+(?:\s*,\s*\d+)*\)'
RUN=re.compile(PMID+r'(?:[ \t]*(?:[,，、][ \t]*)?'+PMID+r')+')
BARE_E=re.compile(r'(?<![A-Za-z0-9_\[\\])E([1-9][0-9]*)(?:\s*[-–—]\s*E([1-9][0-9]*))?(?![A-Za-z0-9_\]])')
PROTECTED=re.compile(r'```[\s\S]*?```|`[^`\n]*`|!?\[(?:\\.|[^\]\\])*\]\([^\n)]*\)|https?://[^\s<>]+')
GROUPED_IDS=re.compile(r'\[[ER][1-9][0-9]*(?:[ \t]*[,，、;；][ \t]*[ER][1-9][0-9]*)+\]')

def normalize_evidence_ids(text,sources):
    """Bind bare E IDs/ranges to this unit only; keep the original in sourceBlocks."""
    def replace(match):
        start=int(match[1]);end=int(match[2] or match[1])
        if end<start or end-start>=len(sources):raise ValueError('证据编号范围无效：'+match[0])
        ids=['E'+str(i) for i in range(start,end+1)]
        if any(i not in sources for i in ids):raise ValueError('正文包含不在本单元证据池中的编号：'+match[0])
        return ' '.join('['+i+']' for i in ids)
    def group(match):
        ids=re.findall(r'[ER][1-9][0-9]*',match[0])
        if any(i not in sources for i in ids):raise ValueError('正文包含不在本单元证据池中的编号：'+match[0])
        return ' '.join('['+i+']' for i in ids)
    def normalize(part):return BARE_E.sub(replace,GROUPED_IDS.sub(group,part))
    parts=[];at=0
    for match in PROTECTED.finditer(text):
        parts.extend([normalize(text[at:match.start()]),match[0]]);at=match.end()
    parts.append(normalize(text[at:]))
    return ''.join(parts)

def dedupe_citations(text):
    # Never cross prose, table cells, or line/paragraph boundaries.
    def collapse(match):
        ids=list(dict.fromkeys(re.findall(r'\d+',match[0])))
        return '(PMID: '+', '.join(ids)+')'
    return RUN.sub(collapse,text)

def resolve_citations(text,sources):
    text=normalize_evidence_ids(text,sources)
    return dedupe_citations(re.sub(r'\[([ER][0-9]+)\]',lambda m:'(PMID: '+sources[m[1]]['pmid']+')' if m[1] in sources else m[0],text))

def render_sections(sections,resources,project,numbers=None,evidence=None):
    """Resolve only selected resources from the frozen pool, with document-wide numbering."""
    import evidence_resources
    from review_export import resource_html,generated_table_html,markdown_html
    numbers=numbers if numbers is not None else {}
    by_id={r['id']:r for r in resources};result=[];targets={}
    for section in sections:
        for index,block in enumerate(section.get('blocks',[])):
            if objects.key(block,section['node_id']) is None:continue
            objects.register(numbers,block,section['node_id'])
            ident=block['resource_id'] if block['type']=='resource' else block['table_id']
            targets.setdefault(ident,[]).append({'node_id':section['node_id'],'label':objects.label(numbers,block,section['node_id']),'anchor':objects.anchor(block,section['node_id'],index)})
    for section in sections:
        item=copy.deepcopy(section);blocks=[];sid=section['node_id'];structured=section.get('citationPoolVersion')==objects.VERSION
        sources={r['id']:r for r in [*(section.get('citationRefs',[])),*(evidence or []),*resources]}
        def resolve(text):
            text=strip_source_links(resolve_citations(text,sources)) if section.get('citationPoolVersion') else strip_source_links(dedupe_citations(text))
            return objects.resolve(text,targets,sid) if structured else text
        incoming=section.get('blocks',[{'type':'markdown','text':section['markdown']}])
        if not structured and any(b['type']=='markdown' and (objects.MANUAL_NUMBER.search(b['text']) or markdown_html(b['text']).find('table')) for b in incoming):
            blocks.append({'type':'notice','text':'旧版正文的图表编号尚未绑定对象，文中的图号、表号可能与装配标签不一致；重新生成此写作单元后可使用统一编号。'})
        for index,block in enumerate(incoming):
            if block['type']=='markdown':blocks.append({'type':'markdown','text':resolve(block['text'])});continue
            common={'anchor':objects.anchor(block,sid,index),'label':objects.label(numbers,block,sid)}
            if block['type']=='table':
                entry={**block,**common,'title':resolve(block['title']),'columns':[resolve(c) for c in block['columns']],
                    'rows':[[resolve(c) for c in row] for row in block['rows']],'notes':resolve(block['notes'])}
                entry['html']=generated_table_html(entry);blocks.append(entry);continue
            obj=by_id.get(block['resource_id'])
            if not obj or obj['resourceId']!=block['resourceId'] or obj['documentVersion']!=block['documentVersion'] or obj['pmid']!=block['pmid'] or obj['kind']!=block['kind']:
                raise ValueError('正文图表与冻结证据池不一致')
            entry={**block,**common,'content':strip_source_links(obj['content']),
                'context':[{**p,'text':strip_source_links(p['text'])} for p in obj.get('context',[])]}
            if obj['kind']=='table':entry['html']=resource_html(obj['content'])
            else:
                if block.get('imageInput')!='attached':raise ValueError('未提供给模型的图片不能装配进正文')
                entry['dataUrl']=evidence_resources.image_data(project,obj)
            blocks.append(entry)
        item['displayBlocks']=blocks;item['markdown']=markdown(blocks);result.append(item)
    return result

def markdown(blocks,image_writer=None):
    parts=[]
    for block in blocks:
        if block['type']=='markdown':parts.append(strip_source_links(dedupe_citations(block['text'])));continue
        if block['type']=='notice':parts.append('> '+block['text']);continue
        if block.get('anchor'):parts.append('<a id="'+block['anchor']+'"></a>')
        if block['type']=='table':
            parts.extend(['**'+block['label']+' · '+block['title']+'**',objects.table_markdown(block)])
            if block['notes']:parts.append(block['notes'])
            continue
        label=block['label'];parts.append('**'+label+' · 原文'+('表格' if block['kind']=='table' else '图片')+'** (PMID: '+block['pmid']+')')
        if block['kind']=='table':parts.append(strip_source_links(block['content']))
        elif image_writer:parts.append('!['+label+']('+image_writer(block)+')')
        else:parts.append('['+label+'：图片见正文预览或 HTML / Word 导出]')
    return '\n\n'.join(parts)

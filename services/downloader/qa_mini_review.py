"""Round-based question answering using the review retrieval and resource contracts."""
import content_language as lang
import asyncio,copy,json,time
import corpus_files as files
import vector_chunks as chunks
import review_retrieval as retrieval
import review_bundle as bundle_api
import review_content
import evidence_resources as assets
import qa_protocol,qa_history

POLICY='qa-mini-review-v1'
PLAN='''先结合当前问题与按轮次排列的完整 history 判断意图，再决定是否将用户问题拆解为检索问题。history 中 question 是用户原话，answer 是成功的正式回答；历史回答不是证据，不能直接继承旧 E/R 引用。
输出 JSON：{"route":"research","aspects":["待回答要点"],"queries":[{"query":"独立可理解的完整检索问题","purpose":"要点"}],"historyRequests":[{"tool":"read_previous_evidence","runId":"从 history 选择的 runId","referenceIds":["E1"]}],"reason":"选择此路径的理由"}。
route 可选：chat 仅问候、感谢或使用方法，不输出科学新结论；clarify 结合历史仍无法确定必要指代/研究对象时追问；rewrite 仅缩写、翻译、改格式，不增加事实或结论；evidence 追查前述结论的原文依据；research 新研究问题或需要补证据的追问。简短不代表闲聊：例如“那小鼠呢？”须结合历史识别研究对象和待验证关系并检索。不能确定是否需科学证据时用 research。
chat/clarify 的 queries 和 historyRequests 均为空；rewrite 的 queries 为空，historyRequests 指定要改写的历史回答并省略 referenceIds，以保留原有引用绑定；改写整段回答时也省略 blockIds，只改某个表格时可指定 blockIds。无适合改写的成功历史回答则 clarify。
历史工具只能读取 history 里成功回答实际引用的证据。可按 referenceIds 选择 E/R 引用，或 blockIds 选择生成表 T/原资源 R；省略两者则读取该回答实际引用的全部材料，不是整个旧材料池。工具可与新 queries 同时使用：例如先取回“这个结论”的依据，再查询小鼠证据。只有需要旧原文时才调用。
research 的 queries 应具体、完整、尽量独立，粒度相当于综述终末子标题，明确对象、关系和条件，保留否定、反证、适用范围，不预设结论。不超过 maxQueries。不把全部历史材料池载入。'''
DIRECT='''根据 question 与 history 回复普通交流、使用方法或提出必要澄清。route=chat 不能生成需要文献支持的新科学结论；route=clarify 只询问解答问题所缺的必要信息。历史回答不是原文证据，不虚构引用或声称已检索。直接输出回复正文，默认中文。'''
HISTORY_TOOLS='''可同时返回 historyRequests：[{"tool":"read_previous_evidence","runId":"有效历史回答 ID","referenceIds":["E1"]}]。省略 referenceIds/blockIds 只取该回答已引用的证据，不是整个旧池；不可重复已执行的相同请求。仍需新证据则提出 queries。'''
ASSESS='''依据共享材料池判断是否足以回答用户问题，逐要点说明支持、部分支持、缺失或冲突。未检索到不代表科学界不存在；同一篇论文多个块不是多项独立研究。已明确足够则 enough=true；仅可能足够、尚有关键疑点则 false。
输出 JSON：{"enough":true,"coverage":[{"aspect":"要点","status":"supported","evidenceIds":["E1"],"gap":"仍需解决的具体缺口"}],"queries":[{"query":"下一轮完整检索问题","purpose":"补充缺口或检查反证与边界"}],"reason":"判断理由"}。status 为 supported、partial、missing、conflicting。queries 不超过 maxQueries，不重复 previousQueries。若 round<minRounds，即使初步充分，也需提出有意义的边界/反证/条件补查。若材料不足且 round<maxRounds，提出针对缺口的新 query。达到 maxRounds 时无需再提 query。'''
ASSESS+='\n'+HISTORY_TOOLS
WRITE=bundle_api.SYSTEM+'''\n本任务是回答用户问题的小综述，按 materialBundle.outputContract 输出一个写作单元。综合整个共享池联合回答，不为每个 query 独立写一遍。不重复问题标题；需要分层时用加粗段首。用中文回答，用户指定其他语言则遵循。source citations 和图表协议与综述相同。根据 stopReason 和 coverage 明确尚存缺口，不将材料缺失断言为研究不存在。没有字数上限，按问题需要完整论述。'''


def make_bundle(question,run_id,evidence,language=None):
    node={'id':run_id,'serial':'answer','title':question}
    unit={'serial':'answer','title':question,'nodes':[node],'leaves':[node]}
    snapshot={'topic':question,'config':{'language':lang.label(language) if language else '按用户要求，默认中文','requirements':'Answer the question and preserve evidence limitations.' if language=='en' else '回答用户问题，保留证据边界。'}}
    bundle=bundle_api.make(snapshot,unit,{run_id:{'query':question,'chunks':evidence}})
    return bundle,unit


def messages(project,profile,messages,payload):
    """Attach each real image once with the same R ID used by the review contract."""
    packed=copy.deepcopy(payload);parts=[];notes=[]
    task=packed.get('task',packed)
    english=task['materialBundle']['task'].get('language')=='English'
    for obj in task['materialBundle']['resources']:
        if obj['kind']=='figure':
            if profile.get('model') in profile.get('visionModels',[]) and obj.get('assetPath'):
                parts.extend([{'type':'text','text':f"资源 {obj['id']} · PMID {obj['pmid']}"},
                              {'type':'image_url','image_url':{'url':assets.image_data(project,obj)}}])
                obj['imageInput']='attached'
            else:
                obj['imageInput']='not_provided';notes.append(obj['id']+' 未发送图像，只能依据附近文字，不能声称看过图片或插入原图。')
        obj.pop('assetPath',None)
    if english:
        notes=[n.replace(' 未发送图像，只能依据附近文字，不能声称看过图片或插入原图。',' has no image input. Use nearby text only; do not claim to have seen the image or insert it.') for n in notes]
        for part in parts:
            if part.get('type')=='text':part['text']=part['text'].replace('资源 ','Resource ')
    out=[dict(m) for m in messages];out[0]['content']+='\n'+'\n'.join(notes)
    text=json.dumps(packed,ensure_ascii=False)
    out[-1]['content']=[{'type':'text','text':text},*parts] if parts else text
    return out


def queries(value,limit,seen):
    if not isinstance(value,list):raise ValueError('queries 必须为数组')
    result=[];local=set()
    for item in value:
        if not isinstance(item,dict) or not isinstance(item.get('query'),str) or not isinstance(item.get('purpose',''),str):raise ValueError('query 须有文本和检索目的')
        query=item['query'].strip();key=' '.join(query.casefold().split())
        if query and key not in seen and key not in local:
            local.add(key);result.append({'query':query,'purpose':item.get('purpose','')})
    # The configured search breadth limits actions, never truncates model output.
    return result[:limit]


def stop_reason(round_no,cfg,enough):
    if round_no>=cfg['maxRounds']:return '达到最多检索轮数，基于现有材料回答并说明缺口'
    if round_no>=cfg['minRounds'] and enough:return '材料已足够且达到最少检索轮数'
    return None


def decode_answer(raw,bundle,unit,profile,project):
    value,_=qa_protocol.object_output(raw)
    checked=copy.deepcopy(bundle)
    for obj in checked['resources']:
        if obj['kind']=='figure' and obj.get('assetPath') and profile.get('model') in profile.get('visionModels',[]):
            assets.image_data(project,obj)  # Check the same immutable image used in the request.
            obj['imageFile']={'sha256':obj['assetSha256']}
    sections,errors=bundle_api.decode(value,checked,unit,profile)
    if errors:raise ValueError('问答格式校验未通过：'+'；'.join(dict.fromkeys(str(issue) for issues in errors.values() for issue in issues)))
    if bundle['evidencePool'] and not sections[0]['citationRefs']:raise ValueError('回答没有提供池内证据引用')
    rendered=review_content.render_sections(sections,bundle['resources'],project,evidence=bundle['evidencePool'],language='en' if bundle['task']['language']=='English' else 'zh')[0]
    return rendered


async def run(e,snapshot,cfg,planner,answer,records,papers,coverage,llm,save,event,finish_event,check,add,evidence,path,verify_materials,prepare_retrieval=None):
    language=lang.normalize(snapshot.get('contentLanguage')) if snapshot.get('promptVersion') else None;english=language=='en'
    plan_prompt=lang.PLAN_EN if english else PLAN
    assess_prompt=lang.ASSESS_EN if english else ASSESS
    direct_prompt=lang.DIRECT_EN if english else DIRECT
    write_system=(lang.writing_system(language,bundle_api.SYSTEM)+'\n'+lang.WRITE_EN if english else lang.WRITING_ZH+WRITE[len(bundle_api.SYSTEM):]) if language else WRITE
    question=snapshot['question'];run_id=snapshot['id'];project=files.base(e)
    seen=set();history=[];aspects=[];examined=set();warnings=[]
    rcfg=snapshot.get('retrievalConfig') or retrieval.settings.snapshot(e.ROOT,e.PROJECT)
    retriever=None;history_results=[];history_seen=set();history_bindings=set();round_no=0;route='research'
    def history_payload(bundle):
        result=[];table_start=1
        for previous in history_results:
            result.append(qa_history.rebound(previous,bundle,table_start))
            table_start+=sum(b['type']=='table' for b in previous.get('sourceBlocks') or [])
        return result
    def checkpoint():
        e.write_json(path/'evidence.json',evidence);e.write_json(path/'retrieval.json',history);e.write_json(path/'history-evidence.json',history_payload(make_bundle(question,run_id,evidence,language)[0]))
        save(readingCoverage={**coverage,'candidateChunks':len({h['chunkId'] for r in history for h in r['hits']}),
            'assessedChunks':0,'examinedChunks':len(examined),'examinedPapers':len({r['metadata']['pmid'] for r in evidence if r['id'] in examined}),
            'poolChunks':len(evidence),'poolPapers':len({r['metadata']['pmid'] for r in evidence}),
            'citedChunks':0,'paperRead':[]})
    def material():
        bundle,_=make_bundle(question,run_id,evidence,language)
        return {'question':question,'history':snapshot['history'],'aspects':aspects,'materialBundle':bundle,
                'retrieval':history,'qualityWarnings':warnings,'historyEvidence':history_payload(bundle),'route':route}
    async def planning(stage,payload,prompt):
        value=await llm(planner,stage,payload,prompt)
        if 'materialBundle' in payload:
            examined.update(r['id'] for r in evidence)
        return value
    async def read_history(requests):
        before=len(history_bindings)
        for request in requests:
            key=chunks.digest(request)
            if key in history_seen:continue
            history_seen.add(key);step=event('history_evidence',status='running',action=request)
            try:
                allowed=set(files.current(e) or [])
                if snapshot.get('pmids') is not None:allowed.intersection_update(snapshot['pmids'])
                result=await asyncio.to_thread(qa_history.load,path.parent,snapshot['history'],request,allowed)
                for row in result['rows']:add(row)
                history_results.append(result)
                history_bindings.update((result['runId'],ident) for ident in result['bindings'])
                finish_event(step,result=history_payload(make_bundle(question,run_id,evidence,language)[0])[-1],reason='已按历史引用取回原文并绑定本轮编号')
                if result['unavailable']:warnings.append({'stage':'读取历史证据','reason':'部分历史证据不在当前文献范围或快照不可用：'+', '.join(result['unavailable'])})
            except ValueError as exc:
                warnings.append({'stage':'读取历史证据','reason':str(exc)});finish_event(step,status='warning',reason=str(exc))
            checkpoint()
        return len(history_bindings)>before
    async def assess(round_no,min_rounds):
        while True:
            decision=await planning('判断问答材料',{**material(),'round':round_no,'minRounds':min_rounds,'maxRounds':cfg['maxRounds'],
                'previousQueries':sorted(seen),'maxQueries':cfg['queriesPerRound']},assess_prompt)
            if not await read_history(decision.get('historyRequests',[])):return decision
    plan=await planning('拆解问答问题',{'question':question,'history':snapshot['history'],'maxQueries':cfg['queriesPerRound']},plan_prompt)
    route=plan.get('route','research');save(intent=route,workflow=POLICY,rcsEnabled=False)
    event('intent',route=route,reason=plan.get('reason',''),status='done')
    if route in ('chat','clarify'):
        raw=await llm(answer,'澄清问题' if route=='clarify' else '对话回复',
                      {'question':question,'history':snapshot['history'],'route':route,'guidance':plan.get('reason','')},direct_prompt,structured=False)
        await verify_materials();save(answer=raw,state='done',phase='已完成',round=0,finished=time.time(),stopReason='无需文献检索',
                        citationRefs=[],usedEvidence=[],citationValidation={'status':'not_applicable','problems':[]});return
    aspects=plan['aspects'];pending=queries(plan['queries'],cfg['queriesPerRound'],seen)
    await read_history(plan.get('historyRequests',[]))
    save(aspects=aspects,retrievalConfig=rcfg)
    decision={'enough':False,'coverage':[]};stop=''
    if route=='rewrite':
        if not history_results or any(w['stage']=='读取历史证据' for w in warnings) or any(r['unavailable'] or (r['hasCitations'] and not r.get('sourceBlocks')) for r in history_results):
            raise ValueError('历史回答的结构或引用快照不完整，无法安全改写；请重新检索回答')
        if not evidence:
            raw=await llm(answer,'改写历史回答',{'question':question,'history':snapshot['history'],
                'sourceAnswers':[{'runId':r['runId'],'answer':r['answer']} for r in history_results]},
                '仅按用户要求改写 sourceAnswers，不增加新事实、不编造引用，输出正文。',structured=False)
            await verify_materials();save(answer=raw,state='done',phase='已完成',round=0,finished=time.time(),citationRefs=[],usedEvidence=[],citationValidation={'status':'not_applicable','problems':[]});return
        stop='仅改写历史正式回答，沿用原文引用绑定'
    if route=='research' and not pending:pending=[{'query':question,'purpose':'回答当前问题（结合对话历史）'}]
    if route=='evidence' and not pending:
        decision=await assess(0,0)
        if decision['enough'] and evidence:stop='历史引用原文足以回答，未启动新检索'
        else:pending=queries(decision['queries'],cfg['queriesPerRound'],seen)
    while not stop and round_no<cfg['maxRounds']:
        check();save(phase='检索问题正文',agentStep=round_no+1)
        if not pending:
            # Never silently skip the lower bound or repeat the old query to fake a round.
            repair=await planning('补充问答查询',{**material(),'round':round_no,'minRounds':cfg['minRounds'],'maxRounds':cfg['maxRounds'],
                'previousQueries':sorted(seen),'maxQueries':cfg['queriesPerRound'],'previousCoverage':decision.get('coverage',[])},
                assess_prompt+('\nThe last round supplied no executable new query. Propose new queries targeting unresolved aspects, counterevidence and boundaries.' if english else '\n上一轮没有提供可执行的新 query；本轮必须针对尚未解决的要点或反证与适用边界提出新查询。'))
            await read_history(repair.get('historyRequests',[]))
            pending=queries(repair['queries'],cfg['queriesPerRound'],seen)
            if not pending:raise ValueError('模型未提出新的补查 query，未虚增检索轮数；可继续检查点重试')
        round_no+=1;save(round=round_no)
        if retriever is None:
            if prepare_retrieval is not None:records,papers,coverage=await prepare_retrieval()
            await verify_materials()
            retriever=await asyncio.to_thread(retrieval.Retriever,e.ROOT,path,records,check,lambda msg:save(phase=msg),rcfg,e)
        for query in pending:
            await verify_materials();step=event('search',status='running',**query)
            found=await asyncio.to_thread(retriever.retrieve,query['query'],cfg['topK'],cfg['topK'])
            await verify_materials()
            hits=[]
            for row in found:
                eid=add(row);hits.append({'eid':eid,'chunkId':row['id'],'score':row.get('retrievalScore',0)})
            history.append({'round':round_no,**query,'hits':hits});seen.add(' '.join(query['query'].casefold().split()))
            finish_event(step,hits=hits,note='已检索相关段落及关联图表');checkpoint()
        event('round',totalChunks=len(evidence),papers=len({r['metadata']['pmid'] for r in evidence}))
        decision=await assess(round_no,cfg['minRounds'])
        allowed={r['eid'] for r in evidence};allowed.update(r['id'] for r in material()['materialBundle']['resources'])
        for row in decision['coverage']:
            row['evidenceIds']=[eid for eid in row.get('evidenceIds',[]) if eid in allowed]
            if row['status'] in ('supported','conflicting') and not row['evidenceIds']:
                row.update(status='missing',gap='未提供可定位的池内证据')
        # A supported verdict with no actual evidence cannot stop a nonempty research question early.
        enough=decision['enough'] and bool(evidence)
        save(evidenceCoverage=decision['coverage'],qualityWarnings=warnings)
        event('decision',enough=enough,coverage=decision['coverage'],reason=decision['reason'],queries=decision['queries']);checkpoint()
        stop=stop_reason(round_no,cfg,enough)
        if stop:break
        pending=queries(decision['queries'],cfg['queriesPerRound'],seen)
    save(stopReason=stop,phase='撰写问答')
    if not evidence:
        await verify_materials()
        save(answer='当前检索范围内未获得可用证据，无法据此给出研究结论；这不代表相关研究不存在。',state='done',finished=time.time(),citationValidation={'status':'no_evidence'});return
    bundle,unit=make_bundle(question,run_id,evidence,language)
    await verify_materials()
    e.write_json(path/'answer-bundle.json',bundle)
    payload={**material(),'coverage':decision['coverage'],'stopReason':stop}
    write_prompt=write_system+('\n本轮只改写 historyEvidence.sourceBlocks：保留其论断边界与引用关系，可删减、翻译、重排或整合为表格；不得从材料中增加新结论。旧编号已由程序换为本轮编号。' if route=='rewrite' else '')
    def decode_output(raw):
        rendered=decode_answer(raw,bundle,unit,answer,project)
        if route=='rewrite':
            original={value for old in payload['historyEvidence'] for value in old['referenceMap'].values() if value.startswith(('E','R'))}
            if any(r['id'] not in original for r in rendered['citationRefs']):raise ValueError('纯改写不得新增历史正式回答未引用的证据或图表引用')
        return rendered
    if english and route=='rewrite':write_prompt=write_system+'\nRewrite only historyEvidence.sourceBlocks. Preserve claim boundaries and citation bindings. You may shorten, translate, reorder or synthesize a table, but add no new conclusions. The app has remapped old citation IDs.'
    raw=await llm(answer,'撰写问答',payload,write_prompt,structured=False)
    # A returned model response confirms this material was sent, even if its
    # formatting later fails validation. Pure rewrites do not run assess().
    examined.update(r['id'] for r in evidence)
    checkpoint()
    try:rendered=decode_output(raw)
    except ValueError as exc:
        save(formatRepair={'reason':str(exc),'state':'running'})
        raw=await llm(answer,'修复问答格式',{**payload,'invalidOutput':raw,'formatError':str(exc)},write_prompt+('\nRepair only output structure, evidence IDs, object cross-references and incorrect material-scope claims. Preserve supported content and return complete JSON.' if english else '\n只修复输出结构、证据 ID、交叉引用格式及错误的材料范围表述，保留有依据的内容；返回完整 JSON。'),structured=False)
        try:rendered=decode_output(raw)
        except ValueError as failure:
            save(formatRepair={'reason':str(failure),'state':'failed'})
            raise ValueError('回答格式需要修复，请重试。已保留原文材料和处理记录。') from failure
        save(formatRepair={'reason':str(exc),'state':'done'})
    refs=rendered['citationRefs'];used={r['id'] for r in refs if r['id'].startswith('E')}
    used_resources={r['id'] for r in refs if r['id'].startswith('R')}
    for obj in bundle['resources']:
        if obj['id'] in used_resources:used.update(obj['linkedEvidenceIds'])
    checkpoint();await verify_materials()
    e.write_json(path/'answer-section.json',rendered)
    state={**coverage,'candidateChunks':len({h['chunkId'] for r in history for h in r['hits']}),'assessedChunks':0,
        'examinedChunks':len(evidence),'examinedPapers':len({r['metadata']['pmid'] for r in evidence}),
        'poolChunks':len(evidence),'poolPapers':len({r['metadata']['pmid'] for r in evidence}),
        'citedChunks':len(used),'paperRead':[]}
    save(answer=rendered['markdown'],draft='',answerBlocks=rendered['displayBlocks'],citationRefs=refs,
         readingCoverage=state,
         usedEvidence=sorted(used,key=lambda eid:int(eid[1:])),answerFinished=time.time(),finished=time.time(),state='done',phase='已完成',
         citationValidation={'status':'structural_checked','problems':[],'note':'已校验证据绑定、图表结构与交叉引用；未进行 LLM 事实后验证。'})

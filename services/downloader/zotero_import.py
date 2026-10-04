"""Read-only collection snapshots and scoped PDF import for Zotero sources."""
import asyncio,json,re,os,time,uuid
from pathlib import Path
import zotero_local as z
import corpus_files as files


def key(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Z0-9]{8}',value):raise ValueError('无效的 Zotero 条目键')
    return value


def valid_doi(value):
    value=z.normalize_doi(value)
    return value if re.fullmatch(r'10\.\d{4,9}/[^\s"\x00-\x1f]+',value) and len(value)<=256 else ''


async def collections(api):
    # Collections have no dateAdded sort field; use the API's default ordering.
    result=[];seen=set();expected=None
    for _ in range(z.MAX_PAGES):
        page,total=await api.page('users/0/collections',{'start':len(result),'limit':100})
        if expected is not None and expected!=total:raise ValueError('读取期间集合发生变化，请重试')
        expected=total
        for item in page:
            data=item['data'];k=key(item.get('key') or data.get('key'))
            if k in seen:raise ValueError('集合分页重复，请重试')
            seen.add(k);result.append({**data,'key':k})
        if len(result)==total:break
        if not page or len(result)>total:raise ValueError('集合分页不完整')
    else:raise ValueError('集合数量超过上限')
    bykey={c['key']:c for c in result}
    def path(c):
        names=[c['name']];parents={c['key']};p=c.get('parentCollection')
        while p:
            if p in parents or p not in bykey:raise ValueError('集合层级不完整，请重试')
            parents.add(p);c=bykey[p];names.insert(0,c['name']);p=c.get('parentCollection')
        return ' / '.join(names)
    return sorted([{**c,'path':path(c)} for c in result],key=lambda c:c['path'].casefold())


def selected_roots(all_collections,selected):
    # Accept old single-collection callers and normalize overlapping selections.
    values=[selected] if isinstance(selected,str) else selected
    if not isinstance(values,list) or not values or len(values)>z.MAX_ITEMS:
        raise ValueError('请选择至少一个文件夹')
    ids={key(v) for v in values};bykey={c['key']:c for c in all_collections}
    if not ids.issubset(bykey):raise ValueError('所选文件夹不存在，请重新连接')
    def covered(c):
        seen={c['key']};parent=c.get('parentCollection')
        while parent:
            if parent in seen or parent not in bykey:raise ValueError('集合层级不完整')
            if parent in ids:return True
            seen.add(parent);parent=bykey[parent].get('parentCollection')
        return False
    return [c for c in all_collections if c['key'] in ids and not covered(c)]


def descendants(all_collections,selected):
    ids={c['key'] for c in selected_roots(all_collections,selected)}
    while True:
        added={c['key'] for c in all_collections if c.get('parentCollection') in ids}-ids
        if not added:return [c for c in all_collections if c['key'] in ids]
        ids.update(added)


async def scan(api,selected):
    tree=await collections(api);roots=selected_roots(tree,selected);chosen=descendants(tree,[c["key"] for c in roots]);items={}
    for c in chosen:
        for item in await api.pages(f"users/0/collections/{c['key']}/items/top"):
            if not item.get('deleted') and item.get('itemType') not in ('attachment','note','annotation') and not item.get('parentItem'):
                if item['key'] in items and items[item['key']]!=item:raise ValueError('读取期间条目发生变化，请重试')
                items[item['key']]=item
    if len(items)>z.MAX_ITEMS:raise ValueError('导入条目超过 5000 条，请选择较小的集合')
    rows=[{'key':i['key'],'title':i.get('title',''),'doi':valid_doi(i.get('DOI')),'originalDoi':i.get('DOI',''),'version':i.get('version')} for i in items.values()]
    summary=roots[0] if len(roots)==1 else {'key':'','name':f'{len(roots)} 个文件夹','path':'、'.join(c['name'] for c in roots[:2])+(f' 等 {len(roots)} 个文件夹' if len(roots)>2 else '（2 个文件夹）')}
    return {'collection':summary,'selectedCollections':roots,'collections':chosen,'items':rows,'total':len(rows),'withDoi':sum(bool(i['doi']) for i in rows),'uniqueDois':len({i['doi'] for i in rows if i['doi']}),'version':api.version,'zoteroItems':list(items.values())}


def attachment_rule(data):
    # Same whitelist and supplementary exclusions, irrespective of linkMode.
    if data.get('deleted') or data.get('itemType')!='attachment':return None
    if str(data.get('contentType','')).lower()!='application/pdf':return None
    rule=z.ALIASES.get(z.normalize_title(data.get('title')))
    if not rule:return None
    if any(z.negative_name(data.get(k,'')) or z.negative_path(str(data.get(k,''))) for k in ('title','filename','url')):return None
    return rule


async def copy_pdf(e,a):
    p=e.pmid(a['pmid']);base=files.base(e);cancel=base/'metadata/zotero-imports'/e.ident(a['job'])/'cancel'
    def guard():
        if cancel.exists():raise ValueError('导入已取消')
        if p not in (files.current(e) or set()):raise ValueError('文献已移出当前集合')
    dest=files.folder(e,'pdf')/f'{p}.pdf'
    with files.lock(e):
        guard()
        if dest.is_symlink():raise ValueError('项目 PDF 不能是符号链接')
        if dest.exists():
            try:e.validate_pdf(dest);return {'state':'reused','message':'复用已有 PDF'}
            except Exception:return {'state':'conflict','message':'已有文件未通过 PDF 校验，保留原文件'}
    candidates=[];errors=[]
    async with z.LocalAPI(a['address']) as api:
        for parent in a['parents']:
            guard();parent=key(parent)
            body,_=await api.request(f'users/0/items/{parent}')
            item=json.loads(body)['data']
            if item.get('deleted') or valid_doi(item.get('DOI'))!=a['doi']:
                errors.append(f'{parent}: DOI 已变化');continue
            for data in await api.pages(f'users/0/items/{parent}/children'):
                rule=attachment_rule(data)
                if not rule or data.get('parentItem')!=parent:continue
                k=key(data['key'])
                try:
                    body,_=await api.request(f'users/0/items/{k}/file/view/url')
                    path=z.file_path(body.decode());signature=z.fingerprint(path)
                    if signature and 0<signature[2]<=z.MAX_PDF and not z.negative_path(path.as_uri()):
                        candidates.append({'key':k,'parent':parent,'data':data,'path':path,'stat':signature,'rule':rule})
                except (ValueError,OSError) as ex:errors.append(f'{k}: {ex}')
    for candidate in z.rank(candidates):
        tmp=files.folder(e,f"metadata/zotero-imports/{e.ident(a['job'])}/staging")/f'{p}.pdf'
        tmp.unlink(missing_ok=True)
        try:
            checked,_=z.copy_checked(candidate,tmp,e.validate_pdf)
            with files.lock(e):
                guard()
                if dest.exists():return {'state':'conflict','message':'项目中已出现 PDF，保留现有文件'}
                info={**checked,'pmid':p,'path':f'pdf/{p}.pdf','source':'Zotero','downloaded':time.time(),'zoteroParentKey':candidate['parent'],'zoteroAttachmentKey':candidate['key'],'zoteroTitle':candidate['data'].get('title'),'zoteroRuleVersion':z.RULES.get('version'),'importJob':a['job'],'identity':'Zotero 条目 DOI 与 PubMed 精确匹配','manuscriptKind':candidate['rule'].get('kind'),'priority':candidate['rule']['priority']}
                os.replace(tmp,dest)
                e.write_json(e.metadata_path(e.PROJECT,p),info)
                e.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?)',(e.PROJECT,p,json.dumps(info)))
                try:z.cache_fingerprint(e,dest,checked['sha256'])
                except Exception:pass
            return {'state':'imported','message':'已复制 PDF','attachmentKey':candidate['key'],'parentKey':candidate['parent']}
        except Exception as ex:errors.append(f"{candidate['key']}: {ex}")
        finally:tmp.unlink(missing_ok=True)
    return {'state':'missing','message':'；'.join(errors[:10]) or '没有符合名称规则的可读本地 PDF'}


def current_job(e):
    path=files.base(e)/'metadata/zotero-job.json'
    if not path.exists():return None
    j=json.loads(path.read_text())
    if j.get('state') in ('queued','running'):
        try:
            import storage
            with storage.file_lock(files.base(e)/'metadata/zotero-import.lock'):
                # A worker can finish between our initial read and lock acquisition.
                j=json.loads(path.read_text())
                if j.get('state') in ('queued','running') and time.time()-j.get('started',j.get('created',0))>30:
                    j.update(state='interrupted',stage='导入已中断',error='导入进程已退出，已保存的文献保留');e.write_json(path,j)
                    report=files.base(e)/'metadata/zotero-imports'/e.ident(j['id'])/'report.json'
                    e.write_json(report,j)
        except ValueError:pass
    return j


def rpc(e,op,a):
    if op=='finish':return files.update_missing_pdf_report(e)
    if op=='check':
        import library_service
        library_service.check_owner(e,{})
        if library_service.running(e):raise ValueError('请先结束当前项目任务，再导入 Zotero')
        return {}
    if op=='pdf':return asyncio.run(copy_pdf(e,a))
    address=e.config().get('zoteroAddress') or 'localhost:23119'
    async def read():
        async with z.LocalAPI(address) as api:
            if op=='collections':return {'collections':await collections(api),'address':address}
            if op=='preview':
                result=await scan(api,a.get('collections',a.get('collection')))
                result.update(id=uuid.uuid4().hex,address=address,created=time.time())
                e.write_json(files.folder(e,'metadata/zotero-previews')/(result['id']+'.json'),result)
                return {k:v for k,v in result.items() if k not in ('items','zoteroItems')}
            raise ValueError('未知 Zotero 操作')
    try:return asyncio.run(read())
    except Exception as ex:raise ValueError(f'Zotero 读取失败：{ex}。请打开 Zotero，并启用本地 API。') from ex

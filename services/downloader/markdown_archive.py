"""Hash-verified Markdown bundles for corpus removal/reinclusion; no vector backup."""
import hashlib,json,os,shutil,time,uuid
import corpus_files as files


def sha(data):return hashlib.sha256(data).hexdigest()
def safe(root,relative):
    path=root/relative
    if not path.resolve().is_relative_to(root.resolve()):raise ValueError('Markdown 备份路径无效')
    for p in (path,*path.parents):
        if p==root:break
        if p.is_symlink():raise ValueError('Markdown 备份不能包含符号链接')
    return path

def clear_time(root,p):
    marker=safe(root,'metadata/markdown-cleared.json')
    return json.loads(marker.read_text()).get('before',{}).get(p,0) if marker.exists() else 0

def locations(p):
    return [f'markdown/{p}.md',f'markdown/raw/{p}.md',f'metadata/markdown/{p}.json',f'markdown/assets/{p}',f'markdown/history/{p}']

def archive(e,p,previous_epoch):
    """Finish a durable copy before the caller removes any active derivatives."""
    root=files.base(e);meta=safe(root,f'metadata/markdown/{p}.json')
    try:info=json.loads(meta.read_text())
    except (OSError,ValueError):info={}
    if not isinstance(info,dict):info={}
    pdf=safe(root,f'pdf/{p}.pdf')
    if not pdf.is_file():pdf=safe(root,f'pdf/redundant/{p}.pdf')
    pdf_sha=sha(pdf.read_bytes()) if pdf.is_file() else ''
    # An interrupted/obsolete conversion must never become valid through restore.
    valid=bool(pdf_sha) and info.get('pdfSha256')==pdf_sha and info.get('rebuildEpoch',0)==previous_epoch
    entries={}
    for name in locations(p):
        source=safe(root,name)
        candidates=source.rglob('*') if source.is_dir() else [source]
        for candidate in candidates:
            relative=candidate.relative_to(root).as_posix();safe(root,relative)
            if candidate.is_file():entries[relative]=sha(candidate.read_bytes())
    if not entries:return False
    identity={k:v for k,v in entries.items() if k!=f'metadata/markdown/{p}.json'}
    identity['conversion']={k:v for k,v in info.items() if k!='rebuildEpoch'}
    version=sha(json.dumps([pdf_sha,valid,identity],sort_keys=True).encode())
    parent=files.folder(e,f'archive/markdown/{p}');target=safe(parent,version)
    if target.exists():
        try:
            old=json.loads((target/'manifest.json').read_text())
            cutoff=clear_time(root,p)
            if isinstance(old,dict) and old.get('created',0)>cutoff and old.get('restorable')==valid and isinstance(old.get('files'),dict) and old['files'].keys()==entries.keys() and all(sha(safe(target,k).read_bytes())==v for k,v in old['files'].items()) and {k:v for k,v in old['files'].items() if k!=f'metadata/markdown/{p}.json'}=={k:v for k,v in entries.items() if k!=f'metadata/markdown/{p}.json'}:return True
        except (OSError,ValueError,KeyError,TypeError):pass
        target=safe(parent,version+'-'+uuid.uuid4().hex)
    stage=safe(parent,'.pending-'+uuid.uuid4().hex);stage.mkdir()
    try:
        for relative,digest in entries.items():
            source=safe(root,relative);dest=safe(stage,relative);dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,dest)
            if sha(dest.read_bytes())!=digest:raise ValueError('Markdown 备份期间文件发生变化，原文件保留')
        e.write_json(stage/'manifest.json',{'version':1,'pmid':p,'created':time.time(),'pdfSha256':pdf_sha,'restorable':valid,'files':entries})
        os.replace(stage,target)
    finally:
        if stage.exists():shutil.rmtree(stage)
    return True

def restore(e,p):
    """Restore compatible bytes only; publish the new epoch after all files exist."""
    import artifact_state,conversion_config,markdown_service
    root=files.base(e);pdf=safe(root,f'pdf/{p}.pdf');meta=safe(root,f'metadata/markdown/{p}.json')
    if not pdf.is_file() or meta.is_file():return False
    parent=safe(root,f'archive/markdown/{p}')
    if not parent.is_dir():return False
    try:pdf_sha=e.validate_pdf(pdf)['sha256']
    except ValueError:return False
    cutoff=clear_time(root,p)
    candidates=[]
    for path in parent.glob('*/manifest.json'):
        safe(root,str(path.relative_to(root)))
        try:
            manifest=json.loads(path.read_text())
            if isinstance(manifest,dict) and isinstance(manifest.get('created'),(int,float)) and manifest['created']>cutoff and manifest.get('version')==1 and manifest.get('pmid')==p and manifest.get('restorable') and manifest.get('pdfSha256')==pdf_sha:candidates.append((manifest.get('created',0),path.parent,manifest))
        except (OSError,ValueError,TypeError):continue
    for _,folder,manifest in sorted(candidates,key=lambda item:item[0],reverse=True):
        entries=manifest.get('files',{});allowed=locations(p);meta_name=f'metadata/markdown/{p}.json'
        if not isinstance(entries,dict) or not {meta_name,f'markdown/{p}.md',f'markdown/raw/{p}.md'}<=entries.keys():continue
        if any(name not in allowed and not any(name.startswith(prefix+'/') for prefix in allowed[-2:]) for name in entries):continue
        try:
            # Validate the entire bundle before restoring even one file.
            for name,digest in entries.items():
                source=safe(folder,name);dest=safe(root,name)
                if not source.is_file() or sha(source.read_bytes())!=digest:raise ValueError('Markdown 备份校验失败')
                if dest.exists() and (not dest.is_file() or sha(dest.read_bytes())!=digest):raise ValueError('当前文件与备份不同，保留当前文件')
            info=json.loads(safe(folder,meta_name).read_text())
            if not isinstance(info,dict):continue
            if info.get('pdfSha256')!=pdf_sha or info.get('rawSha256')!=entries[f'markdown/raw/{p}.md']:continue
            cfg=markdown_service.config(e)
            if not conversion_config.matches(e.ROOT,info,cfg) or info.get('cleaningSignature')!=markdown_service.signature(cfg):continue
            for name in entries:
                if name!=meta_name:e.atomic(safe(root,name),safe(folder,name).read_bytes())
            info['rebuildEpoch']=artifact_state.epoch(e,p)
            e.write_json(meta,info)
            return True
        except (OSError,ValueError,TypeError):continue
    return False

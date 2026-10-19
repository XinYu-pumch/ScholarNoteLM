"""Disposable UI summaries. Generation/retrieval must use authoritative readers.

Every hit validates dependency file identities, including SQLite WAL and image
assets. No TTL can make changed material appear current. Payloads contain neither
credentials nor vectors; a racing write is never published as a valid snapshot.
"""
from file_identity import change_ns
import hashlib,json,os
from pathlib import Path
import storage

VERSION=1

def identity(path):
    try:
        s=path.stat()
        if path.is_dir():return [str(path),'directory']
        if str(path).endswith('-wal') and not s.st_size:return [str(path),None]
        return [str(path),s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,change_ns(path,s)]
    except FileNotFoundError:return [str(path),None]

def dependencies(e):
    root=storage.project_dir(e.ROOT,e.PROJECT)
    paths=[root/'pubmed/current.xml']
    for folder in ('pdf','markdown','abstracts'):
        base=root/folder
        paths.append(base)
        if base.exists():
            for parent,dirs,names in os.walk(base,followlinks=False):
                dirs[:]=sorted(d for d in dirs if d!='redundant')
                paths.extend(Path(parent)/n for n in sorted(names))
    for name in ('corpus-membership.json','conversion-settings.json','index-generation.json','index-cleared.json','pdf-cleared.json'):
        paths.append(root/'metadata'/name)
    for base in (root/'metadata/markdown',e.ROOT/'config'):
        paths.append(base)
        if base.exists():paths.extend(sorted(base.rglob('*.json')))
    for db in (root/'vectors/chunks.sqlite3',e.ROOT/'data/research/research.sqlite3'):
        paths.extend([db,Path(str(db)+'-wal')])
    # Code changes, including recall/splitter policy, invalidate installed caches.
    paths.extend(sorted(Path(__file__).parent.glob('*.py')))
    encoded=json.dumps([VERSION,str(root.resolve()),[identity(p) for p in paths]],ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()

def cached(e,name,compute,force=False,on_unstable=None):
    project=hashlib.sha256(str(storage.project_dir(e.ROOT,e.PROJECT).resolve()).encode()).hexdigest()
    path=e.ROOT/'cache/status-snapshots'/project/(hashlib.sha256(name.encode()).hexdigest()+'.json')
    before=dependencies(e)
    if not force:
        try:
            value=json.loads(path.read_text(encoding='utf8'))
            if value['signature']==before and dependencies(e)==before:return value['data']
        except (OSError,ValueError,KeyError,TypeError):pass
    for attempt in range(2):
        data=compute();after=dependencies(e)
        if before==after:
            try:storage.atomic(path,{'signature':after,'data':data})
            except OSError:pass  # A read-only cache directory must not break the page.
            return data
        before=after
    # A UI-only best-effort snapshot; do not cache a racing computation.
    # Evidence retrieval/publishing always use authoritative readers.
    if on_unstable:return on_unstable(data)
    raise ValueError('文献或索引正在更新，请稍后刷新状态')

def documents(e,profile):
    import vector_chunks
    return cached(e,'documents:'+profile,lambda:vector_chunks.inspect_documents(e,profile),on_unstable=lambda docs:[{**d,'refreshing':True} for d in docs])

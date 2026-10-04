"""System resources stay in the installation; project data lives in a chosen workspace."""
from pathlib import Path
from contextlib import contextmanager
import json, os, re, shutil, sqlite3, subprocess, sys, uuid

FOLDERS = {'pubmed':'PubMed XML、检索批次和合并快照', 'pdf':'当前集合 PDF，以 PMID 命名；redundant/ 保存移出集合的 PDF',
 'abstracts':'PubMed 摘要 Markdown，以 PMID 命名', 'markdown':'清洗后全文 Markdown；raw/ 原稿，assets/ 图片',
 'logs':'下载报告和逐篇日志', 'vectors':'文本块、向量缓存、源文本快照与索引状态',
 'notes':'阅读笔记', 'review':'综述工作区、大纲、正文、检索证据与导出', 'packages':'当前 XML 对应的文献包',
 'qa':'文献问答、原文证据快照、任务和导出', 'metadata':'项目数据库和下载来源记录'}

def atomic(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('w',encoding='utf8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def config(root):
    f=root/'config/storage.json'
    return json.loads(f.read_text()) if f.exists() else {'version':1,'workspace':str(root/'workspace'),'projects':{}}

FOLDER_PATTERN = r'[A-Za-z0-9_㐀-䶿一-鿿]{1,64}'

def folder_name(value):
    if not isinstance(value,str) or not re.fullmatch(FOLDER_PATTERN,value):raise ValueError('文件夹名只能包含中文、英文字母、数字和下划线，长度 1–64')
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])',value):raise ValueError('此文件夹名是 Windows 保留名称，请换一个')
    return value

def default_name(project):return folder_name(re.sub('[^A-Za-z0-9]','',project)[:64] or 'Project')
def project_dir(root, project):
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',project):raise ValueError('项目标识无效')
    cfg=config(root)
    if project in cfg.get('deletedProjects',{}):raise ValueError('项目已删除，请刷新项目列表')
    base=Path(cfg['workspace']);folder=folder_name(cfg['projects'].get(project,default_name(project)));dest=base/folder
    if base.is_symlink() or dest.is_symlink():raise ValueError('工作目录和项目目录不能是符号链接')
    if dest.resolve().parent!=base.resolve():raise ValueError('项目路径超出工作目录')
    return dest

def layout(path):
    path.mkdir(parents=True,exist_ok=True)
    for name in FOLDERS:
        if (path/name).is_symlink():raise ValueError('项目子目录不能是符号链接')
        (path/name).mkdir(exist_ok=True)
    if not (path/'README.md').exists():(path/'README.md').write_text('# ScholarNoteLM 项目文件\n\n'+''.join(f'- `{k}/`：{v}\n' for k,v in FOLDERS.items())+'\n`pubmed/current.xml` 是当前合并文献集合；历史文件保留在 queries 和 snapshots 中。\n`metadata/` 是应用继续编辑项目所需的数据，请与项目一起保留。\n',encoding='utf8')

@contextmanager
def file_lock(path, shared=False):
    path.parent.mkdir(parents=True,exist_ok=True)
    f=path.open('a+b')
    try:
        if os.name=='nt':
            import msvcrt
            f.seek(0);f.write(b'0');f.flush();f.seek(0)
            msvcrt.locking(f.fileno(),msvcrt.LK_NBRLCK if shared else msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),(fcntl.LOCK_SH if shared else fcntl.LOCK_EX)|fcntl.LOCK_NB)
    except OSError:
        f.close();raise ValueError('项目正在使用，请等待检索、聊天或下载结束后再操作')
    try:yield
    finally:f.close()

def initialize(root):
    cfg=config(root)
    if cfg.get('migrated'):return cfg
    # The pre-workspace layout (data/projects) has been migrated everywhere; refuse rather than ignore it.
    if (root/'data/projects').exists():raise ValueError('检测到旧版项目目录 data/projects，当前版本不再支持自动迁移')
    Path(cfg['workspace']).mkdir(parents=True,exist_ok=True)
    cfg['migrated']=True;cfg['cleanupPending']=False;atomic(root/'config/storage.json',cfg)
    return cfg

def read_state(root):
    f=root/'data/prototype/state.json'
    if not f.exists():return None
    state=json.loads(f.read_text())
    deleted=config(root).get('deletedProjects',{})
    state['projects']=[json.loads((project_dir(root,p['id'])/'project.json').read_text()) for p in state['projects'] if p['id'] not in deleted]
    if state.get('active') not in {p['id'] for p in state['projects']}:
        state['active']=state['projects'][0]['id'] if state['projects'] else ''
    return state

def write_state(root,state):
    if state.get('version')!=1 or not isinstance(state.get('projects'),list):raise ValueError('项目状态格式无效')
    cfg=config(root)
    ids=[p['id'] for p in state['projects']]
    if len(set(ids))!=len(ids) or (state.get('active') not in ids if ids else state.get('active')!=''):raise ValueError('当前项目无效')
    if any(pid not in cfg['projects'] or pid in cfg.get('deletedProjects',{}) for pid in ids):raise ValueError('项目列表已变更，请刷新后重试')
    for p in state['projects']:
        if p['id'] not in cfg['projects']:raise ValueError('请先创建项目文件夹')
        dest=project_dir(root,p['id']);layout(dest);atomic(dest/'project.json',p)
        atomic(dest/'notes'/'notes.json',p.get('notes',{}))
    atomic(root/'data/prototype/state.json',{**state,'projects':[{'id':p['id']} for p in state['projects']]})
    return {'ok':True}

def status(root,project=''):
    cfg=config(root)
    return {'workspace':cfg['workspace'],'system':str(root/'data/reference'),'projectPath':str(project_dir(root,project)) if project else '', 'folder':cfg['projects'].get(project,default_name(project)) if project else '', 'folders':FOLDERS}

def register(root,a):
    cfg=config(root);pid=a['project'];name=folder_name(a['folder'])
    project_dir(root,pid)  # Validate identifiers and reject deleted project IDs.
    if pid in cfg['projects']:
        if cfg['projects'][pid]==name:return status(root,pid)
        raise ValueError('项目已存在')
    if name.lower() in {v.lower() for v in cfg['projects'].values()}:raise ValueError('项目文件夹名称已使用（不区分大小写）')
    dest=Path(cfg['workspace'])/name
    if dest.exists():raise ValueError('目标文件夹已存在，请换一个名称')
    cfg['projects'][pid]=name;layout(dest);atomic(dest/'project.json',a['data']);atomic(root/'config/storage.json',cfg)
    return status(root,pid)

def delete_project(root,a):
    """Caller holds the exclusive storage lock and catalog lock.

    The catalog tombstone is the commit point: old state files and late requests
    cannot resurrect the project, even if the application exits immediately.
    """
    pid=a['project'];cfg=config(root)
    if a.get('confirm')!=pid:raise ValueError('请确认要删除的项目')
    if pid not in cfg['projects']:raise ValueError('项目不存在或已删除')
    source=project_dir(root,pid)
    state=read_state(root)
    if state is None:raise ValueError('项目列表尚未保存，请稍后重试')
    # Stage only until the catalog commit succeeds; this is not a recovery backup.
    original=json.loads(json.dumps(cfg))
    target=source.with_name('.deleting-'+uuid.uuid4().hex)
    os.rename(source,target)
    try:
        del cfg['projects'][pid]
        cfg.setdefault('deletedProjects',{})[pid]={'name':next((p.get('name','') for p in state['projects'] if p['id']==pid),'')}
        atomic(root/'config/storage.json',cfg)
    except Exception:
        os.rename(target,source)
        raise
    # read_state filters the committed tombstone, so no second catalog/state
    # transaction is required. The normal UI save compacts the state file later.
    try:
        shutil.rmtree(target)
    except OSError as exc:
        # Make remaining files available for a retry, never report success while
        # silently retaining a backup. Some files may already have been removed.
        os.rename(target,source)
        if not (source/'project.json').exists():atomic(source/'project.json',next(p for p in state['projects'] if p['id']==pid))
        atomic(root/'config/storage.json',original)
        raise ValueError('项目删除未完成，部分文件可能已删除；请关闭占用文件的程序后重试') from exc
    return {'state':read_state(root),'deleted':True}

def move_workspace(root,value):
    cfg=config(root);old=Path(cfg['workspace']).resolve();target=Path(value).expanduser()
    if not target.is_absolute():raise ValueError('工作目录必须是绝对路径')
    if target.is_symlink():raise ValueError('请选择真实文件夹，不支持符号链接')
    target=target.resolve()
    if target==old:return status(root)
    if target.is_relative_to(old) or old.is_relative_to(target):raise ValueError('新旧工作目录不能互相包含')
    for reserved in ['data','config','cache','runtimes','services','apps','backups','dist','node_modules']:
        system=(root/reserved).resolve()
        if target==root or target.is_relative_to(system) or system.is_relative_to(target):raise ValueError('工作目录不能覆盖应用系统目录')
    for pid in cfg['projects']:
        db=project_dir(root,pid)/'metadata/downloads.sqlite3'
        if db.exists():
            with sqlite3.connect(db) as c:
                if c.execute("SELECT 1 FROM batches WHERE state IN ('running','queued')").fetchone():raise ValueError('请先暂停下载，再更换工作目录')
    target.mkdir(parents=True,exist_ok=True)
    for name in cfg['projects'].values():
        if (target/name).exists():raise ValueError(f'新目录中已有 {name}，不会覆盖')
    copied=[]
    try:
        for name in cfg['projects'].values():
            src=old/name;dst=target/name
            if any(p.is_symlink() for p in src.rglob('*')):raise ValueError('项目包含符号链接，请先移除链接')
            copied.append(dst);shutil.copytree(src,dst)
            # Compare every copied file before activating the new location.
            import hashlib
            for f in src.rglob('*'):
                if f.is_file():
                    other=dst/f.relative_to(src)
                    with f.open('rb') as source,other.open('rb') as copied_file:
                        if f.stat().st_size!=other.stat().st_size or hashlib.file_digest(source,'sha256').digest()!=hashlib.file_digest(copied_file,'sha256').digest():raise ValueError('迁移文件校验失败')
        cfg['workspace']=str(target);atomic(root/'config/storage.json',cfg)
    except Exception:
        for p in copied:shutil.rmtree(p)
        raise
    for name in cfg['projects'].values():shutil.rmtree(old/name)
    return status(root)

def choose_folder():
    if sys.platform=='darwin':
        r=subprocess.run(['osascript','-e','POSIX path of (choose folder with prompt "选择 ScholarNoteLM 项目工作目录")'],capture_output=True,text=True)
        if r.returncode:return {'path':''}
        return {'path':r.stdout.strip().rstrip('/') or '/'}
    if os.name=='nt':
        script='Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description="ScholarNoteLM workspace"; if($d.ShowDialog() -eq "OK"){[Console]::Write($d.SelectedPath)}'
        r=subprocess.run(['powershell','-NoProfile','-STA','-Command',script],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        return {'path':r.stdout.strip()}
    raise ValueError('请在输入框中填写文件夹的绝对路径')

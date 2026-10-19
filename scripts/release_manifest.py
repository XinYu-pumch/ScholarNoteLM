"""Release/source pairing; never reads configuration or research data."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def source_files(root):
    names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root).decode().split('\0')
    result=[]
    for name in sorted(set(names)):
        if not name or not (root/name).is_file():continue
        if name.startswith(('config/','data/','workspace/','runtimes/','models/','cache/','tmp/','logs/','dist/','ScholarNoteLM.app/','third-party/')) or name in ('ScholarNoteLM.exe','ScholarNoteLM-Setup.exe','source-manifest.json'):
            raise ValueError('Private/generated path tracked by Git; refusing source export: '+name)
        if (root/name).is_symlink():raise ValueError('Refusing linked source file: '+name)
        result.append(name)
    return result


def generate(root, platform=None):
    files={name:sha(root/name) for name in source_files(root)
           if name.startswith(('apps/desktop/','services/','scripts/install/')) or name in ('package.json','package-lock.json','LICENSE','THIRD_PARTY_NOTICES.md')}
    return {'version':json.loads((root/'package.json').read_text(encoding='utf-8'))['version'],'platform':platform or ('windows-x64' if sys.platform=='win32' else 'macos-arm64'),'files':files}


def export_source(root,out):
    import zipfile
    version=json.loads((root/'package.json').read_text())['version']
    out.mkdir(parents=True,exist_ok=True)
    archive=out/f'ScholarNoteLM-{version}-source.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name in source_files(root):z.write(root/name,'ScholarNoteLM/'+name)
    archive.with_suffix('.zip.sha256').write_text(sha(archive)+'  '+archive.name+'\n')
    return archive


def validate(root, value):
    for name,expected in value['files'].items():
        p=Path(name)
        if p.is_absolute() or '..' in p.parts:raise ValueError('Invalid source manifest path')
        if not (root/p).is_file() or sha(root/p)!=expected:
            raise ValueError(f'程序和源码不匹配: {name}。请使用同一 Release 的源码与 app。')


def check_app(root, platform=None):
    windows=(platform or sys.platform)=='win32'
    app=root/('ScholarNoteLM.exe' if windows else 'ScholarNoteLM.app')
    if not app.exists():
        print(f'请将对应 Release 的 {app.name} 放入本目录；环境已保留。',flush=True)
        return
    manifest=root/'source-manifest.json' if windows else app/'Contents/Resources/source-manifest.json'
    if not manifest.is_file():raise ValueError('此 app 缺少源码版本清单，请使用新的源码安装版。')
    validate(root,json.loads(manifest.read_text(encoding='utf-8')))
    print('App and source match.',flush=True)


def register_installation(root):
    directory=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'ScholarNoteLM' if sys.platform=='win32' else Path.home()/'Library/Application Support/ScholarNoteLM'
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/'installations.json'
    values=json.loads(target.read_text(encoding='utf-8')) if target.exists() else []
    values=[str(root)]+[v for v in values if v!=str(root)]
    temp=target.with_suffix('.tmp');temp.write_text(json.dumps(values,ensure_ascii=False),encoding='utf-8');os.replace(temp,target)

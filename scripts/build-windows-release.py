"""Build a paired Windows x64 EXE, bootstrap UI and source ZIP on Windows."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import zipfile
from release_manifest import generate, sha, export_source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage-only',action='store_true',help='Build in dist/release without replacing the installed executables')
    args=parser.parse_args()
    if os.name != 'nt' or platform.machine().lower() not in ('amd64','x86_64'):
        raise SystemExit('Build on Windows x64 with MSVC C++ Build Tools and Windows SDK.')
    root = Path(__file__).resolve().parents[1]
    out = root/'dist/release'; out.mkdir(parents=True,exist_ok=True)
    manifest = generate(root,platform='windows-x64')
    manifest_file = out/'source-manifest.json'
    manifest_file.write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    subprocess.run([str(root/'scripts/npm-local.cmd'),'run','desktop:build','--','--no-bundle'],cwd=root,check=True)
    binary = root/'cache/tauri-target/release/scholarnotelm.exe'
    shutil.copy2(binary,out/'ScholarNoteLM.exe')
    compiler = Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler),'/nologo','/target:winexe','/platform:x64','/utf8output',
                    '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',
                    '/win32icon:'+str(root/'apps/desktop/src-tauri/icons/icon.ico'),
                    '/out:'+str(out/'ScholarNoteLM-Setup.exe'),str(root/'scripts/windows-setup.cs')],check=True)
    if not args.stage_only:
        for name in ('ScholarNoteLM.exe','ScholarNoteLM-Setup.exe','source-manifest.json'):
            shutil.copy2(out/name,root/name)
    # Retain third-party notices; do not package environment files or user data.
    notices = []
    for tree,label in ((root/'node_modules','npm'),(root/'cache/cargo/registry/src','rust')):
        for file in tree.rglob('*'):
            if file.is_file() and file.name.upper().startswith(('LICENSE','COPYING','NOTICE')) and file.stat().st_size < 2_000_000:
                notices.append((file,'third-party/'+label+'/'+file.relative_to(tree).as_posix()))
    archive = out/f'ScholarNoteLM-{manifest["version"]}-windows-x64.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,strict_timestamps=False) as z:
        for name in ('ScholarNoteLM.exe','ScholarNoteLM-Setup.exe','source-manifest.json','LICENSE','THIRD_PARTY_NOTICES.md'):
            z.write((out if name in ('ScholarNoteLM.exe','ScholarNoteLM-Setup.exe','source-manifest.json') else root)/name,name)
        for file,name in notices:
            z.write(file,name)
    archive.with_suffix('.zip.sha256').write_text(sha(archive)+'  '+archive.name+'\n',encoding='utf-8')
    print('Built unsigned Windows binaries:',archive)
    print('Matching source:',export_source(root,out))


if __name__ == '__main__':
    main()

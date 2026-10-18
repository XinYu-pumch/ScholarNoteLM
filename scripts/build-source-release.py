"""Build the source-install edition; only maintainers need Xcode/Rust/Node."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from release_manifest import generate,sha,export_source
import platform

if sys.platform!='darwin' or platform.machine()!='arm64':raise SystemExit('Build this release on an Apple Silicon Mac.')
root=Path(__file__).resolve().parents[1]
out=root/'dist/release';out.mkdir(parents=True,exist_ok=True)
manifest=generate(root)
(out/'source-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')))
env={**os.environ,'MACOSX_DEPLOYMENT_TARGET':'14.0'}
subprocess.run([str(root/'scripts/npm-local.sh'),'run','desktop:build','--','--bundles','app'],cwd=root,env=env,check=True)
source=root/'cache/tauri-target/release/bundle/macos/ScholarNoteLM.app'
target=root/'ScholarNoteLM.app'
if target.exists():
    # Only replace a previous generated bundle, never an arbitrary directory.
    if not (target/'Contents/Info.plist').is_file():raise RuntimeError('Unexpected app target')
    shutil.rmtree(target)
shutil.copytree(source,target,symlinks=True)
resources=target/'Contents/Resources'
shutil.copy2(out/'source-manifest.json',resources/'source-manifest.json')
for name in ['LICENSE','THIRD_PARTY_NOTICES.md']:
    shutil.copy2(root/name,resources/name)
# Retain the notices shipped with dependencies used during the build.
for tree,label in [(root/'node_modules','npm'),(root/'cache/cargo/registry/src','rust')]:
    for source_notice in tree.rglob('*'):
        if source_notice.is_file() and source_notice.name.upper().startswith(('LICENSE','COPYING','NOTICE')) and source_notice.stat().st_size<2_000_000:
            dest=resources/'third-party'/label/source_notice.relative_to(tree)
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source_notice,dest)

subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-',str(target)],check=True)
subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(target)],check=True)
version=manifest['version'];archive=out/f'ScholarNoteLM-{version}-macos-arm64.zip'
archive.unlink(missing_ok=True)
subprocess.run(['/usr/bin/ditto','-c','-k','--sequesterRsrc','--keepParent',str(target),str(archive)],check=True)
archive.with_suffix('.zip.sha256').write_text(sha(archive)+'  '+archive.name+'\n')
print('Built',target,'and',archive,'(ad-hoc signed; not notarized).')

print("Matching source ZIP:",export_source(root,out))

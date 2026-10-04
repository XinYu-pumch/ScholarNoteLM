"""Import the user's known BADR runtime/models into an independent local runtime."""
import argparse,json,shutil,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
a=argparse.ArgumentParser();a.add_argument('badr',type=Path);args=a.parse_args();src=args.badr.resolve()
base=next((root/'runtimes/python').glob('*/bin/python3.12'))
dest=root/'runtimes/marker'
if not (dest/'bin/python').exists():subprocess.run([str(base),'-m','venv','--without-pip',str(dest)],check=True)
shutil.copytree(src/'venv/lib/python3.12/site-packages',dest/'lib/python3.12/site-packages',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pth','*.egg-link'))
for package in (root/'runtimes/downloader/lib/python3.12/site-packages').glob('pypdf*'):
 shutil.copytree(package,dest/'lib/python3.12/site-packages'/package.name,dirs_exist_ok=True)
shutil.copytree(src/'marker_modified/marker',root/'services/marker/vendor/marker',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','models.py'))
shutil.copytree(src/'marker_modified/static',root/'services/marker/vendor/static',dirs_exist_ok=True)
subprocess.run([str(dest/'bin/python'),'-m','pip','--isolated','--cache-dir',str(root/'cache/pip'),'install','--no-index','--find-links',str(root/'installers/marker'),'--no-deps','transformers==4.49.0','tokenizers==0.21.0'],check=True)
for name in ['LICENSE','pyproject.toml']:
 if (src/'marker_modified'/name).exists():shutil.copy2(src/'marker_modified'/name,root/'services/marker/vendor'/name)
shutil.copytree(src/'marker_config',root/'models/marker',dirs_exist_ok=True)
(root/'models/marker/import-manifest.json').write_text(json.dumps({'source':str(src/'marker_config'),'marker':'1.6.0 (BADR)','files':[{ 'path':str(p.relative_to(root/'models/marker')),'bytes':p.stat().st_size} for p in (root/'models/marker').rglob('*') if p.is_file()]},ensure_ascii=False,indent=2))
print('Marker runtime, source and models copied inside ScholarNoteLM.',flush=True)

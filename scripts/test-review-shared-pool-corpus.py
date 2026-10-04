"""Repackage the user's frozen retrieval results without touching the project or calling APIs."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/downloader'))
import review_bundle as bundle,engine as e
project=ROOT/'workspace/HUSandgene';review=project/'review/review2';out=ROOT/'experiments/review2-shared-pool';out.mkdir(parents=True,exist_ok=True)
files=[*(review/'prompts').glob('*.json'),*(review/'review_parts').glob('*.*')]
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
config=json.loads((review/'writing-settings.json').read_text());snapshot={'topic':'HUS中的基因遗传','config':config};counts={'units':0,'retrievedChunks':0,'pooledChunks':0,'resources':0,'images':0};rows=[]
for f in sorted((review/'prompts').glob('*.json')):
 data=json.loads(f.read_text());assert len(data['plans'])==1
 plan=data['plans'][0];unit=plan['unit'];evidence=data['evidence']
 assert hashlib.sha256((review/'review_parts'/plan['file']).read_bytes()).hexdigest()==plan['sha256']
 original=bundle.make(snapshot,unit,evidence);bundle.validate(original)
 package=bundle.externalize(original,out,project,e.atomic);e.atomic(out/f'prompt_section_{unit["serial"]}.json',bundle.dumps(package)+'\n')
 loaded=bundle.hydrate(package,out)
 assert loaded['evidencePool']==original['evidencePool']
 assert all(a['content']==b['content'] for a,b in zip(original['resources'],loaded['resources']))
 plain=bundle.messages(package,out,{})
 e.atomic(out/f'prompt_section_{unit["serial"]}.txt','[阅读预览 · 正式输入为同名 JSON]\n\n[SYSTEM]\n'+plain[0]['content']+'\n\n[USER]\n'+plain[1]['content'])
 visual=bundle.messages(package,out,{'model':'fixture','visionModels':['fixture']})[-1]['content']
 images=sum(p['type']=='image_url' for p in visual) if isinstance(visual,list) else 0
 assert images==sum(bool(r.get('imageFile')) for r in package['resources'])
 hits=sum(len(r['hits']) for r in package['retrieval']);unique=len(package['evidencePool'])
 counts['units']+=1;counts['retrievedChunks']+=hits;counts['pooledChunks']+=unique;counts['resources']+=len(package['resources']);counts['images']+=images
 rows.append({'unit':unit['serial'],'leafCount':len(package['retrieval']),'retrievedChunks':hits,'pooledChunks':unique,'resources':len(package['resources']),'images':images,'requestTextChars':len(plain[1]['content'])})
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==v for p,v in before.items())
report={'counts':counts,'sourceFilesUnchanged':len(before),'allOriginalChunksAndResourcesPreserved':True,'allReferencesResolved':True,'apiCalls':0,'rows':rows}
e.atomic(out/'verification.json',bundle.dumps(report)+'\n');print(bundle.dumps({k:v for k,v in report.items() if k!='rows'}))

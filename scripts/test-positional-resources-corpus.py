"""Read-only 107-document validation, no embedding API and no project writes."""
from pathlib import Path
import hashlib,json,sys,time
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/downloader'))
import markdown_service as m,vector_chunks as c,evidence_resources as resources
OUT=ROOT/'experiments/positional-resources';OUT.mkdir(exist_ok=True)
rows=[];counts=Counter();started=time.monotonic()
for project in ('HUSandgene','HLH'):
 base=ROOT/'workspace'/project
 for source in sorted((base/'markdown/raw').glob('*.md')):
  before=source.read_bytes();published=source.parent.parent/source.name;before_published=published.read_bytes();raw=before.decode()
  clean,removed=m.clean(raw,{**m.DEFAULTS,'cleaningMode':'references-v1'})
  # Indexing sees published image links, as in the real worker.
  clean=clean.replace('](../assets/','](assets/').replace('src="../assets/','src="assets/').replace("src='../assets/","src='assets/")
  segments=c.split(clean);version=c.digest([source.stem,clean,c.SPLITTER]);objects=resources.extract(base,source.stem,version,clean,segments,lambda path,data:None)
  assert all(s['accepted'] for s in segments)
  assert sum(not ch.isspace() for ch in clean)==sum(sum(not ch.isspace() for ch in s['text']) for s in segments)
  for s in segments:assert clean[s['charStart']:s['charEnd']]==s['text']
  for obj in objects:
   assert clean[obj['charStart']:obj['charEnd']]==obj['content']
   overlap=[s['chunkIndex'] for s in segments if s['charStart']<obj['charEnd'] and s['charEnd']>obj['charStart']]
   assert all(i in obj['chunkIndices'] for i in overlap)
   assert obj['chunkIndices']
   counts[obj['kind']]+=1
   if obj['kind']=='table' and len(overlap)>1:counts['tablesSpanningChunks']+=1
   if obj.get('imageError'):counts['missingOrUnsupportedImages']+=1
  counts['documents']+=1;counts['chunks']+=len(segments);counts['shortChunksRetained']+=sum(s['chars']<100 for s in segments)
  assert source.read_bytes()==before and published.read_bytes()==before_published
  rows.append({'project':project,'pmid':source.stem,'rawSha256':hashlib.sha256(before).hexdigest(),'publishedSha256':hashlib.sha256(before_published).hexdigest(),'chunks':len(segments),'resources':[{k:o[k] for k in ('id','kind','lineStart','lineEnd','chunkIndices')} for o in objects]})
result={'counts':counts,'seconds':time.monotonic()-started,'allNonWhitespaceCharactersRetainedInChunks':True,'allObjectsLinkedToEveryOverlappingChunk':True,'all214SourceFilesUnchanged':True,'imageSnapshots':'dry-run here; real snapshot persistence and history verified in isolated integration tests','rows':rows}
(OUT/'corpus-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))

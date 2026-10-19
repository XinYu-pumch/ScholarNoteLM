"""Paragraph splitting with balanced period boundaries and inspectable evidence records."""
import managed_sqlite
import hashlib,json,re,sqlite3
import xml.etree.ElementTree as ET
import pubmed_xml,evidence_resources as resources
from pathlib import Path
import corpus_files as files

SPLITTER='paragraph-period-balanced-8192-alltext-resources-v3'
TEMPLATE='chunk-body-only-v2'
HEADING_MIN_CHARS=100
RECALL_POLICY='heading-visible-min-100-v1'

def recall_allowed(record):
    text=record.get('text','')
    if not text.strip():return False
    if record.get('metadata',{}).get('blockType')!='heading':return True
    from text_presentation import visible_text
    return len(visible_text(text))>=HEADING_MIN_CHARS

def digest(value):
    if not isinstance(value,str):value=json.dumps(value,sort_keys=True,ensure_ascii=False)
    return hashlib.sha256(value.encode()).hexdigest()
def base(e):return files.folder(e,'vectors')
def known_pmids(e):
    path=files.base(e)/'vectors/chunks.sqlite3'
    if not path.exists():return set()
    with managed_sqlite.connect(path) as c:return {r[0] for r in c.execute('SELECT DISTINCT pmid FROM documents')}

def purge_documents(e,pmids):
    if not pmids:return
    path=files.base(e)/'vectors/chunks.sqlite3'
    if path.exists():
        with connect(e) as c:
            removed_assets=set()
            for p in pmids:
                removed_assets.update(json.loads(r[0]).get('assetPath') for r in c.execute('SELECT data FROM resources WHERE pmid=?',(p,)))
                versions=[r[0] for r in c.execute('SELECT version FROM documents WHERE pmid=?',(p,))]
                for version in versions:
                    if re.fullmatch('[a-f0-9]{64}',version):(base(e)/'sources'/f'{version}.md').unlink(missing_ok=True)
                c.execute('DELETE FROM chunk_fts WHERE id IN (SELECT id FROM chunks WHERE pmid=?)',(p,))
                for table in ('resources','chunks','documents','current_documents','indexed','indexed_metadata','embedding_owners'):
                    c.execute(f'DELETE FROM {table} WHERE pmid=?',(p,))
            c.execute('DELETE FROM embeddings WHERE NOT EXISTS (SELECT 1 FROM embedding_owners o WHERE o.profile=embeddings.profile AND o.input_hash=embeddings.input_hash)')
            retained_assets={json.loads(r[0]).get('assetPath') for r in c.execute('SELECT data FROM resources')}
            for relative in removed_assets-retained_assets-{None}:
                asset=(files.base(e)/relative).resolve()
                if asset.is_relative_to((base(e)/'resource-assets').resolve()):asset.unlink(missing_ok=True)
    for p in pmids:
        (files.base(e)/'vectors/chunks'/f'{p}.jsonl').unlink(missing_ok=True)
        (files.base(e)/'vectors/chunks'/f'{p}.jsonl.gz').unlink(missing_ok=True)

def connect(e):
    c=managed_sqlite.connect(base(e)/'chunks.sqlite3',timeout=15);c.row_factory=sqlite3.Row
    c.executescript('''PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS documents(version TEXT PRIMARY KEY,pmid TEXT,text TEXT,meta TEXT);
    CREATE TABLE IF NOT EXISTS current_documents(pmid TEXT PRIMARY KEY,version TEXT,active INTEGER,meta TEXT);
    CREATE TABLE IF NOT EXISTS resources(id TEXT PRIMARY KEY,version TEXT,pmid TEXT,data TEXT);
    CREATE INDEX IF NOT EXISTS resources_version ON resources(version);
    CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY,version TEXT,pmid TEXT,idx INTEGER,text TEXT,meta TEXT);
    CREATE INDEX IF NOT EXISTS chunks_version ON chunks(version);
    CREATE TABLE IF NOT EXISTS embeddings(profile TEXT,input_hash TEXT,dimension INTEGER,vector BLOB,PRIMARY KEY(profile,input_hash));
    CREATE TABLE IF NOT EXISTS indexed(profile TEXT,pmid TEXT,version TEXT,input_hash TEXT,PRIMARY KEY(profile,pmid));
    CREATE TABLE IF NOT EXISTS indexed_metadata(profile TEXT,pmid TEXT,hash TEXT,PRIMARY KEY(profile,pmid));
    CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY,dimension INTEGER,config TEXT);
    CREATE TABLE IF NOT EXISTS embedding_owners(profile TEXT,input_hash TEXT,pmid TEXT,PRIMARY KEY(profile,input_hash,pmid));
    DROP TABLE IF EXISTS pending_vector_deletes;
    CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY,value TEXT);
    CREATE INDEX IF NOT EXISTS embeddings_hash ON embeddings(input_hash);
    CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(id UNINDEXED,text,tokenize='unicode61');
    ''')
    if not c.execute("SELECT 1 FROM schema_meta WHERE key='embedding-owners'").fetchone():
        for d in c.execute('SELECT * FROM documents').fetchall():
            meta=json.loads(d['meta'])
            for r in records_for(c,d['version'],meta):
                h=digest(embedding_text(r))
                c.execute('INSERT OR IGNORE INTO embedding_owners SELECT profile,input_hash,? FROM embeddings WHERE input_hash=?',(d['pmid'],h))
        c.execute("INSERT OR REPLACE INTO schema_meta VALUES('embedding-owners','1')");c.commit()
    return c

def balanced_spans(text,lo,hi):
    while lo<hi and text[lo].isspace():lo+=1
    while hi>lo and text[hi-1].isspace():hi-=1
    if hi-lo<=8192:return [(lo,hi)] if hi>lo else []
    middle=(lo+hi)//2
    candidates=[lo+m.end() for m in re.finditer(r'\.',text[lo:hi]) if 100<=m.end()<=hi-lo-100 and not (text[lo+m.start()-1].isdigit() and text[lo+m.end()].isdigit())]
    cut=min(candidates,key=lambda x:abs(x-middle)) if candidates else middle
    return balanced_spans(text,lo,cut)+balanced_spans(text,cut,hi)

def split(text):
    """Blank-line paragraphs; long paragraphs recursively bisect at the nearest period."""
    segments=[];section=[];references=False;paragraph=0;idx=0;start=0
    spans=[]
    for match in re.finditer(r'\n\s*\n',text):spans.append((start,match.start()));start=match.end()
    spans.append((start,len(text)))
    for begin,end in spans:
        raw=text[begin:end];p=raw.strip()
        if not p:continue
        begin+=len(raw)-len(raw.lstrip());paragraph+=1
        h=re.match(r'^(#{1,6})\s+(.+)',p)
        if h:
            level=len(h[1]);section=[x for x in section if x[0]<level]+[(level,h[2].strip())]
            references=False  # Reference removal happens only in the Markdown cleaner.
        kind='heading' if h and '\n' not in p else 'reference' if references else 'table' if p.startswith('|') or '<table' in p.lower() else 'caption' if re.match(r'^(figure|fig\.|table|图|表)\s*\d',p,re.I) else 'paragraph'
        for part,(a,b) in enumerate(balanced_spans(text,begin,begin+len(p))):
            body=text[a:b];accepted=bool(body.strip())
            segments.append({'text':body,'accepted':accepted,'reason':'','chunkIndex':idx if accepted else None,'paragraphId':f'p{paragraph}','partIndex':part,'charStart':a,'charEnd':b,'lineStart':text.count('\n',0,a)+1,'lineEnd':text.count('\n',0,max(a,b-1))+1,'chars':len(body),'sectionPath':[x[1] for x in section],'blockType':kind})
            if accepted:idx+=1
    return segments

def date_metadata(node):
    """Keep source components and precision; never invent missing month/day."""
    if node is None:return {'raw':'','precision':'unknown'}
    parts={child.tag:''.join(child.itertext()).strip() for child in node}
    raw=parts.get('MedlineDate') or ' '.join(parts[k] for k in ('Year','Month','Day','Season') if parts.get(k))
    precision='range' if parts.get('MedlineDate') else 'day' if parts.get('Day') else 'month' if parts.get('Month') else 'year' if parts.get('Year') else 'unknown'
    return {**parts,'raw':raw,'precision':precision}

def xml_articles(e):
    path=files.base(e)/'pubmed/current.xml'
    if not path.exists():return {},''
    data=path.read_bytes();root=ET.fromstring(data)
    if root.tag!='PubmedArticleSet':raise ValueError('当前 XML 无效，未更新索引')
    def txt(node):return ''.join(node.itertext()).strip() if node is not None else ''
    result={}
    for node,citation,a,metadata in pubmed_xml.records(root):
        p=e.pmid(txt(citation.find('PMID')))
        if a is None:continue
        ids={n.get('IdType'):txt(n) for n in reversed(pubmed_xml.ids(node,citation,metadata))}
        abstract=[{'label':n.get('Label',''),'text':txt(n)} for n in a.findall('Abstract/AbstractText')]
        dates={'journal':date_metadata(a.find('Journal/JournalIssue/PubDate')),'electronic':[date_metadata(n) for n in a.findall('ArticleDate')],'history':[dict(date_metadata(n),status=n.get('PubStatus','')) for n in node.findall('PubmedData/History/PubMedPubDate')]}
        result[p]={'publicationDate':dates['journal']['raw'],'publicationDates':dates,'pmid':p,'doi':ids.get('doi',''),'pmcid':ids.get('pmc',''),'title':txt(a.find('ArticleTitle')),'authors':[txt(x.find('CollectiveName')) or (txt(x.find('LastName'))+' '+txt(x.find('Initials'))).strip() for x in a.findall('AuthorList/Author')],'journal':txt(a.find('Journal/Title')),'year':txt(a.find('Journal/JournalIssue/PubDate/Year')) or txt(a.find('Journal/JournalIssue/PubDate/MedlineDate'))[:4],'issns':[txt(x) for x in a.findall('Journal/ISSN')]+[txt(x) for x in node.findall('MedlineCitation/MedlineJournalInfo/ISSNLinking')],'language':[txt(x) for x in a.findall('Language')],'publicationTypes':[txt(x) for x in a.findall('PublicationTypeList/PublicationType')],'mesh':[{'id':x.get('UI',''),'term':txt(x)} for x in node.findall('MedlineCitation/MeshHeadingList/MeshHeading/DescriptorName')],'abstractSections':abstract,'abstract':'\n\n'.join((x['label']+': ' if x['label'] else '')+x['text'] for x in abstract)}
        if node.tag=='PubmedBookArticle':
            date=a.find('ContributionDate')
            if date is None:date=a.find('Book/PubDate')
            chapter_date=date_metadata(date)
            result[p].update(journal=txt(a.find('Book/BookTitle')),year=txt(date.find('Year')) if date is not None else '',
                publicationDate=chapter_date['raw'],publicationDates={'chapter':chapter_date,'book':date_metadata(a.find('Book/PubDate')),
                'revised':date_metadata(a.find('DateRevised')),'electronic':[],
                'history':[dict(date_metadata(n),status=n.get('PubStatus','')) for n in metadata.findall('History/PubMedPubDate')] if metadata is not None else []},
                publicationTypes=[txt(x) for x in a.findall('PublicationType')],recordType='book_chapter',
                bookAccession=ids.get('bookaccession',''))
    return result,hashlib.sha256(data).hexdigest()

def provenance(e,pmid):
    path=files.base(e)/'metadata/research.sqlite3'
    if not path.is_file():return {}
    with managed_sqlite.connect(path) as c:
        try:
            rows=c.execute('SELECT q.id,q.name,q.active_run FROM queries q JOIN members m ON m.run_id=q.active_run WHERE q.enabled=1 AND q.archived=0 AND m.pmid=?',(pmid,)).fetchall()
            return {'querySources':[{'id':r[0],'name':r[1],'run':r[2]} for r in rows]}
        except sqlite3.OperationalError:return {}

def jcr_index(e):
    path=e.ROOT/'data/research/research.sqlite3'
    if not path.is_file():return {},{},[],{}
    with managed_sqlite.connect(path) as c:
        row=c.execute("SELECT value FROM settings WHERE key='jcr'").fetchone()
    info=json.loads(row[0]) if row else {};version=info.get('version','')
    if not re.fullmatch('[a-f0-9]{64}',version):return {},{},[],{}
    source=e.ROOT/'data/reference/jcr'/f'{version}.json'
    if not source.exists():return {},{},[],{}
    values=json.loads(source.read_text());issns={};titles={}
    for i,r in enumerate(values):
        for key in ('issn','eissn'):
            n=norm(r.get(key,''))
            if n:issns.setdefault(n,set()).add(i)
        titles.setdefault(norm(r.get('journal','')),set()).add(i)
    return issns,titles,values,{'referenceVersion':version,'referenceName':info.get('name',''),'year':info.get('year')}
def norm(value):return ''.join(c.lower() for c in value if c.isalnum())
def match_jcr(index,article):
    issns,titles,values,info=index;ids=set()
    for value in article.get('issns',[]):ids.update(issns.get(norm(value),set()))
    if not ids:
        candidates=titles.get(norm(article['journal']),set())
        if len({(norm(values[i].get('issn','')),norm(values[i].get('eissn',''))) for i in candidates})==1:ids=candidates
    return {**info,'assignments':[values[i] for i in sorted(ids)]}

def source(e,p,article):
    import artifact_state,markdown_service
    root=files.base(e);md=root/'markdown'/f'{p}.md';pdf=root/'pdf'/f'{p}.pdf';meta_path=root/'metadata/markdown'/f'{p}.json'
    info=json.loads(meta_path.read_text()) if meta_path.exists() else {}
    state=artifact_state.markdown_state(e,p,markdown_service.config(e));valid=state['markdownState']=='latest'
    if valid:
        text=md.read_text();kind='fulltext';path=f'markdown/{p}.md'
    elif state['pdf']:
        text='';kind='pending_fulltext';path=f'markdown/{p}.md'
    else:
        text=article['abstract'];kind='pubmed_abstract';path='pubmed/current.xml'
    return text,{'resourceFingerprint':resources.fingerprint(root,p,text) if kind=='fulltext' else None,'sourceKind':kind,'sourcePath':path,'pdfSha256':state['pdfSha256'],'cleaningSignature':info.get('cleaningSignature') if valid else None,'conversionEngine':info.get('engine') if valid else None,'pdfPages':info.get('pages') if valid else None,'pdfLocations':[],'locationMethod':'markdown-offset' if valid else 'pubmed-abstract-offset','pdfState':state['pdfState'],'markdownState':state['markdownState'],'rebuildEpoch':artifact_state.epoch(e,p)}

def cleared(e):return (files.base(e)/'metadata/index-cleared.json').exists()

def sync(e,pmids=None,reconcile=True):
    if cleared(e):return ''
    # Consistent snapshot against concurrent Markdown publishing / XML reconciliation.
    with files.lock(e):
        if cleared(e):return ''
        if reconcile:files.reconcile_locked(e)
        return sync_locked(e,pmids)

def sync_locked(e,pmids=None):
    if files.current(e) is None:return ''
    with connect(e) as c:
        articles,xml_hash=xml_articles(e);jcr=jcr_index(e)
        if pmids is None:c.execute('UPDATE current_documents SET active=0')
        else:c.executemany('UPDATE current_documents SET active=0 WHERE pmid=?',[(p,) for p in pmids])
        for p,article in articles.items():
            if pmids is not None and p not in pmids:continue
            text,src=source(e,p,article);version=digest([e.PROJECT,p,src['sourceKind'],digest(text),src['pdfSha256'],src['cleaningSignature'],SPLITTER,src['rebuildEpoch'],src.get('resourceFingerprint')])
            meta={**article,'jcr':match_jcr(jcr,article),**provenance(e,p),**src,'projectId':e.PROJECT,'documentVersion':version,'markdownSha256':digest(text),'xmlSha256':xml_hash,'splitterVersion':SPLITTER,'snapshotPath':f'vectors/sources/{version}.md'}
            existing=c.execute('SELECT 1 FROM documents WHERE version=?',(version,)).fetchone()
            if not existing:
                segments=split(text);accepted=[s for s in segments if s['accepted']]
                ids=[digest([version,s['chunkIndex'],s['charStart'],s['text']]) for s in accepted]
                objects=resources.extract(files.base(e),p,version,text,segments,e.atomic) if src['sourceKind']=='fulltext' else []
                for obj in objects:c.execute('INSERT INTO resources VALUES(?,?,?,?)',(obj['id'],version,p,json.dumps(obj,ensure_ascii=False)))
                for i,s in enumerate(accepted):
                    details={k:v for k,v in s.items() if k not in ('text','accepted','reason')};details.update(resourceIds=[obj['id'] for obj in objects if s['chunkIndex'] in obj['chunkIndices']],chunkId=ids[i],previousChunkId=ids[i-1] if i else None,nextChunkId=ids[i+1] if i+1<len(ids) else None,paragraphId=version+':'+s['paragraphId'],contentSha256=digest(s['text']))
                    c.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?)',(ids[i],version,p,i,s['text'],json.dumps(details,ensure_ascii=False)))
                    c.execute('INSERT INTO chunk_fts VALUES(?,?)',(ids[i],s['text']))
                c.execute('INSERT INTO documents VALUES(?,?,?,?)',(version,p,text,json.dumps(meta,ensure_ascii=False)))
                e.atomic(files.folder(e,'vectors/sources')/f'{version}.md',text)
            encoded=json.dumps(meta,ensure_ascii=False)
            c.execute('INSERT OR REPLACE INTO current_documents VALUES(?,?,1,?)',(p,version,encoded))
        # SQLite stores article metadata once per version. Full JSONL is an explicit
        # export, not a second eagerly maintained copy of every block's metadata.
        # Retain old versions in SQLite/sources and clean only removed membership.
        output=base(e)/'chunks'
        for path in output.glob('*.jsonl'):
            if path.stem not in articles:path.unlink()
        for path in output.glob('*.jsonl.gz'):
            if path.name.removesuffix('.jsonl.gz') not in articles:path.unlink()
        return xml_hash

def records_for(c,version,meta):
    objects={r['id']:json.loads(r['data']) for r in c.execute('SELECT id,data FROM resources WHERE version=?',(version,))} if c.execute("SELECT 1 FROM sqlite_master WHERE name='resources'").fetchone() else {}
    result=[]
    for r in c.execute('SELECT * FROM chunks WHERE version=? ORDER BY idx',(version,)):
        details=json.loads(r['meta']);result.append({'id':r['id'],'text':r['text'],'metadata':{**meta,**details},'resources':[objects[k] for k in details.get('resourceIds',[]) if k in objects]})
    return result
def embedding_text(record):
    # Metadata locates evidence; it must not contribute to passage relevance.
    return record['text']
def input_signature(records):return digest([TEMPLATE,*[digest(embedding_text(r)) for r in records]])
def inspect_documents(e,profile=''):
    """Read current dependency state without syncing chunks or creating an index.

    A stale cached document is never presented as indexed under new cleaning
    rules. Actual snapshots remain untouched until an explicit update action.
    """
    from contextlib import closing, nullcontext
    if cleared(e):return []
    path=files.base(e)/'vectors/chunks.sqlite3'
    connection=managed_sqlite.connect(path.as_uri()+'?mode=ro',uri=True) if path.is_file() else None
    if connection:connection.row_factory=sqlite3.Row
    result=[]
    with closing(connection) if connection else nullcontext():
        articles,_=xml_articles(e)
        for p,article in sorted(articles.items(),key=lambda x:int(x[0])):
            text,src=source(e,p,article)
            version=digest([e.PROJECT,p,src['sourceKind'],digest(text),src['pdfSha256'],src['cleaningSignature'],SPLITTER,src['rebuildEpoch'],src.get('resourceFingerprint')])
            cached=connection.execute('SELECT * FROM current_documents WHERE pmid=? AND active=1',(p,)).fetchone() if connection else None
            meta={**(json.loads(cached['meta']) if cached else {}),**article,**src,'documentVersion':version}
            records=records_for(connection,version,meta) if cached and cached['version']==version else []
            # Preview counts in memory so an unbuilt document can still enable
            # the explicit index button. This never persists chunks/snapshots.
            count=len(records) if cached and cached['version']==version else sum(s['accepted'] for s in split(text))
            indexed=connection.execute('SELECT * FROM indexed WHERE profile=? AND pmid=?',(profile,p)).fetchone() if connection else None
            ready=bool(indexed and indexed['version']==version and records and indexed['input_hash']==input_signature(records))
            meta_row=connection.execute('SELECT hash FROM indexed_metadata WHERE profile=? AND pmid=?',(profile,p)).fetchone() if connection else None
            state='latest' if ready else 'blocked' if src['sourceKind']=='pending_fulltext' else 'outdated' if indexed else 'missing'
            result.append({'pmid':p,'title':article['title'],'version':version,'sourceKind':src['sourceKind'],'chunks':count,'indexed':ready,'metadataReady':bool(ready and meta_row and meta_row[0]==metadata_signature(meta)),'state':state,'metadata':meta})
    return result

def documents(e,profile='',pmid=None):
    if cleared(e):return []
    if not (files.base(e)/'pubmed/current.xml').is_file():return []
    with connect(e) as c:
        result=[]
        for d in c.execute('SELECT * FROM current_documents WHERE active=1 AND (? IS NULL OR pmid=?) ORDER BY CAST(pmid AS INTEGER)',(pmid,pmid)).fetchall():
            m=json.loads(d['meta']);records=records_for(c,d['version'],m)
            indexed=c.execute('SELECT * FROM indexed WHERE profile=? AND pmid=?',(profile,d['pmid'])).fetchone()
            ready=bool(indexed and indexed['version']==d['version'] and indexed['input_hash']==input_signature(records))
            meta_row=c.execute('SELECT hash FROM indexed_metadata WHERE profile=? AND pmid=?',(profile,d['pmid'])).fetchone()
            metadata_ready=bool(meta_row and meta_row[0]==metadata_signature(m))
            state='latest' if ready else 'blocked' if m['sourceKind']=='pending_fulltext' else 'outdated' if indexed else 'missing'
            result.append({'pmid':d['pmid'],'title':m['title'],'version':d['version'],'sourceKind':m['sourceKind'],'chunks':len(records),'indexed':ready,'metadataReady':metadata_ready,'state':state,'metadata':m})
        return result

def metadata_signature(meta):
    return digest({k:meta.get(k) for k in ('pmid','title','journal','year','publicationDate','doi','pmcid','sourceKind','authors','publicationDates','mesh','publicationTypes','language')})

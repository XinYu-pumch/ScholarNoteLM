"""Body-only embedding API recall shared by reviews and QA."""
import json,struct
from collections import defaultdict
from types import SimpleNamespace
import vector_chunks as chunks
import retrieval_settings as settings

POLICY='body-only-api-cosine-v5'
def signature(root,cfg=None):
    import vector_service as v
    cfg=cfg or settings.snapshot(root);emb=v.config(SimpleNamespace(ROOT=root))
    return chunks.digest([POLICY,chunks.TEMPLATE,chunks.RECALL_POLICY,chunks.HEADING_MIN_CHARS,v.profile(emb),cfg.get('embeddingFingerprint',settings.fingerprint(emb))])
def ready(root,cfg=None):return settings.verified(root)
def corpus(e):
    if chunks.cleared(e):raise ValueError('索引数据已清空，请先重新建立索引，再准备综述提示词')
    chunks.sync(e);result=[]
    with chunks.connect(e) as c:
        for d in c.execute('SELECT * FROM current_documents WHERE active=1 ORDER BY CAST(pmid AS INTEGER)').fetchall():
            result.extend(r for r in chunks.records_for(c,d['version'],json.loads(d['meta'])) if chunks.recall_allowed(r))
    if not result:raise ValueError('没有可检索的文本块，请先完成 Markdown 转换或检查 PubMed 摘要')
    return result

class APIRecall:
    def __init__(self,e,records,cfg,check,progress):
        import numpy as np
        import vector_service as v
        import corpus_files as files
        self.np=np;self.e=e;self.check=check;self.cfg=v.config(e);self.queries={}
        self.fingerprint=settings.fingerprint(self.cfg)
        if not settings.verified(e.ROOT,self.cfg) or self.fingerprint!=cfg.get('embeddingFingerprint',self.fingerprint):raise ValueError('Embedding 配置已变化或未验证，请重新验证并准备提示词')
        pid=v.profile(self.cfg);keys=[chunks.digest(chunks.embedding_text(r)) for r in records];wanted=set(keys)
        with chunks.connect(e) as c:
            cached={row['input_hash']:np.frombuffer(row['vector'],dtype='<f4').copy() for row in c.execute('SELECT * FROM embeddings WHERE profile=?',(pid,)) if row['input_hash'] in wanted}
        pending=list(dict.fromkeys(k for k in keys if k not in cached));by_key={k:r for k,r in zip(keys,records)}
        owners=defaultdict(set)
        for key,r in zip(keys,records):owners[key].add(r['metadata']['pmid'])
        for at in range(0,len(pending),self.cfg['batchSize']):
            check();group=pending[at:at+self.cfg['batchSize']];progress(f'生成缺失的 API 向量 {at} / {len(pending)}（已有 {len(keys)-len(pending)} 块可复用）')
            values=v.embed([chunks.embedding_text(by_key[k]) for k in group],self.cfg,check=check,root=e.ROOT)
            check()
            with files.lock(e),chunks.connect(e) as c:
                current=files.current(e) or set()
                for k,value in zip(group,values):
                    dim=len(value);old=c.execute('SELECT dimension FROM profiles WHERE id=?',(pid,)).fetchone()
                    if old and old['dimension']!=dim:raise ValueError('Embedding 维度改变，请修改模型版本标识后重新索引')
                    if not owners[k]<=current:raise ValueError('文献集合发生变化，请重新准备提示词')
                    c.execute('INSERT OR IGNORE INTO profiles VALUES(?,?,?)',(pid,dim,json.dumps(v.public(self.cfg))))
                    c.execute('INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?)',(pid,k,dim,struct.pack('<'+'f'*dim,*value)))
                    c.executemany('INSERT OR IGNORE INTO embedding_owners VALUES(?,?,?)',[(pid,k,p) for p in owners[k]])
                    cached[k]=np.asarray(value,dtype='float32')
        check()
        with files.lock(e),chunks.connect(e) as c:
            import artifact_state
            current=files.current(e) or set()
            for k,r in zip(keys,records):
                pmid=r['metadata']['pmid']
                if pmid not in current or artifact_state.epoch(e,pmid)!=r['metadata'].get('rebuildEpoch',0):raise ValueError('文献集合已变化，请重新准备提示词')
                c.execute('INSERT OR IGNORE INTO embedding_owners VALUES(?,?,?)',(pid,k,pmid))
        self.matrix=np.stack([cached[k] for k in keys]);norms=np.linalg.norm(self.matrix,axis=1,keepdims=True)
        if not np.isfinite(self.matrix).all() or (norms==0).any():raise ValueError('本地缓存的向量无效，请重建向量索引')
        self.matrix=self.matrix/norms
    def recall(self,query,k):
        import vector_service as v
        self.check()
        if settings.fingerprint(v.config(self.e))!=self.fingerprint:raise ValueError('Embedding 配置在运行期间改变，请重新准备提示词')
        if query not in self.queries:self.queries[query]=self.np.asarray(v.embed([query],self.cfg,check=self.check,root=self.e.ROOT,purpose='query')[0],dtype='float32')
        q=self.queries[query]
        if len(q)!=self.matrix.shape[1]:raise ValueError('查询向量与文献向量维度不一致，请检查模型版本')
        scores=self.matrix@(q/self.np.linalg.norm(q));ids=self.np.argsort(-scores,kind='stable')[:k]
        return [(int(i),float(scores[i])) for i in ids]
class Retriever:
    def __init__(self,root,cache,records,check,progress,cfg=None,e=None):
        self.records=[r for r in records if chunks.recall_allowed(r)];self.check=check
        self.cfg=cfg or settings.snapshot(root)
        self.recall=APIRecall(e,self.records,self.cfg,check,progress) if self.records else None
    def retrieve(self,query,candidates,topk):
        self.check()
        if not self.records:return []
        return [{**self.records[i],'retrievalScore':score} for i,score in self.recall.recall(query,topk)]

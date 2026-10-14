"""Small, pinned tokenizer assets only; never download or execute model code."""
import hashlib, math, os, tempfile, time
import embedding_providers as providers

JINA_V4_REVISION='853c867b65b749f3c3c72a06868140d842e04f06'
JINA_V4_SHA256='9c5ae00e602b8860cbd784ba82a8aa14e8feecec692e7076590d014d7b7fdafa'
MAX_ASSET_BYTES=16*1024*1024

def jina_costs(root,cfg,texts,check):
    """Return tokenizer budgets for the known API model, or None for safe fallback.

    Cache is shared by projects, independent of keys. A custom model revision must
    not inherit calibration. Download failure never blocks indexing indefinitely.
    """
    check()
    if not providers.is_jina(cfg) or cfg['model'].removeprefix('jina-ai/')!='jina-embeddings-v4' or cfg.get('modelRevision'):
        return None
    import httpx
    try:from tokenizers import Tokenizer
    except ImportError:return None
    path=root/'cache/embedding-tokenizers/jina-embeddings-v4/tokenizer.json'
    temporary=None
    try:
        check()
        valid=path.is_file() and path.stat().st_size<=MAX_ASSET_BYTES and hashlib.sha256(path.read_bytes()).hexdigest()==JINA_V4_SHA256
        if not valid:
            url=f'https://huggingface.co/jinaai/jina-embeddings-v4/resolve/{JINA_V4_REVISION}/tokenizer.json'
            path.parent.mkdir(parents=True,exist_ok=True)
            deadline=time.monotonic()+30
            with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as output:
                temporary=output.name;size=0;digest=hashlib.sha256()
                with httpx.stream('GET',url,timeout=10,follow_redirects=True,trust_env=False,proxy=providers.system_proxy(url)) as response:
                    response.raise_for_status()
                    for block in response.iter_bytes(65536):
                        check();size+=len(block)
                        if time.monotonic()>deadline:raise ValueError('Tokenizer download deadline exceeded')
                        if size>MAX_ASSET_BYTES:raise ValueError('Tokenizer asset too large')
                        digest.update(block);output.write(block)
                if digest.hexdigest()!=JINA_V4_SHA256:raise ValueError('Tokenizer checksum mismatch')
            os.replace(temporary,path);temporary=None
        tokenizer=Tokenizer.from_file(str(path));tokenizer.no_truncation();tokenizer.no_padding()
        costs=[]
        for start in range(0,len(texts),256):
            check()
            # Include room for API special tokens; never modify embedding inputs.
            costs.extend(math.ceil(len(value.ids)*1.05)+8 for value in tokenizer.encode_batch(texts[start:start+256]))
        return costs
    except InterruptedError:
        raise
    except (OSError,ValueError,httpx.HTTPError):
        return None
    finally:
        if temporary:
            try:os.unlink(temporary)
            except FileNotFoundError:pass

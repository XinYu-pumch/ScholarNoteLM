"""Drain physical Chroma deletions without racing the indexing process."""
import argparse,os,sys,time
from pathlib import Path
ROOT=Path(os.environ['SCHOLARNOTELM_ROOT'])
sys.path.insert(0,str(ROOT/'services/downloader'))
import engine as e,corpus_files as files,storage,vector_service as vectors
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--project',required=True);a=parser.parse_args();e.PROJECT=e.ident(a.project)
    for _ in range(120):
        try:
            with storage.file_lock(files.base(e)/'metadata/vector-chroma.lock'),storage.file_lock(ROOT/'config/storage.lock',shared=True):
                vectors.purge_pending_locked(e)
            break
        except ValueError:time.sleep(.5)

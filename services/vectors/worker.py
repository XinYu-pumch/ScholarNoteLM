import argparse,os,sys
from pathlib import Path
ROOT=Path(os.environ.get('SCHOLARNOTELM_ROOT',Path(__file__).resolve().parents[2])).resolve()
sys.path.insert(0,str(ROOT/'services/downloader'))
import engine as e
import vector_service as vectors
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--project',required=True);parser.add_argument('--job',required=True);a=parser.parse_args()
    e.PROJECT=e.ident(a.project);vectors.run(e,e.ident(a.job))

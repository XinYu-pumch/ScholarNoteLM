"""Detached reader worker: only identifiers, never credentials, in process arguments."""
import argparse,asyncio
import engine,reader_service,storage
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--id',required=True);p.add_argument('--run',required=True)
    a=p.parse_args();engine.PROJECT=engine.ident(a.project)
    with storage.file_lock(engine.ROOT/'config/storage.lock',shared=True):
        asyncio.run(reader_service.run(engine,a.id,a.run))

"""Independent, cancellable review process; model credentials never enter run files."""
import argparse,asyncio
import engine,review_writing,storage
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('project','review','token'):p.add_argument('--'+name,required=True)
    a=p.parse_args();engine.PROJECT=engine.ident(a.project)
    with storage.file_lock(engine.ROOT/'config/storage.lock',shared=True):
        asyncio.run(review_writing.run(engine,a.review,a.token))

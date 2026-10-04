"""Independent QA worker; credentials resolved locally, not passed on the command line."""
import argparse,asyncio
import engine,qa_service,storage
if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',required=True);parser.add_argument('--run',required=True)
    args=parser.parse_args();engine.PROJECT=engine.ident(args.project)
    with storage.file_lock(engine.ROOT/'config/storage.lock',shared=True):
        asyncio.run(qa_service.run(engine,args.run))

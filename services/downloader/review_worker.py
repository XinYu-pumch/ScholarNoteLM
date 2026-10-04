"""Independent review generation process; credentials remain in system settings."""
import argparse
import engine,review_service
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('project','review','version','token'):p.add_argument('--'+name,required=True)
    a=p.parse_args();engine.PROJECT=engine.ident(a.project)
    review_service.worker(engine,a.review,a.version,a.token)

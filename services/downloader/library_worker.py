import argparse
import engine as e
import library_service
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--job',required=True);a=p.parse_args()
    e.PROJECT=e.ident(a.project)
    library_service.run(e,e.ident(a.job))

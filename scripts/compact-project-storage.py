"""Inspect/apply lossless storage compaction; defaults to a read-only estimate."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/downloader'))
import engine as e
import corpus_files
import project_compaction
import review_service
import storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--project', action='append', help='Project ID; repeat to select several. Defaults to all registered projects.')
    parser.add_argument('--apply', action='store_true', help='Apply verified lossless changes while holding exclusive storage locks.')
    parser.add_argument('--html', action='store_true', help='Also pool duplicate evidence/images inside recognized standalone HTML exports. All resources stay embedded.')
    args = parser.parse_args()
    e.ROOT = args.root.resolve()
    with ExitStack() as guards:
        if args.apply:
            guards.enter_context(storage.file_lock(e.ROOT / 'config/storage.lock'))
            guards.enter_context(storage.file_lock(e.ROOT / 'config/catalog.lock'))
        cfg = storage.config(e.ROOT)
        projects = args.project or list(cfg['projects'])
        for project in projects:
            if project not in cfg['projects']:
                raise ValueError('未知项目 ID')
            e.PROJECT = project
            with ExitStack() as project_guards:
                if args.apply:
                    project_guards.enter_context(review_service.lock(e))
                    project_guards.enter_context(corpus_files.lock(e))
                result = project_compaction.compact_project(e, args.apply, include_html=args.html)
                result['folder'] = cfg['projects'][project]
                print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

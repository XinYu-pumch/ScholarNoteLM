"""Conservative v2 contracts. Every writable integration project is temporary."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import shutil
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import markdown_cleaning as rules
import markdown_service as m
import engine as e
import corpus_files as files
import artifact_state
import vector_chunks as chunks
import vector_service as vectors
import review_writing
import library_service
from pdf_fixture import pdf

NOTICE='Copyright © 2021 Wolters Kluwer Health, Inc. Unauthorized reproduction of this article is prohibited.'
SCIENCE='We found a sustained treatment response in 24 participants.'


class CleaningIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.old=(e.ROOT,e.PROJECT);self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp')
        e.ROOT,e.PROJECT=Path(self.tmp.name),'cleaning-test';self.base=files.base(e)
        e.write_json(e.ROOT/'config/markdown.json',dict(m.DEFAULTS))
        self.raw='# Results\r\n\r\n'+SCIENCE*4+'\r\n\r\n![Figure](../assets/1/figure.png)\r\n\r\n'+NOTICE+'\r\n\r\n- Useful result\r\n'
        e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article><ArticleTitle>Title</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
        self.body=pdf();e.atomic(self.base/'pdf/1.pdf',self.body)
        e.atomic(self.base/'markdown/raw/1.md',self.raw.encode());e.atomic(self.base/'markdown/1.md',self.raw.encode())
        e.write_json(self.base/'metadata/markdown/1.json',{'pdfSha256':hashlib.sha256(self.body).hexdigest(),'rawSha256':hashlib.sha256(self.raw.encode()).hexdigest(),'cleaningSignature':m.signature(m.config(e)),'rebuildEpoch':artifact_state.epoch(e,'1')})
        spec=importlib.util.spec_from_file_location('v2_marker_worker',self.old[0]/'services/marker/worker.py');self.worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.worker)
    def tearDown(self):
        e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
    def job(self,name):
        report=files.folder(e,'logs/markdown-'+name)
        job={'id':name,'state':'queued','mode':'clean','pmids':['1'],'config':m.config(e),'logPath':str(report),'completed':0,'skipped':0,'failed':0,'items':[]}
        e.write_json(m.job_path(e),job)
        with patch.object(self.worker,'ROOT',e.ROOT),patch.object(socket.socket,'connect',socket.socket.connect),patch.dict(os.environ,{}),patch.object(vectors,'rpc',side_effect=AssertionError('must not index')):
            self.worker.run(e.PROJECT,name)
        return m.read_job(e),report
    def protected_bytes(self):
        return {str(p.relative_to(self.base)):p.read_bytes() for folder in ('markdown','vectors') for p in (self.base/folder).rglob('*') if p.is_file() and not p.name.endswith(('-shm','-wal'))}


CITE='Zhang S, Bai Z, Wang Z, Wang X, Wang W, Li H and Dong Q (2022) Molecular characterization and phylogeny of Shiga toxin-producing Escherichia coli derived from cattle farm. Front. Microbiol. 13:950065. doi: 10.3389/fmicb.2022.950065'
WATERMARK='Downloaded from https://example.org/article.pdf by guest on 22 June 2020'

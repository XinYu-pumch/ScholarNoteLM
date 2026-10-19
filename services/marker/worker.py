"""Offline Marker job: reuse models, preserve raw output, publish against current XML."""
import argparse,gc,hashlib,json,os,shutil,socket,sys,time,traceback
from pathlib import Path
ROOT=Path(os.environ.get('SCHOLARNOTELM_ROOT',Path(__file__).resolve().parents[2])).resolve()
sys.path.insert(0,str(ROOT/'services/downloader'))
sys.path.insert(0,str(ROOT/'services/marker/vendor'))
import engine as e
import markdown_service as m
import corpus_files as files
import storage
import artifact_state
import conversion_config as conversion
import compute_devices

class ModelLoadError(RuntimeError):pass

def published(text):
    return text.replace('](../assets/','](assets/').replace('src="../assets/','src="assets/').replace("src='../assets/","src='assets/")

def run(project,job_id):
    e.PROJECT=project;base=files.base(e);job=m.read_job(e)
    if not job or job['id']!=job_id:raise RuntimeError('转换任务已被替换')
    report=Path(job['logPath']);cfg=job['config'];models=None;inference=None
    def cancelled():return (base/'metadata'/('markdown-stop-'+job_id)).exists() or bool(job.get('owner') and not e.process_alive(job['owner']))
    def save():
        snapshot=dict(job)
        # Maintenance must still see an active job until its owned service exits.
        if not snapshot.get('finished') and snapshot['state'] in ('stopped','done','failed'):
            snapshot['state']='stopping' if snapshot['state']=='stopped' else 'running'
        e.write_json(m.job_path(e),snapshot);e.write_json(report/'report.json',snapshot)
        e.atomic(report/'report.txt','ScholarNoteLM 本地 Markdown 转换\n'+json.dumps(snapshot,ensure_ascii=False,indent=2))
    job.update(state='running',pid=os.getpid(),started=time.time());save()
    try:
        with storage.file_lock(ROOT/'data/locks/conversion-models.lock'), storage.file_lock(ROOT/'config/storage.lock',shared=True):
            os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HOME=str(ROOT/'cache/huggingface'),TORCH_HOME=str(ROOT/'cache/torch'),XDG_CACHE_HOME=str(ROOT/'cache'),SURYA_CACHE_DIR=str(ROOT/'models/marker'),PYTORCH_ENABLE_MPS_FALLBACK='1',TOKENIZERS_PARALLELISM='false',TQDM_DISABLE='1')
            if cfg['device']!='auto':os.environ['TORCH_DEVICE']=cfg['device']
            else:os.environ.pop('TORCH_DEVICE',None)
            # macOS keeps its existing in-process MPS model path and precision.
            # Windows CUDA lives in a separate process so a failed context cannot
            # contaminate CPU recovery or the durable job's ownership/locks.
            if job['mode']=='convert':
                selection=compute_devices.detect(ROOT,cfg['device'])
                if cfg['device'] not in ('auto','cpu') and selection['device']!=cfg['device']:
                    raise RuntimeError('所选加速设备不可用：'+selection.get('reason',''))
                job['compute']=selection;job['device']=selection['device'];save()
                os.environ['TORCH_DEVICE']=selection['device']
                if selection['device']=='cuda' and os.name=='nt':
                    from inference_client import InferenceClient
                    def compute_changed():
                        job['compute']=inference.selection;job['device']=inference.selection['device']
                        job['acceleratorFallbacks']=inference.fallbacks;save()
                    inference=InferenceClient(ROOT,selection,automatic=cfg['device']=='auto',on_change=compute_changed)
            # Enforce offline conversion even if a library tries a fallback download.
            original_connect=socket.socket.connect
            def offline(sock,address):
                if sock.family in (socket.AF_INET,socket.AF_INET6):raise RuntimeError('本地转换禁止网络请求；请检查模型文件是否完整')
                return original_connect(sock,address)
            socket.socket.connect=offline
            for p in job['pmids']:
                if cancelled():
                    job['state']='stopped';break
                job.update(current=p,page=0,pages=0);save();started=time.monotonic();stage=report/'staging'/p;stage.mkdir(parents=True,exist_ok=True);worker_info={}
                try:
                    with files.lock(e):
                        if p not in (files.current(e) or set()):
                            job['skipped']+=1;job['items'].append({'pmid':p,'state':'skipped','reason':'已离开当前 XML'});continue
                        generation=artifact_state.epoch(e,p)
                        pdf=base/'pdf'/f'{p}.pdf';raw=base/'markdown/raw'/f'{p}.md';dest=base/'markdown'/f'{p}.md'
                        meta_path=base/'metadata/markdown'/f'{p}.json';meta=json.loads(meta_path.read_text()) if meta_path.exists() else {}
                        raw_before=raw.read_bytes() if raw.is_file() else None
                        dest_before=dest.read_bytes() if dest.is_file() else None
                        same_engine=conversion.matches(ROOT,meta,cfg)
                        source_cfg=cfg if same_engine else meta.get('conversionConfig',{**cfg,'engine':'marker'})
                        if job['mode']=='convert':
                            checked=e.validate_pdf(pdf);sha=checked['sha256'];stat=pdf.stat()
                            requested,effective=m.text_workers(cfg.get('pdftextWorkers','auto'),checked['pages'])
                            worker_info={'pages':checked['pages'],'pdftextWorkers':requested,'effectiveTextWorkers':effective}
                            if not job.get('force') and same_engine and raw.is_file() and dest.is_file() and meta.get('pdfSha256')==sha and meta.get('rebuildEpoch',0)==generation and meta.get('rawSha256',artifact_state.file_hash(e,raw))==artifact_state.file_hash(e,raw) and m.signature_matches(meta,cfg):
                                job['skipped']+=1;job['items'].append({'pmid':p,'state':'skipped','reason':'PDF 和清洗规则未变'});continue
                            shutil.copy2(pdf,stage/f'{p}.pdf')
                            raw_text=raw_before.decode('utf-8') if not job.get('force') and same_engine and raw_before is not None and meta.get('pdfSha256')==sha and meta.get('rebuildEpoch',0)==generation else None
                        else:
                            if not raw.is_file():raise ValueError('没有转换原稿')
                            if not same_engine:raise ValueError('当前原稿属于另一个引擎，请执行 PDF 转换以更新原稿')
                            raw_text=raw_before.decode('utf-8');sha=meta.get('pdfSha256');stat=pdf.stat() if pdf.exists() else None
                    if job['mode']=='convert' and dest_before is not None and raw_before is not None:
                        expected=meta.get('publishedSha256')
                        if not expected and m.signature_matches(meta,source_cfg):
                            old_clean=published(m.clean(raw_before.decode('utf-8'),source_cfg)[0])
                            expected=hashlib.sha256(old_clean.encode()).hexdigest()
                        if (not expected or hashlib.sha256(dest_before).hexdigest()!=expected) and not job.get('replaceEdited'):
                            raise ValueError('现有 Markdown 包含手动编辑或无法确认原始版本；请使用明确覆盖操作，旧版本将保留在历史目录')
                    reuse_raw=raw_text is not None
                    if raw_text is None:
                        if inference is not None:
                            out=inference.convert(stage/f'{p}.pdf',stage,requested,cancelled)
                            job['compute']=inference.selection;job['device']=inference.selection['device']
                            job['acceleratorFallbacks']=inference.fallbacks;save()
                        elif models is None:
                            try:
                                from marker.models import create_model_dict
                                from marker.config.parser import ConfigParser
                                from marker.output import save_output
                                models=create_model_dict()
                            except Exception as ex:raise ModelLoadError(str(ex)) from ex
                            import torch
                            job['device']=os.environ.get('TORCH_DEVICE') or ('cuda' if torch.cuda.is_available() else 'mps' if torch.backends.mps.is_available() else 'cpu');save()
                        if inference is None:
                            parser=ConfigParser({'output_dir':str(stage),'output_format':'markdown','disable_ocr':True,'pdftext_workers':requested,'disable_tqdm':True,'use_llm':False})
                            converter=parser.get_converter_cls()(config=parser.generate_config_dict(),artifact_dict=models,processor_list=parser.get_processors(),renderer=parser.get_renderer(),llm_service=None)
                            rendered=converter(str(stage/f'{p}.pdf'));out=Path(parser.get_output_folder(str(stage/f'{p}.pdf')))
                            save_output(rendered,str(out),p)
                            del rendered,converter
                        raw_text=(out/f'{p}.md').read_bytes().decode('utf-8')
                        # Keep images; all Markdown variants use the same live asset location.
                        for img in out.iterdir():
                            if img.suffix.lower() in ('.png','.jpg','.jpeg','.webp'):
                                raw_text=raw_text.replace(']('+img.name+')','](../assets/'+p+'/'+img.name+')')
                        worker_info['computeDevice']=job.get('device','cpu')
                        if inference is not None:worker_info['computePrecision']=inference.selection['precision']
                    if len(raw_text.strip())<40:raise ValueError('未提取到足够正文；Marker 当前关闭 OCR，扫描件需另行 OCR')
                    cleaned,removed=m.clean(raw_text,cfg)
                    with files.lock(e):
                        # If the PDF changed during inference, never publish stale text as current.
                        files.reconcile_locked(e)
                        if cancelled():raise InterruptedError('转换已停止，结果未发布')
                        if conversion.identity(ROOT,m.config(e))!=conversion.identity(ROOT,cfg):raise ValueError('转换配置已改变，结果未发布')
                        if (dest.read_bytes() if dest.is_file() else None)!=dest_before:raise ValueError('转换期间 Markdown 被编辑，结果未发布')
                        if p not in (files.current(e) or set()) or artifact_state.epoch(e,p)!=generation:raise ValueError('转换期间文献已移出或重新纳入，结果已丢弃，请重新转换')
                        source=base/'pdf'/f'{p}.pdf'
                        if not source.exists() or e.validate_pdf(source)['sha256']!=sha:raise ValueError('转换期间 PDF 已改变，结果未发布，请重新转换')
                        if (raw.read_bytes() if raw.is_file() else None)!=raw_before:raise ValueError('转换期间 Markdown 原稿已改变，结果未发布，请重新清洗')
                        raw_dest=files.folder(e,'markdown/raw')/f'{p}.md'
                        md_dest=files.folder(e,'markdown')/f'{p}.md'
                        history=base/'markdown/history'/p/job_id
                        if dest_before is not None or raw_before is not None:
                            history.mkdir(parents=True,exist_ok=True)
                            if raw_before is not None:
                                (history/'raw').mkdir();(history/'raw'/f'{p}.md').write_bytes(raw_before)
                            if dest_before is not None:(history/f'{p}.md').write_bytes(dest_before)
                            e.write_json(history/'metadata.json',meta)
                            old_assets=base/'markdown/assets'/p
                            if old_assets.is_dir():shutil.copytree(old_assets,history/'assets'/p,dirs_exist_ok=True)
                        image_dest=files.folder(e,'markdown/assets/'+p)
                        out=stage/p
                        if out.exists():
                            for img in out.iterdir():
                                if img.suffix.lower() in ('.png','.jpg','.jpeg','.webp'):shutil.copy2(img,image_dest/img.name)
                        # Raw lives one directory deeper than the cleaned document.
                        if not reuse_raw:e.atomic(raw_dest,raw_text)
                        e.atomic(md_dest,published(cleaned))
                        raw_sha=hashlib.sha256(raw_text.encode('utf-8')).hexdigest()
                        meta={'pmid':p,'pdfSha256':sha,'pdfSize':source.stat().st_size,'pdfMtimeNs':source.stat().st_mtime_ns,'converted':time.time(),'cleaningSignature':m.signature(cfg),'cleaningMode':cfg.get('cleaningMode',m.DEFAULTS['cleaningMode']),'cleaningVersion':m.cleaning_version(cfg),'removedCount':len(removed),'engine':'Marker 1.6.0','ocr':False,'conversionIdentity':conversion.identity(ROOT,cfg),'conversionConfig':cfg,'publishedSha256':hashlib.sha256(published(cleaned).encode()).hexdigest(),'job':job_id,'rebuildEpoch':generation,'rawSha256':raw_sha,**worker_info}
                        e.write_json(meta_path,meta);e.write_json(report/(p+'-cleaning.json'),{'pmid':p,'sourcePath':f'markdown/raw/{p}.md','sourceSha256':raw_sha,'cleaningMode':meta['cleaningMode'],'cleaningVersion':meta['cleaningVersion'],'cleaningSignature':meta['cleaningSignature'],'enabled':True,'positionEncoding':'Unicode characters; charEnd exclusive; lines one-based','removed':removed})
                    job['completed']+=1;job['items'].append({'pmid':p,'state':'success',**worker_info,'removed':len(removed),'seconds':round(time.monotonic()-started,2)})
                except Exception as ex:
                    if cancelled():
                        job['state']='stopped';job['items'].append({'pmid':p,'state':'stopped','reason':'结果未发布'});break
                    traceback.print_exc();job['failed']+=1;job['items'].append({'pmid':p,'state':'failed','error':str(ex),'seconds':round(time.monotonic()-started,2)})
                    if isinstance(ex,ModelLoadError):raise
                finally:
                    shutil.rmtree(stage,ignore_errors=True);gc.collect();save()
            else:job['state']='done'
    except Exception as ex:
        job.update(state='failed',error=str(ex));traceback.print_exc()
    finally:
        if inference is not None:inference.close()
        job.update(current='',finished=time.time());save()
        if job['state']=='done' and job.get('indexAfter',False):
            try:
                import vector_service
                job['vectorFollowup']=vector_service.rpc(e,'auto',{'requestId':job_id,'owner':job.get('owner',0)})
            except Exception as ex:job['vectorFollowup']={'state':'failed','error':str(ex)}
            save()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--project',required=True);parser.add_argument('--job',required=True);args=parser.parse_args()
    run(e.ident(args.project),e.ident(args.job))

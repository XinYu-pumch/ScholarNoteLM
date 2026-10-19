//! Durable one-shot Zotero imports. Each run owns an immutable collection snapshot.
use super::*;
use std::path::PathBuf;
use std::process::{Command, Stdio};

fn location(root:&Path,p:&str)->R<PathBuf>{Ok(project_dir(root,p)?.join("metadata/zotero-job.json"))}
fn read(path:&Path)->R<Value>{serde_json::from_slice(&fs::read(path).map_err(err)?).map_err(err)}
fn save(root:&Path,p:&str,j:&Value)->R<()>{
    write_file(&project_dir(root,p)?.join(format!("metadata/zotero-imports/{}/report.json",s(j,"id"))),j.to_string().as_bytes())?;
    write_file(&location(root,p)?,j.to_string().as_bytes())
}
fn job_lock(root:&Path,p:&str)->R<File>{
    let path=project_dir(root,p)?.join("metadata/zotero-import.lock");
    let f=OpenOptions::new().create(true).truncate(false).read(true).write(true).open(path).map_err(err)?;
    f.try_lock_exclusive().map_err(|_|"Zotero 导入正在运行".to_string())?;Ok(f)
}
pub(super) fn status(root:&Path,p:&str)->R<Value>{
    let path=location(root,p)?;
    if !path.exists(){return Ok(json!(null));}
    let mut j=read(&path)?;
    let lock=job_lock(root,p);
    if lock.is_ok() {
        // Re-read under ownership: a worker may have completed since the first read.
        j=read(&path)?;
        if s(&j,"state")=="completed" && !s(&j,"error").is_empty(){
            let previous=json!({"state":"historical","error":j["error"],"recorded":now()});
            if !j["attempts"].is_array(){j["attempts"]=json!([]);}
            j["attempts"].as_array_mut().unwrap().push(previous);j["error"]=json!("");save(root,p,&j)?;
        }
        if ["queued","running"].contains(&s(&j,"state")) && now().saturating_sub(j["started"].as_u64().or(j["created"].as_u64()).unwrap_or(0))>30 {
            j["state"]=json!("interrupted");j["stage"]=json!("导入已中断");j["error"]=json!("导入进程已退出；已保存的来源和 PDF 保留，可重新导入。");save(root,p,&j)?;
        }
    }
    let dir=project_dir(root,p)?.join(format!("metadata/zotero-imports/{}",s(&j,"id")));
    let receipt=dir.join("process.json");let spawned=dir.join("spawn.json");
    if receipt.exists() || spawned.exists(){
        let mut process=read(if receipt.exists(){&receipt}else{&spawned})?;
        process["lockHeld"]=json!(lock.is_err());j["process"]=process;
    }
    Ok(j)
}
/// Foreground ownership for automation hosts that reap descendants on command exit.
/// Called after dispatch releases the project/import locks; never restart a job here.
#[allow(dead_code)] // Shared module; the desktop host keeps running without this CLI helper.
pub fn wait_for_job(root:&Path,p:&str,id:&str)->R<Value>{
    loop {
        let j=status(root,p)?;
        if s(&j,"id")!=id{return Err("Zotero 任务已变化，请读取原任务报告".into());}
        if !["queued","running"].contains(&s(&j,"state")){return Ok(j);}
        std::thread::sleep(Duration::from_millis(200));
    }
}
// This lock spans an entire query execution, including its network requests.
// Zotero publishes durable ownership while holding it, before its worker starts.
pub(super) fn source_operation(root:&Path,p:&str)->R<File>{
    let f=OpenOptions::new().create(true).truncate(false).read(true).write(true)
        .open(project_dir(root,p)?.join("metadata/source-operations.lock")).map_err(err)?;
    f.try_lock_exclusive().map_err(|_|"文献来源任务正在执行，请完成或取消后再操作".to_string())?;
    if ["queued","running"].contains(&s(&status(root,p)?,"state")) {
        return Err("Zotero 导入正在运行，请完成或取消后再修改文献来源".into());
    }
    Ok(f)
}
pub(super) fn source_job(root:&Path,p:&str,q:&Value)->R<Value>{
    let id=q["run"]["zotero"]["job"].as_str().unwrap_or_else(||s(q,"id"));
    valid_id(id)?;
    let path=project_dir(root,p)?.join(format!("metadata/zotero-imports/{id}/report.json"));
    if !path.exists(){return Ok(Value::Null);}
    let mut j=read(&path)?;
    // The detailed rows belong in the report, not in each workspace response.
    j.as_object_mut().ok_or("Zotero 任务记录无效")?.remove("rows");
    Ok(j)
}
fn create_pending(root:&Path,c:&mut Connection,p:&str,j:&mut Value)->R<()>{
    let id=s(j,"id").to_string();valid_id(&id)?;
    let roots=j["selectedCollections"].as_array().cloned().unwrap_or_else(||vec![j["collection"].clone()]);
    let names=roots.iter().map(|v|if s(v,"name").is_empty(){s(v,"path").rsplit(" / ").next().unwrap_or("Zotero 导入")}else{s(v,"name")}).collect::<Vec<_>>();
    let name=names.join("、");
    let mut f=defaults();f["mode"]=json!("full");
    j["sourceId"]=json!(id);
    save(root,p,j)?;
    let tx=c.transaction().map_err(err)?;
    tx.execute("INSERT INTO queries(id,project,name,text,source) VALUES(?,?,?,'','zotero')",params![id,p,name]).map_err(err)?;
    put(&tx,&format!("queryFilters:{id}"),&f)?;
    tx.commit().map_err(err)?;Ok(())
}
pub(super) fn rpc(root:&Path,c:&mut Connection,p:&str,op:&str,a:&Value)->R<Value>{
    valid_id(p)?;
    match op {
        "status"=>status(root,p),
        "report"=>{
            valid_id(s(a,"id"))?;
            read(&project_dir(root,p)?.join(format!("metadata/zotero-imports/{}/report.json",s(a,"id"))))
        },
        "cancel"=>{
            let j=status(root,p)?;
            if j["id"]!=a["id"] {return Err("导入任务已变化，请刷新".into());}
            if ["queued","running"].contains(&s(&j,"state")) {
                write_file(&project_dir(root,p)?.join(format!("metadata/zotero-imports/{}/cancel",s(&j,"id"))),b"cancel")?;
            }
            Ok(j)
        },
        "start"=>{
            let _=status(root,p)?;
            let _lock=job_lock(root,p)?;
            let old=if location(root,p)?.exists(){read(&location(root,p)?)?}else{json!(null)};
            if ["queued","running"].contains(&s(&old,"state")) && now().saturating_sub(old["created"].as_u64().unwrap_or(0))<30 {return Err("Zotero 导入正在启动".into());}
            // Serialize against preparation/cleanup starts, then publish ownership before spawning.
            let operations=OpenOptions::new().create(true).truncate(false).read(true).write(true).open(project_dir(root,p)?.join("metadata/library-operations.lock")).map_err(err)?;
            operations.try_lock_exclusive().map_err(|_|"项目任务正在启动，请稍后重试".to_string())?;
            download_rpc(root,"zotero.check",json!({"project":p}))?;
            valid_id(s(a,"preview"))?;
            let snapshot=read(&project_dir(root,p)?.join(format!("metadata/zotero-previews/{}.json",s(a,"preview"))))?;
            let id=uid();
            let dir=project_dir(root,p)?.join(format!("metadata/zotero-imports/{id}"));
            write_file(&dir.join("snapshot.json"),snapshot.to_string().as_bytes())?;
            let mut j=json!({"id":id,"state":"queued","stage":"准备 DOI 匹配","created":now(),"collection":snapshot["collection"],"selectedCollections":snapshot.get("selectedCollections").cloned().unwrap_or_else(||json!([snapshot["collection"]])),"total":snapshot["total"],"processed":0,"matched":0,"pdfImported":0,"pdfReused":0,"rows":[]});
            create_pending(root,c,p,&mut j)?;
            let log=File::create(dir.join("worker.log")).map_err(err)?;
            let mut command=Command::new(std::env::current_exe().map_err(err)?);
            command.args(["--zotero-worker",p,&id]).env("SCHOLARNOTELM_ROOT",root).current_dir(root).stdin(Stdio::null()).stdout(Stdio::from(log.try_clone().map_err(err)?)).stderr(Stdio::from(log));
            #[cfg(unix)] {use std::os::unix::process::CommandExt;command.process_group(0);}
            #[cfg(windows)] {use std::os::windows::process::CommandExt;command.creation_flags(0x08000200);}
            match command.spawn(){Ok(child)=>{
                let receipt=json!({"pid":child.id(),"jobId":id,"spawned":now(),"mode":"background"});
                write_file(&dir.join("spawn.json"),receipt.to_string().as_bytes())?;
                j["process"]=receipt;
                // Reap our child in a long-lived desktop host; CLI callers can use --wait.
                std::thread::spawn(move ||{let mut child=child;let _=child.wait();});
            },Err(e)=>{j["state"]=json!("failed");j["error"]=json!(e.to_string());save(root,p,&j)?;return Err(err(e));}}
            Ok(j)
        },
        "collections"|"preview"=>download_rpc(root,&format!("zotero.{op}"),a.clone()),
        _=>Err("未知 Zotero 来源操作".into())
    }
}
fn normalize_doi(value:&str)->String{
    let mut d=value.trim().to_lowercase();
    for prefix in ["https://doi.org/","http://doi.org/","https://dx.doi.org/","http://dx.doi.org/","doi:"]{if let Some(rest)=d.strip_prefix(prefix){d=rest.trim().into();break;}}d
}
fn resolve(root:&Path,c:&Connection,p:&str,dois:&[String],cancel:&Path,dir:&Path)->R<Vec<(String,Value,String)>>{
    let term=dois.iter().map(|d|format!("\"{d}\"[aid]")).collect::<Vec<_>>().join(" OR ");
    let result=search(root,c,&term,&defaults(),9999,Some(cancel))?;
    write_file(&dir.join("esearch.json"),result.to_string().as_bytes())?;
    let ids=result["ids"].as_array().ok_or("PubMed PMID 列表缺失")?.iter().map(|v|v.as_str().unwrap_or("").to_string()).collect::<Vec<_>>();
    if result["count"].as_u64()!=Some(ids.len() as u64) || ids.iter().any(|id|id.is_empty()||!id.chars().all(|c|c.is_ascii_digit())){return Err("PubMed 返回列表不完整，未将此批标为无匹配".into());}
    let mut articles=Vec::new();
    for (i,batch) in ids.chunks(100).enumerate(){
        let raw=ncbi(root,c,"efetch",vec![("db".into(),"pubmed".into()),("id".into(),batch.join(",")),("retmode".into(),"xml".into())],Some(cancel))?;
        let xml_path=pubmed_storage::save(root,p,raw.as_bytes())?;
        write_file(&dir.join(format!("efetch-{i}.json")),json!({"xmlPath":xml_path}).to_string().as_bytes())?;
        let parsed=parse_pubmed(&raw)?;
        let actual=parsed.iter().map(|v|v.0.clone()).collect::<HashSet<_>>();
        if parsed.len()!=batch.len() || actual!=batch.iter().cloned().collect(){return Err("PubMed XML 与请求 PMID 不一致".into());}
        articles.extend(parsed);
    }
    Ok(articles)
}
fn commit(root:&Path,c:&mut Connection,p:&str,j:&mut Value,articles:&[(String,Value,String)],cancel:&Path)->R<()>{
    let _lock=project_lock(root,p)?;check_query_cancel(Some(cancel))?;
    let id=s(j,"sourceId").to_string();valid_id(&id)?;let run=uid();
    let relative=pubmed_storage::save(root,p,pack_xml(&articles.iter().map(|v|v.2.clone()).collect::<Vec<_>>()).as_bytes())?;
    let mut f=defaults();f["mode"]=json!("full");
    let data=json!({"id":run,"revision":1,"created":now(),"count":articles.len(),"fetched":articles.len(),"truncated":false,"filters":f,"text":"Zotero 集合导入快照","xmlPath":relative,"zotero":{"job":j["id"],"collection":j["collection"],"selectedCollections":j["selectedCollections"]}});
    let tx=c.transaction().map_err(err)?;
    let updated=tx.execute("UPDATE queries SET active_run=? WHERE id=? AND project=? AND source='zotero' AND active_run IS NULL",params![run,id,p]).map_err(err)?;
    if updated!=1{return Err("导入来源已改变，无法保存 XML".into());}
    put(&tx,&format!("queryFilters:{id}"),&f)?;
    tx.execute("INSERT INTO runs VALUES(?,?,?,?,?)",params![run,id,1,now(),data.to_string()]).map_err(err)?;
    for (i,(pmid,v,xml)) in articles.iter().enumerate(){
        tx.execute("INSERT INTO articles VALUES(?,?,?) ON CONFLICT(pmid) DO NOTHING",params![pmid,v.to_string(),xml]).map_err(err)?;
        tx.execute("INSERT INTO members VALUES(?,?,?,?,?)",params![run,pmid,i,v.to_string(),xml]).map_err(err)?;
    }
    tx.commit().map_err(err)?;
    j["sourceId"]=json!(id);j["runId"]=json!(run);save(root,p,j)?;
    corpus(root,c,p)?;Ok(())
}
fn execute(root:&Path,p:&str,j:&mut Value)->R<()>{
    let dir=project_dir(root,p)?.join(format!("metadata/zotero-imports/{}",s(j,"id")));
    let snapshot=read(&dir.join("snapshot.json"))?;let cancel=dir.join("cancel");
    let mut c=db_project(root,p)?;
    if !j["sourceId"].is_string(){let _guard=project_lock(root,p)?;create_pending(root,&mut c,p,j)?;}
    check_query_cancel(Some(&cancel))?;
    let mut rows=snapshot["items"].as_array().ok_or("集合快照无效")?.clone();
    let mut dois=Vec::new();let mut seen=HashSet::new();
    for row in &mut rows{let doi=s(row,"doi").to_string();row["status"]=json!(if doi.is_empty(){"missing_doi"}else{"pending"});if !doi.is_empty()&&seen.insert(doi.clone()){dois.push(doi);}}
    j["state"]=json!("running");j["rows"]=json!(rows);save(root,p,j)?;
    let mut accepted=HashMap::new();
    for (batch_no,batch) in dois.chunks(50).enumerate(){
        j["stage"]=json!(format!("匹配 DOI：第 {} / {} 批",batch_no+1,dois.len().div_ceil(50)));save(root,p,j)?;
        let result=resolve(root,&c,p,batch,&cancel,&dir.join(format!("pubmed-batch-{batch_no}")));
        check_query_cancel(Some(&cancel))?;
        for doi in batch {
            let matches=result.as_ref().map(|articles|articles.iter().filter(|(_,v,_)|normalize_doi(s(v,"doi"))==*doi).collect::<Vec<_>>()).unwrap_or_default();
            let status=if result.is_err(){"request_failed"}else if matches.is_empty(){"unmatched"}else if matches.len()>1{"ambiguous"}else{"matched"};
            for row in rows.iter_mut().filter(|r|s(r,"doi")==doi){
                row["status"]=json!(status);row["pmids"]=json!(matches.iter().map(|v|&v.0).collect::<Vec<_>>());
                if let Err(ref error)=result{row["error"]=json!(error);}
            }
            if matches.len()==1{accepted.insert(matches[0].0.clone(),matches[0].clone());}
        }
        j["processed"]=json!(rows.iter().filter(|r|r["status"]!="pending").count());j["rows"]=json!(rows);save(root,p,j)?;
    }
    // Keep the pending source visible, but never publish XML after all requests fail.
    if rows.iter().any(|r|r["status"]=="request_failed") && accepted.is_empty(){return Err("PubMed 请求失败，未保存文献 XML。可重新导入；详情见报告。".into());}
    let mut articles=accepted.into_values().collect::<Vec<_>>();articles.sort_by(|a,b|a.0.cmp(&b.0));
    j["matched"]=json!(articles.len());j["stage"]=json!("保存 PubMed XML");save(root,p,j)?;
    commit(root,&mut c,p,j,&articles,&cancel)?;
    for (i,(pmid,v,_)) in articles.iter().enumerate(){
        check_query_cancel(Some(&cancel))?;
        j["stage"]=json!(format!("导入本地 PDF：{} / {}",i+1,articles.len()));save(root,p,j)?;
        let parents=rows.iter().filter(|r|r["status"]=="matched"&&r["pmids"][0]==*pmid).map(|r|r["key"].clone()).collect::<Vec<_>>();
        // Project lock serializes source toggles and PDF publication.
        let _guard=project_lock(root,p)?;
        let pdf=download_rpc(root,"zotero.pdf",json!({"project":p,"job":j["id"],"pmid":pmid,"doi":normalize_doi(s(v,"doi")),"parents":parents,"address":snapshot["address"]})).unwrap_or_else(|e|json!({"state":"failed","message":e}));
        for row in rows.iter_mut().filter(|r|r["status"]=="matched"&&r["pmids"][0]==*pmid){row["pdf"]=pdf.clone();}
        if pdf["state"]=="imported"{j["pdfImported"]=json!(j["pdfImported"].as_u64().unwrap_or(0)+1);}
        if pdf["state"]=="reused"{j["pdfReused"]=json!(j["pdfReused"].as_u64().unwrap_or(0)+1);}
        j["rows"]=json!(rows);save(root,p,j)?;
    }
    check_query_cancel(Some(&cancel))?;
    let partial=rows.iter().any(|r|["request_failed","unmatched","ambiguous"].contains(&s(r,"status")) || ["failed","conflict"].contains(&s(&r["pdf"],"state")));
    j["processed"]=json!(rows.len());j["state"]=json!(if partial{"partial"}else{"completed"});j["stage"]=json!(if partial{"部分完成，请查看导入报告"}else{"导入完成"});Ok(())
}
fn begin_attempt(j:&mut Value){
    if !s(j,"error").is_empty(){
        let previous=json!({"started":j.get("started").unwrap_or(&j["created"]),"finished":j["finished"],"state":j["state"],"error":j["error"],"pid":j["pid"]});
        if !j["attempts"].is_array(){j["attempts"]=json!([]);}
        j["attempts"].as_array_mut().unwrap().push(previous);
    }
    j["error"]=json!("");j["reportWarning"]=json!("");
    j.as_object_mut().unwrap().remove("finished");
    j["started"]=json!(now());j["pid"]=json!(std::process::id());
    for key in ["processed","matched","pdfImported","pdfReused"]{j[key]=json!(0);}
    j["state"]=json!("running");j["stage"]=json!("准备 DOI 匹配");
}
/// Returns true when invoked as the detached import worker (both CLI and desktop).
pub fn worker_entry(root:&Path)->bool{
    let args=std::env::args().collect::<Vec<_>>();
    if args.get(1).map(String::as_str)!=Some("--zotero-worker"){return false;}
    let work=||->R<()>{
        let p=args.get(2).ok_or("缺少项目")?;let id=args.get(3).ok_or("缺少任务")?;valid_id(p)?;valid_id(id)?;
        let _storage=storage_lock(root,false)?;
        // Parent holds the import lock until spawn returns.
        let deadline=SystemTime::now()+Duration::from_secs(10);
        let _lock=loop{match job_lock(root,p){Ok(lock)=>break lock,Err(e)=>{if SystemTime::now()>deadline{return Err(e);}std::thread::sleep(Duration::from_millis(50));}}};
        let mut j=read(&location(root,p)?)?;if s(&j,"id")!=id{return Err("任务已改变".into());}
        if j["runId"].is_string(){return Err("此任务已发布文献 XML，不能重新执行；请重新导入以创建独立来源".into());}
        begin_attempt(&mut j);save(root,p,&j)?;
        write_file(&project_dir(root,p)?.join(format!("metadata/zotero-imports/{id}/process.json")),json!({"pid":std::process::id(),"jobId":id,"started":j["started"],"mode":"worker"}).to_string().as_bytes())?;
        if let Err(e)=execute(root,p,&mut j){
            let cancelled=project_dir(root,p)?.join(format!("metadata/zotero-imports/{id}/cancel")).exists();
            j["state"]=json!(if cancelled{"cancelled"}else{"failed"});j["stage"]=json!(if cancelled{"导入已取消"}else{"导入失败"});j["error"]=json!(e);
        }
        if j["runId"].is_string(){
            if let Err(e)=download_rpc(root,"zotero.finish",json!({"project":p})){j["reportWarning"]=json!(e);}
        }
        j["finished"]=json!(now());save(root,p,&j)
    };
    if let Err(e)=work(){eprintln!("{e}");}true
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn retry_clears_current_error_but_preserves_attempt(){
        let mut j=json!({"id":"retry","created":1,"started":2,"finished":3,"pid":123,"state":"interrupted","error":"old failure","reportWarning":"old warning","matched":4});
        begin_attempt(&mut j);
        assert_eq!(j["error"],"");assert_eq!(j["reportWarning"],"");assert!(j.get("finished").is_none());
        assert_eq!(j["attempts"][0]["error"],"old failure");assert_eq!(j["attempts"][0]["pid"],123);
        assert_eq!(j["matched"],0);assert_eq!(j["state"],"running");
        begin_attempt(&mut j);assert_eq!(j["attempts"].as_array().unwrap().len(),1);
    }
    fn setup()->PathBuf{
        let root=std::env::temp_dir().join(format!("scholar-zotero-{}-{}",std::thread::current().name().unwrap_or("test").replace("::","-"),uid()));
        db_project(&root,"test").unwrap();root
    }
    #[test]
    fn status_preserves_live_ownership_and_heals_completed_error_once(){
        let root=setup();let mut j=json!({"id":"receipt","state":"running","created":now()-60,"started":now()-60});
        save(&root,"test",&j).unwrap();
        let lock=job_lock(&root,"test").unwrap();
        assert_eq!(status(&root,"test").unwrap()["state"],"running");drop(lock);
        assert_eq!(status(&root,"test").unwrap()["state"],"interrupted");
        j["started"]=json!(now());save(&root,"test",&j).unwrap();
        assert_eq!(status(&root,"test").unwrap()["state"],"running");
        j["state"]=json!("completed");j["error"]=json!("previous interruption");save(&root,"test",&j).unwrap();
        let fixed=status(&root,"test").unwrap();assert_eq!(fixed["error"],"");
        assert_eq!(fixed["attempts"][0]["error"],"previous interruption");
        assert_eq!(status(&root,"test").unwrap()["attempts"].as_array().unwrap().len(),1);
        fs::remove_dir_all(root).unwrap();
    }
    fn xml(id:&str,doi:&str)->String{format!("<PubmedArticle><MedlineCitation><PMID>{id}</PMID><Article><ArticleTitle>No abstract {id}</ArticleTitle></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType=\"doi\">{doi}</ArticleId></ArticleIdList><ReferenceList><Reference><ArticleIdList><ArticleId IdType=\"doi\">10.1234/cited</ArticleId></ArticleIdList></Reference></ReferenceList></PubmedData></PubmedArticle>")}
    fn fixture(root:&Path){
        let body=pack_xml(&[xml("1","10.1234/a(b)"),xml("2","10.1234/ambiguous"),xml("3","10.1234/ambiguous")]);
        write_file(&root.join("ncbi-fixture.json"),json!({"responses":[{"endpoint":"esearch","term":"\"10.1234/a(b)\"[aid] OR \"10.1234/ambiguous\"[aid] OR \"10.1234/cited\"[aid]","body":json!({"esearchresult":{"count":"3","idlist":["1","2","3"]}}).to_string()},{"endpoint":"efetch","body":body}]}).to_string().as_bytes()).unwrap();
    }
    fn snapshot(root:&Path,id:&str)->Value{
        let snapshot=json!({"collection":{"key":"COLLECT1","path":"Parent / Child"},"address":"localhost:23119","items":[{"key":"PARENT01","doi":"10.1234/a(b)"},{"key":"PARENT02","doi":"10.1234/a(b)"},{"key":"PARENT03","doi":"10.1234/ambiguous"},{"key":"PARENT04","doi":"10.1234/cited"},{"key":"PARENT05","doi":""}]});
        write_file(&project_dir(root,"test").unwrap().join(format!("metadata/zotero-imports/{id}/snapshot.json")),snapshot.to_string().as_bytes()).unwrap();
        json!({"id":id,"created":now(),"state":"queued","stage":"准备 DOI 匹配","collection":snapshot["collection"],"total":5,"rows":[],"matched":0,"pdfImported":0,"pdfReused":0})
    }
    #[test]
    fn import_snapshots_exact_mapping_dedup_and_no_abstract_filters(){
        let root=setup();let mut first=Value::Null;
        for id in ["first","second"]{
            fixture(&root);let mut job=snapshot(&root,id);
            job["selectedCollections"]=json!([{"key":"COLLECT1","path":"Parent / Child"},{"key":"OUTSIDE1","path":"Other branch"}]);
            execute(&root,"test",&mut job).unwrap();save(&root,"test",&job).unwrap();
            assert_eq!(job["state"],"partial");assert_eq!(job["matched"],1);
            assert_eq!(job["rows"][2]["status"],"ambiguous");assert_eq!(job["rows"][3]["status"],"unmatched");assert_eq!(job["rows"][4]["status"],"missing_doi");
            assert!(job["rows"][2]["pdf"].is_null());if id=="first"{first=job;}
        }
        let mut c=db_project(&root,"test").unwrap();let w=workspace(&root,&c,"test").unwrap();
        assert_eq!(w["queries"].as_array().unwrap().len(),2);assert_eq!(w["corpus"]["included"],1);
        assert_eq!(w["queries"][0]["run"]["zotero"]["selectedCollections"][1]["path"],"Other branch");
        assert_eq!(w["corpus"]["papers"][0]["sources"].as_array().unwrap().len(),2);assert_eq!(w["queries"][0]["stale"],false);
        assert!(run_query(&root,&mut c,"test",s(&first,"sourceId"),None,true).unwrap_err().contains("快照"));
        let saved=dispatch(&root,json!({"action":"query.save","args":{"project":"test","id":first["sourceId"],"name":"Renamed","text":"malicious[tiab]","filters":{"jcr":true}}})).unwrap();
        assert_eq!(saved["queries"][0]["text"],"");assert_eq!(saved["queries"][0]["name"],"Renamed");assert_eq!(saved["corpus"]["included"],1);
        let batch=dispatch(&root,json!({"action":"query.filters.apply","args":{"project":"test","dates":{"start":"2026-01-01","end":"2026-02-01"}}})).unwrap();
        assert_eq!(batch["queries"][0]["filters"]["start"],"");
        let exclusions=read(&project_dir(&root,"test").unwrap().join("metadata/abstract-exclusions.json")).unwrap();assert_eq!(exclusions,json!([]));
        drop(c);fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn incomplete_fetch_is_failure_not_unmatched(){
        let root=setup();let mut j=snapshot(&root,"bad");
        write_file(&root.join("ncbi-fixture.json"),json!({"responses":[{"endpoint":"esearch","term":"\"10.1234/a(b)\"[aid] OR \"10.1234/ambiguous\"[aid] OR \"10.1234/cited\"[aid]","body":json!({"esearchresult":{"count":"4","idlist":["1"]}}).to_string()}]}).to_string().as_bytes()).unwrap();
        assert!(execute(&root,"test",&mut j).is_err());assert_eq!(j["rows"][0]["status"],"request_failed");
        let w=workspace(&root,&db_project(&root,"test").unwrap(),"test").unwrap();
        assert_eq!(w["queries"].as_array().unwrap().len(),1);assert!(w["queries"][0]["run"].is_null());assert_eq!(w["corpus"]["included"],0);fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn cancelled_before_commit_preserves_pending_source_without_xml(){
        let root=setup();let mut j=snapshot(&root,"cancelled");
        write_file(&project_dir(&root,"test").unwrap().join("metadata/zotero-imports/cancelled/cancel"),b"cancel").unwrap();
        assert!(execute(&root,"test",&mut j).is_err());
        let w=workspace(&root,&db_project(&root,"test").unwrap(),"test").unwrap();
        assert_eq!(w["queries"].as_array().unwrap().len(),1);assert!(w["queries"][0]["run"].is_null());assert_eq!(w["corpus"]["included"],0);fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn pending_source_is_immediate_and_commit_updates_same_row(){
        let root=setup();let mut c=db_project(&root,"test").unwrap();let mut j=snapshot(&root,"pending");
        create_pending(&root,&mut c,"test",&mut j).unwrap();
        let w=workspace(&root,&c,"test").unwrap();
        assert_eq!(w["queries"].as_array().unwrap().len(),1);assert_eq!(w["queries"][0]["name"],"Child");
        assert_eq!(w["queries"][0]["zoteroJob"]["state"],"queued");assert!(w["queries"][0]["run"].is_null());assert_eq!(w["corpus"]["included"],0);
        fixture(&root);execute(&root,"test",&mut j).unwrap();save(&root,"test",&j).unwrap();
        let w=workspace(&root,&c,"test").unwrap();assert_eq!(w["queries"].as_array().unwrap().len(),1);
        assert_eq!(w["queries"][0]["id"],"pending");assert_eq!(w["queries"][0]["xmlExists"],true);assert_eq!(w["corpus"]["included"],1);
        drop(c);fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn source_ownership_blocks_both_directions_but_allows_reads_and_other_projects(){
        let root=setup();let mut c=db_project(&root,"test").unwrap();let mut j=snapshot(&root,"locked");
        // Simulate the ownership held by query.run for its entire execution.
        let owner=source_operation(&root,"test").unwrap();
        assert!(dispatch(&root,json!({"action":"zotero.start","args":{"project":"test"}})).unwrap_err().contains("文献来源任务正在执行"));
        drop(owner);create_pending(&root,&mut c,"test",&mut j).unwrap();
        for action in ["query.run","query.save","query.create","query.filters.apply","query.toggle","query.archive","xml.import","zotero.start"]{
            assert!(dispatch(&root,json!({"action":action,"args":{"project":"test"}})).unwrap_err().contains("Zotero 导入正在运行"),"{action}");
        }
        assert!(dispatch(&root,json!({"action":"workspace","args":{"project":"test"}})).is_ok());
        assert!(dispatch(&root,json!({"action":"xml.export","args":{"project":"test"}})).is_ok());
        assert!(dispatch(&root,json!({"action":"query.create","args":{"project":"other"}})).is_ok());
        j["state"]=json!("cancelled");save(&root,"test",&j).unwrap();
        assert!(dispatch(&root,json!({"action":"query.create","args":{"project":"test"}})).is_ok());
        drop(c);fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn orphaned_job_recovers_without_leaving_sources_locked(){
        let root=setup();let mut c=db_project(&root,"test").unwrap();let mut j=snapshot(&root,"orphan");
        j["created"]=json!(now()-60);create_pending(&root,&mut c,"test",&mut j).unwrap();
        let lock=source_operation(&root,"test").unwrap();
        let w=workspace(&root,&c,"test").unwrap();assert_eq!(w["sourceBusy"],false);
        assert_eq!(w["queries"][0]["zoteroJob"]["state"],"interrupted");assert_eq!(w["corpus"]["included"],0);
        drop(lock);drop(c);fs::remove_dir_all(root).unwrap();
    }

}

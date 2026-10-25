//! Optional providers: registration/configuration and a cancellable private pipe.
//! No supplier-specific protocol or header constants belong in this module.
use super::{s,err,R};
use serde_json::{json,Value};
use std::{fs,io::{BufRead,BufReader,Write},path::Path,process::{Command,Stdio,Child},time::Duration};

pub fn id(profile:&Value)->&str {match s(profile,"provider") {""=>"openai",id=>id}}
pub fn thinking_catalog(root:&Path)->Vec<Value> {
    fs::read(root.join("services/downloader/thinking_presets.json")).ok()
        .and_then(|b|serde_json::from_slice(&b).ok()).unwrap_or_default()
}
pub fn needs_worker(profile:&Value)->bool {
    id(profile)!="openai" || profile["thinkingByModel"].get(s(profile,"model")).is_some()
}
fn validate_thinking(root:&Path,profile:&Value)->R<()> {
    if id(profile)!="openai" {return Ok(());}
    if let Some(settings)=profile.get("thinkingByModel") {
        let presets=thinking_catalog(root);
        for (_,selected) in settings.as_object().ok_or("模型思考预设格式无效")? {
            let preset=presets.iter().find(|p|p["id"]==selected["preset"] && selected["preset"].is_string()).ok_or("模型思考预设无效，请重新选择")?;
            let level=selected.get("level").unwrap_or(&preset["defaultLevel"]);
            if !preset["levels"].as_array().is_some_and(|levels|levels.contains(level)) {
                return Err("此思考预设不支持所选档位，请重新选择".into());
            }
        }
    }
    Ok(())
}
pub fn catalog(root:&Path)->Vec<Value> {
    let folder=root.join("services/llm_providers");
    let registered:Value=fs::read(folder.join("registry.json")).ok().and_then(|b|serde_json::from_slice(&b).ok()).unwrap_or(json!({}));
    registered["providers"].as_array().map(|ids|ids.iter().filter_map(|v| {
        let id=v.as_str()?;
        if id.is_empty() || !id.bytes().all(|b|b.is_ascii_lowercase()||b.is_ascii_digit()||b==b'_'){return None;}
        let path=folder.join(id);
        if !path.join("adapter.py").is_file(){return None;}
        let manifest:Value=serde_json::from_slice(&fs::read(path.join("manifest.json")).ok()?).ok()?;
        (manifest["id"]==id).then_some(manifest)
    }).collect()).unwrap_or_default()
}
pub fn manifest(root:&Path,profile:&Value)->R<Option<Value>> {
    if id(profile)=="openai" {return Ok(None);}
    catalog(root).into_iter().find(|v|s(v,"id")==id(profile)).map(Some).ok_or_else(||"此模型供应商已停用或未安装，请选择其他模型配置".into())
}
pub fn validate(root:&Path,profile:&Value)->R<Option<Value>> {
    validate_thinking(root,profile)?;
    let meta=manifest(root,profile)?;
    if let Some(ref m)=meta {
        if s(profile,"baseUrl").trim().trim_end_matches('/')!=s(m,"baseUrl") {return Err("此供应商使用固定的官方地址，请从供应商面板重新创建配置".into());}
        if !s(profile,"model").is_empty() && m["models"].get(s(profile,"model")).is_none() {return Err("供应商尚未收录此模型的官方端点，请更新供应商模块".into());}
        if let Some(models)=profile["models"].as_array() {
            if models.iter().any(|v|v.as_str().is_none_or(|id|m["models"].get(id).is_none())) {return Err("供应商尚未收录此模型的官方端点，请更新供应商模块".into());}
        }
        if let Some(settings)=profile.get("reasoningByModel") {
            let settings=settings.as_object().ok_or("模型思考强度配置格式无效")?;
            for (model,level) in settings {
                let level=level.as_str().ok_or("模型思考强度配置格式无效")?;
                if !level.is_empty() && m["models"][model]["reasoning"]["options"].get(level).is_none() {
                    return Err("此模型不支持所选思考强度，请重新选择".into());
                }
                if level=="budget" {
                    let spec=&m["models"][model]["reasoning"]["budget"];
                    let value=profile["reasoningBudgetByModel"][model].as_u64().ok_or("请填写此模型支持的正整数思考 token 预算")?;
                    if spec.is_null() || value<spec["min"].as_u64().unwrap_or(1) || spec["max"].as_u64().is_some_and(|max|value>max) {
                        return Err("请填写此模型支持的正整数思考 token 预算".into());
                    }
                }
            }
        }
    }
    Ok(meta)
}

pub fn prepare_save(root:&Path,profile:&mut Value,profiles:&Value)->R<()> {
    if let Some(meta)=manifest(root,profile)? {
        if meta["singleProfile"]==true {
            if profiles.as_array().is_some_and(|items|items.iter().any(|p|id(p)==id(profile)&&p["id"]!=profile["id"])) {
                return Err("此供应商只允许一个配置，请编辑已有配置".into());
            }
            profile["name"]=meta["name"].clone();
        }
    }
    Ok(())
}

pub fn name_conflict(a:&Value,b:&Value)->bool {
    if a["id"]==b["id"] || s(a,"name").to_lowercase()!=s(b,"name").to_lowercase(){return false;}
    // Dedicated providers have a fixed name. A legacy ordinary profile may
    // already use it; preserve that profile and its references unchanged.
    // Scope names by explicit provider even after its module has been removed.
    if id(a)!=id(b){return false;}
    true
}
struct Worker(Child);
impl Drop for Worker {fn drop(&mut self){let _=self.0.kill();let _=self.0.wait();}}

pub fn stream(root:&Path,profile:&Value,messages:Value,session:Value,emit:&mut dyn FnMut(&str,&str)->R<bool>)->R<()> {
    validate(root,profile)?;
    let mut command=Command::new(root.join(if cfg!(windows){"runtimes/downloader/Scripts/python.exe"}else{"runtimes/downloader/bin/python"}));
    command.arg(root.join("services/downloader/llm_provider_worker.py")).current_dir(root)
        .env("SCHOLARNOTELM_ROOT",root).env("PYTHONUTF8","1").env("PYTHONDONTWRITEBYTECODE","1")
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(windows)] {use std::os::windows::process::CommandExt;command.creation_flags(0x08000000);}
    let mut worker=Worker(command.spawn().map_err(|_|"无法启动模型供应商进程，请检查 downloader 运行时")?);
    worker.0.stdin.take().ok_or("供应商输入不可用")?.write_all(json!({"profile":profile,"messages":messages,"session":session}).to_string().as_bytes()).map_err(err)?;
    let stdout=worker.0.stdout.take().ok_or("供应商输出不可用")?;
    let (tx,rx)=std::sync::mpsc::sync_channel(16);
    std::thread::spawn(move|| {for line in BufReader::new(stdout).lines() {if tx.send(line).is_err(){break;}}});
    loop {
        match rx.recv_timeout(Duration::from_millis(150)) {
            Ok(Ok(line))=>{
                let value:Value=serde_json::from_str(&line).map_err(|_|"供应商进程返回了无效数据")?;
                match s(&value,"type") {
                    "done"=>return Ok(()),
                    "error"=>return Err(s(&value,"error").to_string()),
                    "delta"=>if !emit(s(&value,"text"),s(&value,"reasoning"))?{return Ok(());},
                    _=>return Err("供应商进程返回了未知状态".into()),
                }
            },
            Ok(Err(_))=>return Err("读取供应商进程失败".into()),
            Err(std::sync::mpsc::RecvTimeoutError::Timeout)=>{if !emit("","")?{return Ok(());}},
            Err(_)=>return Err("供应商进程提前结束，未收到完成状态".into()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn removed_provider_never_intercepts_default_profiles() {
        let root=std::env::temp_dir().join(format!("scholarnotelm-provider-{}",super::super::uid()));
        let dir=root.join("services/llm_providers");fs::create_dir_all(dir.join("fixture")).unwrap();
        fs::write(dir.join("registry.json"),r#"{"providers":["fixture"]}"#).unwrap();
        fs::write(dir.join("fixture/manifest.json"),r#"{"id":"fixture","baseUrl":"https://fixture.invalid/v1","models":{"m":{"protocol":"chat"}}}"#).unwrap();
        fs::write(dir.join("fixture/adapter.py"),"# installed fixture").unwrap();
        let profile=json!({"provider":"fixture","baseUrl":"https://fixture.invalid/v1","model":"m","models":["m"]});
        assert!(validate(&root,&profile).unwrap().is_some());
        assert!(validate(&root,&json!({"name":"fixture","baseUrl":"https://ordinary.invalid/v1"})).unwrap().is_none());
        assert!(validate(&root,&json!({"provider":"fixture","baseUrl":"https://wrong.invalid/v1","model":"m"})).is_err());
        fs::remove_dir_all(dir.join("fixture")).unwrap();
        assert!(catalog(&root).is_empty());assert!(validate(&root,&profile).is_err());
        assert!(validate(&root,&json!({"provider":"openai","model":"any"})).unwrap().is_none());
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn singleton_name_and_model_effort_are_enforced_only_for_registered_providers() {
        let root=std::env::temp_dir().join(format!("scholarnotelm-provider-{}",super::super::uid()));
        let dir=root.join("services/llm_providers");fs::create_dir_all(dir.join("fixture")).unwrap();
        fs::write(dir.join("registry.json"),r#"{"providers":["fixture"]}"#).unwrap();
        fs::write(dir.join("fixture/adapter.py"),"# fixture").unwrap();
        fs::write(dir.join("fixture/manifest.json"),r#"{"id":"fixture","name":"fixed_name","singleProfile":true,"baseUrl":"https://fixture.invalid/v1","models":{"a":{"reasoning":{"options":{"low":{},"max":{}}}},"b":{"reasoning":{"options":{"low":{},"medium":{},"high":{}}}}}}"#).unwrap();
        let mut p=json!({"id":"go","provider":"fixture","name":"custom","baseUrl":"https://fixture.invalid/v1","model":"a","reasoningByModel":{"a":"max","b":"medium"}});
        assert!(validate(&root,&p).is_ok());prepare_save(&root,&mut p,&json!([])).unwrap();assert_eq!(p["name"],"fixed_name");
        let profiles=json!([p]);let mut duplicate=p.clone();duplicate["id"]=json!("second");
        assert!(prepare_save(&root,&mut duplicate,&profiles).is_err());assert!(prepare_save(&root,&mut p,&profiles).is_ok());
        p["reasoningByModel"]["a"]=json!("medium");assert!(validate(&root,&p).is_err());
        p["reasoningByModel"]=json!({"b":42});assert!(validate(&root,&p).is_err());
        let ordinary=json!({"id":"normal","name":"fixed_name","model":"a","reasoningByModel":{"a":"anything"}});
        assert!(validate(&root,&ordinary).is_ok());assert!(!name_conflict(&ordinary,&p));
        assert!(name_conflict(&ordinary,&json!({"id":"other","name":"FIXED_NAME"})));
        fs::remove_dir_all(root).unwrap();
        assert!(!name_conflict(&ordinary,&p));
    }
}

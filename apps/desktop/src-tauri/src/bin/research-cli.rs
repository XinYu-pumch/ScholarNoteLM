#[path = "../research.rs"]
mod research;
use std::io::{Read, Write};
fn main() {
    let root = std::path::PathBuf::from(
        std::env::var("SCHOLARNOTELM_ROOT").expect("SCHOLARNOTELM_ROOT required"),
    );
    if research::zotero_worker_entry(&root) {return;}
    if std::env::args().any(|a| a == "--auto-mesh") {
        research::auto_mesh(&root);
        return;
    }
    let mut input = String::new();
    std::io::stdin()
        .take(50_000_000)
        .read_to_string(&mut input)
        .unwrap();
    let streaming = std::env::args().any(|a| a == "--stream");
    let wait = std::env::args().any(|a| a == "--wait");
    let result = serde_json::from_str::<serde_json::Value>(&input)
        .map_err(|e| e.to_string())
        .and_then(|v| {
            if wait {
                if streaming || v["action"]!="zotero.start" {return Err("--wait 仅用于非流式 zotero.start".into());}
                let project=v["args"]["project"].as_str().ok_or("缺少项目")?.to_string();
                let started=research::dispatch(&root,v)?;
                return research::wait_for_zotero_job(&root,&project,started["id"].as_str().ok_or("缺少任务 ID")?);
            }
            if streaming {
                research::stream_dispatch(&root, v, |event| {
                    let mut out = std::io::stdout().lock();
                    writeln!(out, "{}", event).map_err(|e| e.to_string())?;
                    out.flush().map_err(|e| e.to_string())
                })
            } else {
                research::dispatch(&root, v)
            }
        });
    let output = match result {
        Ok(v) => serde_json::json!({"ok":true,"data":v,"type":"done"}),
        Err(e) => serde_json::json!({"ok":false,"error":e,"type":"done"}),
    };
    println!("{}", output);
}

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{fs, path::PathBuf};
use tauri::Manager;
mod research;

#[tauri::command]
async fn research_rpc(
    request: serde_json::Value,
    workspace: tauri::State<'_, Workspace>,
) -> Result<serde_json::Value, String> {
    let root = workspace.root.clone();
    tauri::async_runtime::spawn_blocking(move || research::dispatch(&root, request))
        .await
        .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn research_stream(
    request: serde_json::Value,
    channel: tauri::ipc::Channel<serde_json::Value>,
    workspace: tauri::State<'_, Workspace>,
) -> Result<serde_json::Value, String> {
    let root = workspace.root.clone();
    tauri::async_runtime::spawn_blocking(move || {
        research::stream_dispatch(&root, request, |event| {
            channel.send(event).map_err(|e| e.to_string())
        })
    })
    .await
    .map_err(|e| e.to_string())?
}

struct Workspace {
    root: PathBuf,
}

fn workspace_root() -> Result<PathBuf, String> {
    if let Ok(path) = std::env::var("SCHOLARNOTELM_ROOT") {
        let root = PathBuf::from(path);
        if root.join("PROJECT_PLAN.md").is_file() {
            return Ok(root);
        }
        return Err("SCHOLARNOTELM_ROOT must point to the ScholarNoteLM folder".into());
    }
    let starts = [
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(PathBuf::from)),
        std::env::current_dir().ok(),
    ];
    for start in starts.into_iter().flatten() {
        for parent in start.ancestors() {
            if parent.join("PROJECT_PLAN.md").is_file() {
                return Ok(parent.to_path_buf());
            }
        }
    }
    Err("Keep this preview inside the ScholarNoteLM folder, or set SCHOLARNOTELM_ROOT".into())
}

fn main() {
    if std::env::args().any(|a|a=="--zotero-worker") {
        if let Ok(root)=workspace_root(){research::zotero_worker_entry(&root);}
        return;
    }
    tauri::Builder::default()
        .setup(|app| {
            let root = workspace_root().map_err(std::io::Error::other)?;
            let webview_dir = root.join("cache/webview");
            fs::create_dir_all(&webview_dir)?;
            let update_root = root.clone();
            std::thread::spawn(move || loop {
                research::auto_mesh(&update_root);
                std::thread::sleep(std::time::Duration::from_secs(3600));
            });
            app.manage(Workspace {
                root,
            });
            tauri::WebviewWindowBuilder::from_config(app, &app.config().app.windows[0])?
                .data_directory(webview_dir)
                .title(if std::env::var("SCHOLARNOTELM_DEV").as_deref() == Ok("1") { "ScholarNoteLM · 开发版" } else { "ScholarNoteLM" })
                .build()?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            research_rpc,
            research_stream
        ])
        .run(tauri::generate_context!())
        .expect("Unable to launch ScholarNoteLM");
}

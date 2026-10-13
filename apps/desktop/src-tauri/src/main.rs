#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{fs, path::PathBuf};
use tauri::{Manager, Emitter};
use std::sync::Mutex;
mod exit_guard;
#[cfg(target_os = "macos")]
mod macos_exit;
use exit_guard::ExitGuard;
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

// The Python engine is required at runtime, so its entry point marks the app root.
// (A documentation file was used before and broke startup when docs were reorganised.)
fn is_app_root(path: &std::path::Path) -> bool {
    path.join("services/downloader/engine.py").is_file()
}

fn workspace_root() -> Result<PathBuf, String> {
    if let Ok(path) = std::env::var("SCHOLARNOTELM_ROOT") {
        let root = PathBuf::from(path);
        if is_app_root(&root) {
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
            if is_app_root(parent) {
                return Ok(parent.to_path_buf());
            }
        }
    }
    Err("Keep this preview inside the ScholarNoteLM folder, or set SCHOLARNOTELM_ROOT".into())
}

#[tauri::command]
fn close_guard_ready(state: tauri::State<'_, Mutex<ExitGuard>>, ready: bool) {
    state.lock().unwrap().reset(ready);
}

#[tauri::command]
fn close_guard_answer(app: tauri::AppHandle, state: tauri::State<'_, Mutex<ExitGuard>>, ticket: u64, allow: bool) {
    let approved = state.lock().unwrap().answer(ticket, allow);
    if approved { app.exit(0); }
}

fn request_guarded_exit(app: &tauri::AppHandle) {
    let ticket = app.state::<Mutex<ExitGuard>>().lock().unwrap().request();
    if let Some(ticket) = ticket {
        if let Some(window) = app.get_webview_window("main") { let _ = window.set_focus(); }
        if app.emit_to("main", "app-close-requested", ticket).is_err() {
            app.state::<Mutex<ExitGuard>>().lock().unwrap().answer(ticket, false);
        }
    }
}

fn main() {
    if std::env::args().any(|a|a=="--zotero-worker") {
        if let Ok(root)=workspace_root(){research::zotero_worker_entry(&root);}
        return;
    }
    let app = tauri::Builder::default()
        .manage(Mutex::new(ExitGuard::default()))
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if window.state::<Mutex<ExitGuard>>().lock().unwrap().intercept() {
                    api.prevent_close(); request_guarded_exit(window.app_handle());
                }
            }
        })
        .setup(|app| {
            #[cfg(target_os = "macos")]
            macos_exit::install(app.handle())?;
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
            research_stream,
            close_guard_ready,
            close_guard_answer
        ])
        .build(tauri::generate_context!())
        .expect("Unable to launch ScholarNoteLM");
    app.run(|app, event| {
        if let tauri::RunEvent::ExitRequested { api, .. } = event {
            if app.state::<Mutex<ExitGuard>>().lock().unwrap().intercept() {
                api.prevent_exit(); request_guarded_exit(app);
            }
        }
    });
}

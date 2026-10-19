//! Locate the source-install folder independently of Finder's working directory.
use std::{fs, path::{Path,PathBuf}};
use sha2::{Digest,Sha256};
use serde_json::Value;

const MANIFEST:&str=env!("SCHOLARNOTELM_SOURCE_MANIFEST");

fn validate(root:&Path, manifest:&str)->Result<(),String>{
    if !root.join("services/downloader/engine.py").is_file(){return Err("请选择包含 services 的 ScholarNoteLM 安装目录".into());}
    if manifest.is_empty(){return Ok(());}
    let value:Value=serde_json::from_str(manifest).map_err(|e|e.to_string())?;
    for (name,expected) in value["files"].as_object().ok_or("程序版本清单无效")? {
        let path=Path::new(name);
        if path.is_absolute() || path.components().any(|c|matches!(c,std::path::Component::ParentDir)){return Err("程序版本清单路径无效".into());}
        let bytes=fs::read(root.join(path)).map_err(|_|format!("安装目录缺少文件：{name}"))?;
        if format!("{:x}",Sha256::digest(bytes))!=expected.as_str().unwrap_or(""){
            return Err(format!("源码与预编译程序版本不匹配：{name}。请使用同一 Release 的源码和 app。"));
        }
    }
    Ok(())
}

pub fn resolve()->Result<PathBuf,String>{
    let manifest=if cfg!(debug_assertions){""}else{MANIFEST};
    if let Ok(path)=std::env::var("SCHOLARNOTELM_ROOT"){
        let root=PathBuf::from(path);validate(&root,manifest)?;return Ok(root);
    }
    if let Ok(exe)=std::env::current_exe(){
        for root in exe.ancestors().skip(1){
            // A nearby installation must match; do not silently open another copy's data.
            if root.join("services/downloader/engine.py").is_file(){validate(root,manifest)?;return Ok(root.to_path_buf());}
        }
    }
    // Use the platform's per-user installation registry when the executable is moved.
    let registry = if cfg!(windows) {
        std::env::var_os("LOCALAPPDATA").map(|p|PathBuf::from(p).join("ScholarNoteLM/installations.json"))
    } else {
        std::env::var_os("HOME").map(|p|PathBuf::from(p).join("Library/Application Support/ScholarNoteLM/installations.json"))
    };
    if let Some(file)=registry{
        if let Ok(bytes)=fs::read(file){
            if let Ok(paths)=serde_json::from_slice::<Vec<PathBuf>>(&bytes){
                let matches:Vec<_>=paths.into_iter().filter(|p|validate(p,manifest).is_ok()).collect();
                if matches.len()==1{return Ok(matches[0].clone());}
            }
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let script = "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description='Select ScholarNoteLM installation (services, runtimes, models)'; if($d.ShowDialog() -eq 'OK'){[Console]::Write($d.SelectedPath)}";
        let output=std::process::Command::new("powershell.exe").args(["-NoProfile","-STA","-Command",script]).creation_flags(0x08000000).output().map_err(|e|e.to_string())?;
        if output.status.success() && !output.stdout.is_empty(){
            let root=PathBuf::from(String::from_utf8_lossy(&output.stdout).trim());
            validate(&root,manifest)?;return Ok(root);
        }
    }
    #[cfg(target_os="macos")]
    {
        let output=std::process::Command::new("/usr/bin/osascript").args(["-e","POSIX path of (choose folder with prompt \"选择 ScholarNoteLM 安装目录（包含 services、runtimes 和 models；不是研究工作目录）\")"]).output().map_err(|e|e.to_string())?;
        if output.status.success(){let root=PathBuf::from(String::from_utf8_lossy(&output.stdout).trim());validate(&root,manifest)?;return Ok(root);}
    }
    Err(if cfg!(windows){"未找到安装目录。请将 ScholarNoteLM.exe 放入匹配的源码目录，并运行install-environment.cmd。"}else{"未找到安装目录。请将 app 放入匹配的 ScholarNoteLM 源码目录，并运行install-environment.command。"}.into())
}

pub fn check_runtime(root:&Path)->Result<(),String>{
    #[cfg(windows)]
    for name in ["downloader","marker","retrieval"] {
        let directory=root.join("runtimes").join(name);
        let config=fs::read_to_string(directory.join("pyvenv.cfg")).unwrap_or_default();
        let home=config.lines().find_map(|line|line.strip_prefix("home = "));
        if !directory.join("Scripts/python.exe").is_file() || !home.is_some_and(|p|Path::new(p).join("python.exe").is_file()){
            return Err("运行环境缺失或安装目录已移动。请在当前源码目录重新运行install-environment.cmd，然后启动程序。".into());
        }
    }
    let _=root;
    Ok(())
}

pub fn show_error(message:&str){
    eprintln!("{message}");
    #[cfg(windows)]
    {
        #[link(name="user32")]
        extern "system" { fn MessageBoxW(window:*mut std::ffi::c_void,text:*const u16,title:*const u16,kind:u32)->i32; }
        let text:Vec<u16>=message.encode_utf16().chain(Some(0)).collect();
        let title:Vec<u16>="ScholarNoteLM 无法启动".encode_utf16().chain(Some(0)).collect();
        unsafe { MessageBoxW(std::ptr::null_mut(),text.as_ptr(),title.as_ptr(),0x10); }
    }
    #[cfg(target_os="macos")]
    {
        let script="on run argv\ndisplay alert \"ScholarNoteLM 无法启动\" message (item 1 of argv) as critical\nend run";
        let _=std::process::Command::new("/usr/bin/osascript").args(["-e",script,"--",message]).status();
    }
}

#[cfg(test)]
mod tests{
    use super::*;
    #[test]
    fn rejects_missing_or_mismatched_source(){
        let root=std::env::temp_dir().join(format!("scholarnotelm-root-test-{}",std::process::id()));
        fs::create_dir_all(root.join("services/downloader")).unwrap();
        fs::write(root.join("services/downloader/engine.py"),b"fixture").unwrap();
        assert!(validate(&root,"").is_ok());
        assert!(validate(&root,r#"{"files":{"services/downloader/engine.py":"wrong"}}"#).is_err());
        let hash=format!("{:x}",Sha256::digest(b"fixture"));
        assert!(validate(&root,&serde_json::json!({"files":{"services/downloader/engine.py":hash}}).to_string()).is_ok());
        assert!(validate(&root,r#"{"files":{"../outside":"bad"}}"#).is_err());
        fs::remove_dir_all(root).unwrap();
    }
}

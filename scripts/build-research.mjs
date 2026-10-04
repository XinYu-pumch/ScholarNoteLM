import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('..',import.meta.url));
const env={...process.env,CARGO_HOME:path.join(root,'cache/cargo'),RUSTUP_HOME:path.join(root,'runtimes/rust'),CARGO_TARGET_DIR:path.join(root,'cache/tauri-target'),TMPDIR:path.join(root,'tmp')};
const cargo=path.join(root,'cache/cargo/bin',process.platform==='win32'?'cargo.exe':'cargo');
const r=spawnSync(cargo,['build','--manifest-path',path.join(root,'apps/desktop/src-tauri/Cargo.toml'),'--bin','research-cli'],{cwd:root,env,stdio:'inherit'});process.exit(r.status??1);

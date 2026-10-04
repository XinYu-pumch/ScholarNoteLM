# ScholarNoteLM 开发版

日常修改使用根目录的 `开发启动 ScholarNoteLM.command`。这是 Tauri dev 模式：启动本地 Vite 和原生桌面窗口，前端直接读取源码、原生部分按需编译，不生成或替换发行 `.app`。窗口标题、侧栏均显示“开发版”。

## macOS

双击 `开发启动 ScholarNoteLM.command`，保留打开的终端。首次需要编译开发依赖，后续使用增量编译。2026-09-28 清理过编译缓存，因此下一次启动可能再次完整编译；这不表示模型或项目丢失。在终端按 Control+C 退出；再次双击可重新启动。若提示 1420 端口占用，已有开发版可直接继续使用；先退出其他独立 Vite 预览再启动。

| 修改内容 | 生效方式 |
| --- | --- |
| React / TypeScript / CSS | 保存后 Vite 自动更新界面，一般保留当前页面 |
| Rust / Tauri 配置 | 自动增量编译并重启桌面窗口，无需打包 |
| Python 下载 / Markdown 服务 | 下一次启动相应工作进程加载新代码；已运行任务继续使用启动时的代码 |
| Node 启动脚本 / 环境变量 / 依赖 | 退出开发进程后重新启动 |

下载进行中修改 Python，先在任务中心暂停，并等工作进程退出，再继续任务以加载新代码。重启 Rust 桌面进程时，属于旧进程的下载任务会暂停，需要在任务中心继续。不要为了更新代码清空项目。

开发版使用现有项目与系统配置。不要同时打开旧打包版和开发版编辑同一项目。原来的 `启动 ScholarNoteLM.command` 仍打开 `dist/macos/ScholarNoteLM.app`，它不会自动更新前端；本轮日常调试请使用新的开发启动入口。

## 文件位置

- 本地服务只监听 `127.0.0.1:1420`。
- Node、Rust、Python 运行时继续使用根目录 `runtimes/`。
- Cargo/npm/Vite 编译缓存位于 `cache/`，临时目录为 `tmp/`。
- 本次启动和热更新记录：`logs/development.log`。双击启动时日志直接显示在终端。
- 开发启动脚本会在退出时清理其子进程，不自动终止其他占用端口的程序。

## Windows

提供 `开发启动 ScholarNoteLM.cmd`。需要对应的 Windows Node（`runtimes/node/node.exe`）、Rust/Cargo 和 Python 运行时，以及 Windows 原生构建工具与 WebView2。不能直接复用 macOS 二进制。本轮在 macOS 实测；Windows 启动入口尚未实机验证。

## 早期开发模式验证记录

- 无刷新操作，保存 `App.tsx` 后界面由 0.5.3 自动变为 0.5.4 · 开发版。
- 修改 Tauri 配置后自动重新编译，约 7.66 秒后重新启动原生桌面进程。
- TypeScript 检查和 Vite 生产构建通过。

仅需要分发一个独立版本时才运行 `desktop:build`。

## 自动化启动 Zotero 导入

`research-cli` 从标准输入接收 JSON。在会回收命令子进程的自动化环境中，对 `zotero.start` 使用 `--wait`，让命令一直保留到导入任务结束；调用方须给予足够的执行时间。例如，先通过 `zotero.preview` 获得快照 ID，再将以下请求写入 JSON 文件：

```json
{"action":"zotero.start","args":{"project":"项目ID","preview":"快照ID"}}
```

```sh
SCHOLARNOTELM_ROOT="$PWD" cache/tauri-target/debug/research-cli --wait < request.json
```

`--wait` 只支持非流式 `zotero.start`。返回的 `data.state` 是终态；`ok: true` 表示调用完成，仍须检查 state 是 `completed`、`partial`、`failed`、`cancelled` 还是 `interrupted`。命令被外部强行终止仍可能中断导入，不能把后台进程分组当作对宿主回收的保证。

普通桌面入口继续后台执行。启动响应提供 `process.pid`、`jobId`；`zotero.status` 提供 worker 回执及 `process.lockHeld`，结合任务状态判断进度。项目 `metadata/zotero-imports/<任务ID>/` 内的 `spawn.json`、`process.json` 和 `worker.log` 用于诊断。锁占用只代表任务锁当时被占用，不单独证明某个 PID 存活。

仅对尚未发布 XML 的中断任务，内部 worker 可以保留原任务 ID 恢复；旧错误归档到 `attempts`，当前错误清空。已发布 XML 的任务拒绝再次执行同一 worker，以免重复发布。GUI 不增加恢复或更新按钮。

Markdown 任务同样可在开发版直接运行；转换期间修改 Python，先停止并等待当前篇完成，再创建下一任务。参见 [Markdown 说明](MARKDOWN.md)。

## 磁盘与依赖维护

目前转换仅使用 Marker，问答与综述检索使用 Embedding API。重排模型和 Paddle 专用环境已删除，不能按旧文档重新安装。`runtimes/retrieval` 仍是问答与综述 worker 的运行入口，其基础依赖通过 `.pth` 共享 `runtimes/marker`。

编译产物、安装缓存、当前可执行程序及用户资料的边界见 [本地维护](LOCAL_MAINTENANCE.md)。清理后无需为了检查文档重新打包；只有代码变化或需要发行版本时才构建。

# ScholarNoteLM 开发版

新机器先按 [安装说明](INSTALLATION.md) 准备干净环境；已有可用开发目录继续使用原启动方式，不运行安装器覆盖它。

日常修改使用根目录的 `开发启动 ScholarNoteLM.command`。这是 Tauri dev 模式：启动本地 Vite 和原生桌面窗口，前端直接读取源码、原生部分按需编译，不生成或替换发行 `.app`。窗口标题、侧栏均显示“开发版”。

## macOS

双击 `开发启动 ScholarNoteLM.command`，保留打开的终端。首次需要编译开发依赖，后续使用增量编译。清理编译缓存后的下一次启动可能重新完整编译；这不表示模型或项目丢失。在终端按 Control+C 退出；再次双击可重新启动。若提示 1420 端口占用，已有开发版可直接继续使用；先退出其他独立 Vite 预览再启动。

| 修改内容 | 生效方式 |
| --- | --- |
| React / TypeScript / CSS | 保存后 Vite 自动更新界面，一般保留当前页面 |
| Rust / Tauri 配置 | 自动增量编译并重启桌面窗口，无需打包 |
| Python 下载 / Markdown 服务 | 下一次启动相应工作进程加载新代码；已运行任务继续使用启动时的代码 |
| Node 启动脚本 / 环境变量 / 依赖 | 退出开发进程后重新启动 |

下载进行中修改 Python，先在任务中心暂停，并等工作进程退出，再继续任务以加载新代码。重启 Rust 桌面进程时，属于旧进程的下载任务会暂停，需要在任务中心继续。不要为了更新代码清空项目。

开发版默认使用现有项目与系统配置。测试时可显式设置 `SCHOLARNOTELM_ROOT` 为 `tmp/` 下的隔离根目录，启动脚本会保留该值，Rust 与 Python 使用同一根目录。不要同时打开旧打包版和开发版编辑同一项目。原来的 `启动 ScholarNoteLM.command` 仍打开 `dist/macos/ScholarNoteLM.app`，它不会自动更新前端；文件不存在时启动器会提示，日常调试请使用开发启动入口。

## 文件位置

- 本地服务只监听 `127.0.0.1:1420`。
- Node、Rust、Python 运行时继续使用根目录 `runtimes/`。
- Cargo/npm/Vite 编译缓存位于 `cache/`，临时目录为 `tmp/`。
- 启动与热更新日志显示在启动终端；脚本没有固定写入 `logs/development.log` 的保证。
- 开发启动脚本会在退出时清理其子进程，不自动终止其他占用端口的程序。

## Windows

提供 `开发启动 ScholarNoteLM.cmd`。需要对应的 Windows Node（`runtimes/node/node.exe`）、Rust/Cargo 和 Python 运行时，以及 Windows 原生构建工具与 WebView2。不能直接复用 macOS 二进制。当前主要在 macOS 使用；Windows 启动入口尚未实机验证。

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

## 原生退出保护验证

使用隔离根目录启动开发版，修改一个设置后分别关闭窗口和按 ⌘Q，验证继续编辑、放弃、保存失败和保存成功。配置保存成功后，还需等待项目状态及笔记的最后一次写入。macOS 的系统退出走 AppKit delegate，单独依赖 Tauri `ExitRequested` 不足以拦截 ⌘Q。修改或升级 Tauri/Tao 后需重复原生验证。

无需打开应用的回归测试：

```sh
./scripts/npm-local.sh exec -- node --test scripts/test-ui-navigation.mjs scripts/test-exit-protocol.mjs
./scripts/cargo-local.sh test --manifest-path apps/desktop/src-tauri/Cargo.toml --bin scholarnotelm exit_guard
```

## RPC 调试

CLI 为 `cache/tauri-target/debug/research-cli`。直接调用时必须设置 `SCHOLARNOTELM_ROOT`，输入为 `{"action":"...","args":{...}}`，输出为 `{"ok":true,"data":...}` 或错误对象。项目参数是项目 ID，不能假定永远等于文件夹名；路径须通过存储映射解析。

综述主要 RPC：`review.writing.status`、`prepare`、`start`、`retry`、`cancel`、`section`、`preview`、`export`、`settings`。文献库新增按钮对应 `download.start`、`markdown.reconcile`、`markdown.start`。

`review_service.rpc()` 已持有项目综述锁。不要在其同步子调用里重复获取同一非重入文件锁；后台 worker 自己持锁。曾通过真实 CLI 集成测试发现过这种重复加锁导致的“无法启动撰写进程”，不能仅靠直接调用 Python 函数的单元测试判断。

## 测试入口与隔离

基本验证命令见 [AGENTS.md](../AGENTS.md)。代码改动再按范围选用下列脚本，先检查其参数、环境变量及外部请求。文档整理只验证一致性、链接和前端构建，不为了文档重新生成 Rust 缓存或运行用户研究任务。

| 测试 | 范围与注意 |
| --- | --- |
| `scripts/test-review-integration.py` | 大纲与工作区 |
| `scripts/test-review-writing-integration.py` | 独立 worker、准备/写作、重试、取消和导出 |
| `scripts/test-qa-mini-review-integration.py` | 问答流程、历史证据与模型模拟 |
| `scripts/test-vectors-integration.py` | SQLite 向量、独立 worker、本机模拟 Embedding |
| `scripts/test-library-pipeline.py` | 文献库流程编排 |
| `scripts/test-project-deletion.py` | 隔离项目的永久删除与失败处理 |
| `scripts/test-markdown-corpus.py` | XML 变化、归档恢复与派生文件 |
| `scripts/test-literature-workflow.py` | 实际 Marker，非轻量检查 |
| `scripts/test-pubmed-live.py`、`test-download-live.py`、`test-source-cache-live.py` | 会访问真实外网，不是离线回归 |
| `scripts/test-review-reader-ui.mjs` | 离线导出的目录、引用、图表和布局 |
| `scripts/test-review-progress-library-ui.mjs` | 依赖本机项目快照，非空白安装通用测试 |
| `scripts/visual-check.mjs` | 检查提供的隔离 UI 快照，不默认连接 1420；见设计验收矩阵 |

Python 命令使用 `runtimes/downloader/bin/python`，Node 命令使用项目内 Node 或 `npm-local.sh`；部分 worker 会由脚本转交对应 runtime。测试文档里的历史通过记录不能替代本次验证。UI 脚本若连接现有 Vite，必须先以 `tmp/` 隔离的 `SCHOLARNOTELM_ROOT` 启动该服务，不能连接用户正在使用的项目。

修改 `main.rs` 或移动/删除根目录文件后还须实际运行桌面窗口；浏览器模式和 research-cli 不经过原生启动对 `services/downloader/engine.py` 的根目录检查。原生、浏览器和 Windows 验证不能互相代替。

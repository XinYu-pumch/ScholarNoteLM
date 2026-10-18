# 本地文件与磁盘维护

开发目录同时包含源码、运行环境、模型、缓存和研究项目，不等于发行 `.app` 的体积。清理依据当前用途，不能按目录大或文件名旧就删除。

## 可再生成缓存

在项目根目录先预览；执行删除前退出应用、开发服务和后台任务：

```sh
runtimes/downloader/bin/python scripts/clean-generated.py
runtimes/downloader/bin/python scripts/clean-generated.py --apply
```

脚本仅清理固定清单：

- `cache/tauri-target/debug/` 下的 `deps`、`build`、`incremental`、`.fingerprint`、`examples`、`bundle`。
- `cache/vite`、`cache/npm/_logs`、`cache/status-snapshots`。

它拒绝符号链接路径；执行时检测应用/构建进程，发现占用会停止。不会清空 `tmp/`、用户工作目录、模型、安装环境或历史备份，也不删除当前 `scholarnotelm` 与 `research-cli` 可执行文件。Windows 的进程检查较保守，需要退出相关 Node/Cargo 程序。

清理后下一次 Rust 编译或开发启动可能重建大量中间文件，属于正常行为。工具显示文件逻辑大小，硬链接、APFS 写时复制等会使实际释放量小于路径大小之和；以清理前后的磁盘占用核对，不能把预览数当作必然释放量。

npm 下载缓存 `cache/npm/_cacache`、测试截图和日志不在上述脚本清单内。它们是否仍需保留应按本次任务检查并明确删除，不能声称脚本已一并处理。`tmp/` 也可能包含未完成的隔离实验或独有资料，不自动整目录清空。

## 必须保留的运行文件

| 路径 | 用途 |
| --- | --- |
| `models/marker/` | 本地 PDF 转换模型 |
| `runtimes/python/` | Python 虚拟环境共用的解释器 |
| `runtimes/downloader/` | 下载、项目 RPC、综述服务与导出 |
| `runtimes/marker/` | Marker / Surya / PyTorch、索引进程及共享基础依赖 |
| `runtimes/retrieval/` | 综述和问答 worker，借助 `.pth` 共享 Marker 依赖 |
| `runtimes/node/` | 前端开发与下载浏览器 sidecar |
| `runtimes/rust/`、`cache/cargo/` | Rust 工具链与源码依赖缓存 |
| `runtimes/playwright/` | 下载用 Chromium 与 UI 测试浏览器 |
| `services/downloader/resources/` | Jina tokenizer、Zotero 附件白名单等运行资源 |
| `installers/marker/` | `setup-marker-local.py` 使用的离线安装材料 |
| `data/reference/` | MeSH、JCR、Sci-Hub Bloom |
| `cache/tauri-target/debug/scholarnotelm` | 当前开发版原生程序 |
| `cache/tauri-target/debug/research-cli` | 浏览器桥接及 CLI 入口 |
| `dist/ui/` | 前端构建结果 |
| `dist/macos/ScholarNoteLM.app`（若存在） | 旧启动器引用的独立副本，不随源码更新 |

不能因两个环境含同名包就卸载共享依赖，也不能将整个 `cache/` 或 `runtimes/` 当作可删除缓存。Mac 二进制不能直接复制到 Windows 使用。

## 研究数据与无损压缩

PDF、Markdown、向量源快照、问答历史证据、综述材料及已保存稿件都是研究数据。`pdf/redundant/` 与 `archive/markdown/` 用于重新纳入文献时恢复，不是普通下载缓存。全文快照、图片副本和日志可能支持引用核查及重试，不应只按重复内容删除。

新产物自动采用压缩日志、共享 XML、图片快照、稿件图片去重等规则，见 [项目存储](PROJECT_STORAGE.md)。旧项目可先只读估算：

```sh
runtimes/downloader/bin/python scripts/compact-project-storage.py
runtimes/downloader/bin/python scripts/compact-project-storage.py --project 项目ID --html
```

默认检查所有注册项目；`--project` 可重复指定，`--html` 额外检查可识别的单文件 HTML。**只有加 `--apply` 才写入项目**，应在获得相应授权并结束冲突任务后执行。工具持锁、校验无损还原，保留模型输入、引用和签名；无法识别的旧格式跳过，不重新生成正文。

历史归档是否存在以实际磁盘为准，不承诺旧清理报告中的路径仍可恢复。确需恢复归档时先解压到独立空目录，核对后取回；不要覆盖正在使用的项目。源码和被合并的说明从 Git 历史查阅，不需要按日期保留重复源码目录。

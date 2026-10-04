# 本地文件与磁盘维护

更新：2026-10-02。这里说明整个开发目录，包含运行环境、模型及个人研究项目，不等于分发的 `.app` 大小。

## 2026-10-02 清理

本次删除 Rust 构建中间文件、重复的旧应用打包副本、已确认相同的 WebKit/FFmpeg 缓存、已完成安装的 Rust 引导程序，以及源码目录中的 Python 字节码缓存。

历史备份、实验目录、临时分析文件和项目 `analysis/` 目录已汇入 `backups/history-20261002.tar.gz`。归档对相同内容去重并压缩；逐文件校验 SHA-256 后才移除原目录。归档中的独有 PDF 样本、源码、报告和旧数据均保留。旧文档或实验脚本里的这些历史路径需先从归档恢复。

清理结果、文件清单、数据保留检查与运行验证见 [本次报告](../logs/storage-cleanup-20261002/REPORT.md)。既有研究项目中的 PDF、摘要、Markdown、图片、索引、对话、综述正文、已保存稿件、导出文件和配置均保留。旧项目回收站、已删除综述的旧备份和 `pdf/redundant/` 也保留，避免丢失仅存资料。

## 日常清理

退出应用、开发服务及后台任务后，在项目根目录执行：

```sh
python3 scripts/clean-generated.py          # 只显示可清理路径及大小
python3 scripts/clean-generated.py --apply  # 清理所列缓存
```

脚本使用固定允许清单，拒绝符号链接路径；检测到应用或构建进程时停止清理。它不会清空 `tmp`、项目目录、安装环境、模型或历史备份，也不删除当前可执行程序。Windows 可使用已安装的 Python 执行；Windows 进程检查较保守，需退出其他 Node/Cargo 程序。

缓存可重新生成，因此下一次 Rust 编译或开发启动会较慢。反复开发仍会产生编译缓存，可在阶段工作完成后再次预览清理。安装依赖所需的 Cargo 源码缓存保留，避免每次重新下载。

## 恢复历史文件

先解压到单独的空目录，核对后按需取回；不要直接覆盖正在使用的项目：

```sh
mkdir -p tmp/restore-history-20261002
tar -xzf backups/history-20261002.tar.gz -C tmp/restore-history-20261002
```

归档内采用相对路径，相同内容可能表示为 tar 硬链接，标准 tar 可恢复。原路径、大小、时间和校验值记录于 `logs/storage-cleanup-20261002/archive-manifest.json.gz`。同内容去重以文件内容与权限为准；需要精确恢复每个历史副本的时间戳时，以该清单为准。

## 必须保留的运行文件

| 路径 | 用途 |
| --- | --- |
| `models/marker/` | 当前本地 PDF 转换模型 |
| `runtimes/python/` | 各 Python 虚拟环境共用的解释器，虚拟环境中的 python 是指向它的链接 |
| `runtimes/marker/` | Marker/Surya/PyTorch、索引进程与共享基础依赖（仍装有已不使用的 chromadb 包） |
| `runtimes/retrieval/` | 问答及综述 worker 的入口；通过 `scholarnotelm-shared.pth` 共享 Marker 环境 |
| `runtimes/downloader/` | 下载、项目 RPC 等服务 |
| `runtimes/node/` | 前端开发及后台下载浏览器服务 |
| `runtimes/playwright/` | 下载用 Chromium 和界面测试浏览器，不可整体当作缓存删除 |
| `cache/tauri-target/debug/scholarnotelm` | 当前开发版原生程序 |
| `cache/tauri-target/debug/research-cli` | 浏览器开发桥接与 CLI 测试入口 |
| `dist/ui/` | 当前前端构建 |
| `dist/macos/ScholarNoteLM.app` | 旧启动器仍引用的独立安装包，不会随开发源码更新 |

Marker 仍需要自己的 Transformers、Tokenizers 和 PyTorch。不能看到同名包就全部卸载，也不能把 `runtimes/retrieval` 整个删除。

## 保留原因

- `runtimes/playwright` 保留下载用 Chromium 和界面兼容性验证用 WebKit。清掉的是 `cache/playwright` 中重复安装的副本。
- `installers/marker` 的离线 wheel 仍被 `scripts/setup-marker-local.py` 使用，保留。
- `data/reference` 的 MeSH、JCR 和下载索引仍被当前功能使用，保留。
- 问答的证据快照、综述准备材料及图表副本支持引用核查和继续撰写，不能只凭体积删除。
- 当前 PDF、Markdown 和向量资源中部分内容相似，但用途及更新规则不同，不对可变项目文件建立硬链接。
- 前端 46 个 TypeScript 文件均可从应用入口追踪到，未按文件名推测并删除功能。旧 PaddleOCR、MedCPT、BM25 和重排模型已在前次精简中移除，没有重新安装。

2026-09-28 的第一次清理记录见 [历史报告](../logs/storage-cleanup-20260928/REPORT.md)。当时保留的历史备份和实验文件已按本次清理规则归档；不要将旧报告当作当前磁盘清单。

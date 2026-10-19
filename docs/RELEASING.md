# ScholarNoteLM 上传与发布约定

项目提供两种使用方式：**源码版**和**独立 App 版**。两者使用同一套业务源码，区别在于运行环境和本地模型是否随程序一起分发。本文统一规定发布位置；安装细节见 [安装说明](INSTALLATION.md)。

## 1. 文件上传到哪里

| 内容 | 发布位置 | 说明 |
| --- | --- | --- |
| 应用源码、文档、依赖锁、安装脚本 | [GitHub 仓库](https://github.com/XinYu-pumch/ScholarNoteLM) | 提交到 Git，主分支为 `main` |
| Windows/macOS 独立版打包脚本、模板和清单 | 同一 GitHub 仓库 | 与业务源码一起维护，不另建一套源码仓库 |
| Windows 源码配套预编译程序 | [GitHub Releases](https://github.com/XinYu-pumch/ScholarNoteLM/releases) | Windows ZIP，含主程序、环境安装引导、源码校验清单及许可证 |
| macOS 源码配套预编译程序 | 同一个 GitHub Release | Mac ZIP，含 `ScholarNoteLM.app`；不含 Python 运行环境和本地模型 |
| 与预编译程序匹配的源码 ZIP | 同一个 GitHub Release | 供不使用 Git 的用户下载 |
| Windows/macOS 完整独立版 | 网盘 | 按平台分别发布，包含程序、配套源码、运行环境、本地模型和浏览器等运行资源 |
| 单独的 `models/` 文件夹 | 网盘 | 供源码版用户下载；须与源码中的资源清单匹配 |

“GitHub 存放预编译程序”指 **Release 附件**，不是将 `.app`、EXE 或程序 ZIP 提交进 Git 历史。完整独立版和模型大包不上传 GitHub Release。

Git 仓库仍包含指定随附的 JCR 表 `services/reference/jcr/default-2025.xlsx`、必要分词器资源和第三方许可。这些源码随附资源不等于单独分发的 `models/`。

## 2. 用户如何使用

### 方式 A：独立 App 版

1. 从网盘下载适合自己平台的完整独立版。
2. Mac 解压后打开 `ScholarNoteLM.app`；Windows 按独立安装包说明安装，并通过独立版入口启动。
3. 首次启动选择研究工作目录，填写自己的 LLM、Embedding 等服务配置。

无需 Git clone、额外下载 `models/` 或运行源码版环境安装脚本。包内包含本地运行依赖，但 PubMed、文献下载和远程模型调用仍需要网络。

Mac 详见 [MACOS_STANDALONE.md](MACOS_STANDALONE.md)；Windows 详见 [WINDOWS_STANDALONE.md](WINDOWS_STANDALONE.md)。Windows CUDA 大包若包含安装 EXE 和配套 `.bin`，必须完整下载、解压，不能只取 EXE。

### 方式 B：源码版

1. Git clone 仓库，并切换到 Release 指定的源码标签或提交；也可直接下载该 Release 的匹配源码 ZIP。
2. 从 GitHub Release 下载自己平台的预编译程序，解压到源码根目录。
3. 从网盘下载匹配的 `models/`，放入源码根目录，得到 `models/marker/...`，不要套成 `models/models/`。
4. Mac 运行 `install-environment.command`；Windows 运行 `ScholarNoteLM-Setup.exe` 或 `install-environment.cmd`，安装完整运行环境并检查资源。
5. Mac 打开根目录的 `ScholarNoteLM.app`，Windows 打开根目录的 `ScholarNoteLM.exe`。

这里的“源码版”是**源码＋预编译桌面程序＋用户本机安装的环境**，普通用户不需要自己编译 Rust 或前端，也不需要预装系统 Python、Node 或编译工具。使用 `git clone` 需要可用的 Git；Mac 没有 Git/Command Line Tools 时可下载源码 ZIP。操作系统和硬件要求见 [安装说明](INSTALLATION.md#系统要求)。

源码版的源码目录、运行环境和 `models/` 要一起保留，不能仅留下 `.app` 或 EXE。研究工作目录由用户另行指定，可放在安装目录之外。

## 3. 版本与 Release 组织

- GitHub 保留一个当前 Release，集中提供 Windows 和 Mac 的源码配套程序、当前源码 ZIP、SHA-256 校验文件，以及网盘下载入口。
- 每个平台程序明确记录对应源码提交、版本和架构。独立版也标明对应源码提交，方便核对和复现构建。
- **相同版本号不一定是相同构建**。程序内嵌源码清单，不能把最新 `main` 与旧的预编译程序随意组合。克隆后按发布页说明切换到匹配提交；不要绕过源码校验。
- 两个平台尽量使用同一份确定的源码构建。若其中一个平台暂未重编译，保留附件时必须逐项标注其实际对应的旧源码提交，并提供精确源码下载入口；不能把旧程序改名后宣称与新源码兼容。
- 模型包记录适用的资源清单版本或提交，并提供 SHA-256；内容须通过 `scripts/install/assets.json` 校验。资源清单未变化时可复用模型包，不必随每次 UI 修改重新上传。
- 发布页分别列出“源码版程序”“独立版网盘下载”“源码版 models 下载”，避免把两个同名的 Mac `.app` 混淆。
- 未完成构建、上传或验证的项目明确标注“待提供”，不把本机已有文件当作用户已经能够下载的产物。

## 4. 维护者上传顺序

1. **确定源码。** 在工作分支完成修改和相应验证，合并到 `main`；检查 `git status`，只提交公开源码、文档、脚本和允许随附的资源。
2. **确定发布提交。** 记录源码提交并准备对应标签，推送源码。运行 `scripts/audit-public-source.py` 检查可达 Git 历史的常见密钥格式、私人目录和大文件；示例、资源许可仍须人工核对。
3. **构建源码配套程序。** 在 Mac 和 Windows 分别基于指定源码构建，验证程序与源码清单一致。安装脚本、依赖和本地资源的验证按对应安装文档执行。
4. **上传 GitHub Release。** 将两平台程序 ZIP、当前匹配源码 ZIP 和各自 `.sha256` 放入同一个当前 Release；说明每份程序的精确源码对应关系。
5. **构建并上传独立版。** 按两平台独立版文档打包和隔离验收，将完整独立包及校验文件上传网盘。独立打包脚本留在 Git，不将独立包加入 Git 或 Release。
6. **上传 models。** 将源码版所需的 `models/` 打包上传网盘，保留原目录结构、模型卡和许可，并记录资源清单对应关系。
7. **补齐下载说明。** 在 Release 中填写网盘链接、提取码（如有）、平台/架构、文件名、校验值及安装说明入口。核对实际可下载文件与本地构建的大小、SHA-256 一致。
8. **保留一个当前 Release。** 新附件验证完成后再清理其他旧 Release；保留待替换的平台附件及其精确源码入口，不误删另一平台当前可用产物。历史源码提交仍可追溯，标签按仓库维护安排清理。

上述是发布流程约定；构建脚本只生成本地产物，不自动上传 GitHub 或网盘。单独修改本文不会触发构建或发布。

### 构建入口

| 产物 | 构建入口 |
| --- | --- |
| Mac 源码配套程序 | `runtimes/downloader/bin/python scripts/build-source-release.py` |
| Windows 源码配套程序 | `runtimes\downloader\Scripts\python.exe scripts/build-windows-release.py` |
| Mac 独立版（同时生成配套程序） | `runtimes/downloader/bin/python scripts/build-source-release.py --standalone` |
| Windows 独立版 | `scripts/build-windows-standalone.py`，参数和依赖见 [Windows 独立版文档](WINDOWS_STANDALONE.md#构建命令) |

源码配套程序及源码 ZIP 位于 `dist/release/`；Mac 独立版只生成 `dist/macos-standalone/ScholarNoteLM.app`（不附 ZIP 或中间目录），Windows 独立包位于 `dist/standalone/`。只有打包成功并不代表功能验收通过。

## 5. 不发布个人数据

Git、Release 和网盘发行包都不包含开发者的 API Key、个人配置、研究数据库、工作目录、论文、综述、问答记录或调试日志。

- 根目录 `config/`、`data/`、`workspace/`，以及 `tmp/`、`logs/`、`cache/`、个人备份和 `.git/` 不打进用户发行包。
- `runtimes/`、`models/` 不提交 Git。**独立版需要按打包清单包含运行时和模型**；源码版的运行时由安装器建立，模型通过网盘单独取得。
- `services/marker/vendor/marker/config/` 是源码，区别于根目录个人配置；`services/downloader/resources/jina-embeddings-v4/tokenizer.json` 是指定保留的源码资源。
- 主项目采用 GPL-3.0-or-later；模型、字体和第三方资源保留各自许可。详见 [第三方说明](../THIRD_PARTY_NOTICES.md) 和 [资源说明](../scripts/install/ASSET_NOTICES.md)。

## 6. 平台与签名

当前源码配套目标为 Apple Silicon / macOS 14+ 与 Windows 10/11 x64；具体实机验收范围见安装和平台文档。Intel Mac、Windows ARM64 等需要单独构建与验证，不能直接给现有程序改名。

Mac 当前使用 ad-hoc 签名，尚无 Developer ID 签名与公证；Windows 当前未做 Authenticode 签名。正式签名后重新生成程序包和校验值，签名后不能再修改包内容。发布测试使用隔离目录，分别验证源码版安装和独立版启动、转换、重启及研究工作目录重连。

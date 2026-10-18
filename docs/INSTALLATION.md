# macOS 源码安装版

这是“源码目录 + 预编译桌面程序 + 自动安装运行环境”的版本。普通用户不编译应用，不需要预装 Python、Node、Rust、Homebrew 或 Xcode Command Line Tools。

## 系统要求

- Apple Silicon Mac（M 系列），macOS 14 或更新版本。Intel Mac、Windows、Linux 尚未提供本发行版本。
- 建议至少 16 GB 内存；较低内存设备的 PDF 转换体验尚未验收。
- 安装时建议预留 15–20 GB 空间，研究资料另计。下载缓存可在安装成功后清理，`runtimes/` 和 `models/` 不能当缓存删除。
- 首次安装需要访问 GitHub、PyPI、Node/npm 和 Playwright 下载服务。安装子进程跟随可用的 HTTP(S) 系统代理，并尊重显式设置的代理环境变量。
- 安装目录和研究目录都应为当前用户可写的文件夹。不需要 `sudo`，不修改系统 Python 或 shell 配置。

## 安装步骤

1. 从同一个 GitHub Release 取得源码和 `ScholarNoteLM-0.6.1-macos-arm64.zip`。源码可以直接下载 ZIP；macOS 的 `git` 命令可能要求 Command Line Tools，因此 `git clone` 不是前提。
2. 解压源码到准备长期保留的文件夹，把程序 ZIP 中的 `ScholarNoteLM.app` 放到该源码目录根部。
3. 双击 **安装环境.command**。脚本下载并校验引导工具，然后安装项目专用 Python 3.12.9、Marker/向量/下载依赖、Node 20.19.0、Playwright/Chromium 与字体。不会安装 Rust 或构建前端。
4. 从发布者的网盘下载该版本匹配的 `models` 文件夹，放入源码根目录，形成 `models/marker/...`，不要多套一层 `models/models/`。
5. 再次运行安装入口，检查模型文件完整性和程序/源码匹配情况。也可以在终端运行 `bash 安装环境.command --check`。
6. 双击根目录中的 **ScholarNoteLM.app**，首次启动先选择研究工作目录，再创建项目、填写模型服务配置。

模型可以在安装环境之前或之后放入。模型尚未补齐时，安装器明确提示待补齐文件；已安装环境保留，PDF 转换在资源完整前不可用。不会自动从已失效的旧模型地址下载替代版本。

当前预编译程序使用本地 ad-hoc 签名，**没有 Apple Developer ID 签名或公证**。下载后 macOS 可能阻止打开，需要按照系统“隐私与安全性”的提示批准来源。安装器不会关闭 Gatekeeper、移除隔离属性或修改系统安全设置。若需要常规无额外授权的分发体验，维护者需另行使用 Developer ID 签名、公证并验收。

## 文件位置

```text
ScholarNoteLM/
  ScholarNoteLM.app          # 从 Release 解压，不提交 Git
  安装环境.command           # 安装/继续安装/检查；日常直接打开 app
  apps/                     # 前端与 Rust 源码
  services/                 # Python 服务、Marker、浏览器下载依赖
  scripts/                  # 安装清单和维护脚本
  models/marker/            # 网盘取得，不提交 Git
  runtimes/                 # 项目专用运行环境，不提交 Git
  config/                   # 个人设置，不提交 Git
  data/                     # 系统状态和参考资源，不提交 Git
  cache/                    # 下载/浏览器缓存，不提交 Git
```

研究工作目录由用户指定，支持中文、空格和可写的外置磁盘目录。新安装不会默认生成 `workspace/`。所选目录可有其他文件，创建项目时不会覆盖同名目录。已有安装沿用原工作目录；磁盘失联时要求重新连接，不自动创建空白替代项目。

首版 `.app` 与安装目录配套使用，不应只把 `.app` 单独移到 `/Applications` 后删除源码目录。程序优先寻找旁边的源码；系统将下载程序临时转移到隔离位置时，可使用安装器登记的目录；找不到或有多个匹配安装时要求选择安装目录。安装目录和研究工作目录是两个不同概念。

安装登记文件位于 `~/Library/Application Support/ScholarNoteLM/installations.json`，只记录安装路径。程序包含源码校验清单，错误版本会明确报错。更新时请取得完整匹配的一组源码和程序；不要只替换 Python 源文件或只更新 app。

系统参考资料独立管理：JCR 由用户导入有权使用的文件，MeSH 可在设置中从官方来源下载；未提供 Sci-Hub Bloom 索引时会提示不可用并保留后续全量重试，不把开发者的 `data/reference/` 随源码复制给新用户。

## 保留已有开发环境

已有正常安装不需要重跑安装器。脚本拒绝覆盖不属于它管理的环境。当前用户可直接打开本次构建的根目录 `.app`，现有配置、模型、运行时与研究资料继续使用。

安装状态保存在 `runtimes/install-state.json`。同一依赖清单的未完成安装可再次执行；损坏文件会报错而不会被默默忽略。依赖版本变更使用新的干净目录，不做当前环境的破坏性原地升级。

## 维护者构建

维护者才需要 Xcode Command Line Tools、Rust 与前端开发依赖。干净目录可额外使用 `scripts/setup-runtime.py --apply --dev-tools` 安装开发依赖。

```sh
runtimes/downloader/bin/python scripts/build-source-release.py
```

产物为根目录 `ScholarNoteLM.app`，以及 `dist/release/` 下的 `ScholarNoteLM-0.6.1-macos-arm64.zip`、`ScholarNoteLM-0.6.1-source.zip` 和各自的 SHA-256 文件。构建前生成源码清单并嵌入程序，产物只含桌面前端与 Rust 程序，不捆绑用户数据、密钥、Python 环境或模型。

源码公开范围、检查和发布步骤见 [发布说明](RELEASING.md)。模型与字体许可见 [资源说明](../scripts/install/ASSET_NOTICES.md)。模型走网盘不改变其原始许可证要求。

## 验证

```sh
runtimes/downloader/bin/python scripts/test-runtime-setup.py
runtimes/downloader/bin/python scripts/test-runtime-conversion.py --root /绝对路径/干净安装目录
```

第二项在一次性研究项目中生成人工 PDF，使用真实本地 Marker 转换，不调用模型 API。完整流程测试使用本机模拟模型服务。安装实测应限制 PATH，确认未依赖全局 Python/npm/Rust；开发机上的此项验证不等于已在无 Command Line Tools 的另一台 Mac 或所有 macOS 14+ 版本完成实机验收。

本版已完成：629 项 Python 测试（4 项跳过）、Rust CLI 与桌面测试、前端/release 构建、原生窗口首次目录选择和重启、安装目录移动后的检查、45 项浏览器测试及真实离线 PDF 转换。隔离安装使用仅含 macOS 系统工具的 PATH，并设置不可用的开发工具目录；未在另一台无 CLT 的真机上验收，也尚未验证 macOS 下载隔离后的所有启动路径。

# 源码安装版与独立版

两种发行方式及下载位置见 [上传与发布约定](RELEASING.md)。完整独立版通过网盘发布，使用方法见 [Mac 独立版](MACOS_STANDALONE.md) 和 [Windows 独立版](WINDOWS_STANDALONE.md)。以下介绍“源码目录 + 预编译桌面程序 + 自动安装运行环境”的版本。普通用户不编译应用，不需要预装 Python、Node、Rust、Homebrew 或 Xcode Command Line Tools。

## 系统要求

- Apple Silicon Mac（M 系列），macOS 14 或更新版本。Intel Mac、Linux 尚未提供本发行版本；Windows x64 见下文。
- 建议至少 16 GB 内存；较低内存设备的 PDF 转换体验尚未验收。
- 安装时建议预留 15–20 GB 空间，研究资料另计。下载缓存可在安装成功后清理，`runtimes/` 和 `models/` 不能当缓存删除。
- 首次安装需要访问 GitHub、PyPI、Node/npm 和 Playwright 下载服务。安装子进程跟随可用的 HTTP(S) 系统代理，并尊重显式设置的代理环境变量。
- 安装目录和研究目录都应为当前用户可写的文件夹。不需要 `sudo`，不修改系统 Python 或 shell 配置。

## 安装步骤

1. Git clone 仓库后切换到 Release 指定的匹配源码标签或提交，并下载该 Release 的 `ScholarNoteLM-<版本>-macos-arm64.zip`；也可直接下载匹配源码 ZIP。不要默认最新 `main` 与现有程序一致。macOS 的 `git` 命令可能要求 Command Line Tools，因此 `git clone` 不是前提。
2. 解压源码到准备长期保留的文件夹，把程序 ZIP 中的 `ScholarNoteLM.app` 放到该源码目录根部。
3. 双击 **install-environment.command**。脚本下载并校验引导工具，然后安装项目专用 Python 3.12.9、Marker/向量/下载依赖、Node 20.19.0、Playwright/Chromium 与字体。不会安装 Rust 或构建前端。
4. 从发布者的网盘下载该版本匹配的 `models` 文件夹，放入源码根目录，形成 `models/marker/...`，不要多套一层 `models/models/`。
5. 再次运行安装入口，检查模型文件完整性和程序/源码匹配情况。也可以在终端运行 `bash install-environment.command --check`。
6. 双击根目录中的 **ScholarNoteLM.app**，首次启动先选择研究工作目录，再创建项目、填写模型服务配置。

模型可以在安装环境之前或之后放入。模型尚未补齐时，安装器明确提示待补齐文件；已安装环境保留，PDF 转换在资源完整前不可用。不会自动从已失效的旧模型地址下载替代版本。

当前预编译程序使用本地 ad-hoc 签名，**没有 Apple Developer ID 签名或公证**。下载后 macOS 可能阻止打开，需要按照系统“隐私与安全性”的提示批准来源。安装器不会关闭 Gatekeeper、移除隔离属性或修改系统安全设置。若需要常规无额外授权的分发体验，维护者需另行使用 Developer ID 签名、公证并验收。

## Windows x64

从当前 GitHub Release 取得 Windows 源码配套程序，并使用附件说明指定的源码标签、提交或源码 ZIP。若发布页标注 Windows 程序尚未同步重编译，应使用它明确对应的源码，或等待新的匹配程序；不能仅凭相同版本号判断兼容性。程序内嵌的源码清单会拒绝不匹配的组合。

目标为 Windows 10/11 x64（Intel/AMD），当前在 Windows 11 上验收；Windows ARM64 不属于此发布目标。沿用“匹配源码 + 平台程序 + models”的布局，Windows 与 macOS 共用仓库和模型资源，运行时须分别安装。

1. 取得 Windows 程序明确对应的源码（Git clone 后切换到指定提交，或解压匹配源码 ZIP）。安装目录须可写，建议使用较短的路径，如 `D:\ScholarNoteLM`，避免系统受保护目录。
2. 将 `ScholarNoteLM-<版本>-windows-x64.zip` 的内容解压到源码根目录，保留主程序、安装引导、`source-manifest.json` 和第三方许可目录。
3. 把网盘提供的模型放入 `models/marker/`，不要重复嵌套 `models/models/`。
4. 双击 `ScholarNoteLM-Setup.exe`，点击“安装 / 继续”。也可双击源码中的 `install-environment.cmd`。无需提前安装 Python；引导程序下载并校验引导工具，再创建项目专用 Python 3.12.9、Node 20.19.0、Chromium 和固定版本依赖。
5. 点击“检查环境”，成功后双击 `ScholarNoteLM.exe`。首次使用选择研究工作目录，再创建项目。

普通用户无需勾选“开发工具”。安装器检测 Microsoft Edge WebView2；缺失时运行经 Microsoft 签名验证的官方安装程序。首次安装需要网络，可继承 `HTTPS_PROXY`；下载失败后可重试，成功完成的安装阶段保留。模型不由安装器重新下载。没有 NVIDIA 显卡也能使用 CPU。

### 可选 NVIDIA CUDA 加速

安装引导默认勾选“自动安装 NVIDIA CUDA 加速”，先安装原有 CPU 环境，再根据显卡和驱动选择固定版本的 CUDA PyTorch，额外下载约 2–3 GB。不需要安装系统 CUDA Toolkit、cuDNN 或 Rust。取消勾选则仅安装 CPU；命令行对应 `-CpuOnly`。

已安装匹配 CPU 环境的用户可以单独添加 CUDA：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-windows.ps1 -CudaOnly
```

PyTorch 保持 2.9.1：普通适用显卡优先 cu126；计算能力 10.0 及以上（包括 RTX 50 系）选择 cu128。自动安装采用保守驱动门槛：cu126 为 Windows 驱动 560.76+，cu128 为 570.65+，新显卡还需要支持该型号的驱动。门槛来自对应 Toolkit 发布时的驱动版本，不表示更旧驱动一定不能运行；最终以 GPU 运算检查和模型转换为准。部分老显卡未包含在 wheel 中，即使有 NVIDIA 驱动也可能无法加速。不自动安装或升级显卡驱动。

CUDA 环境位于 `runtimes/marker-cu<版本>-<校验标识>/`，自身保存 GPU 版 torch，其余固定依赖共享 `runtimes/marker`，模型共用 `models/`。验证成功后才更新 `runtimes/cuda-state.json`；失败保留 CPU 和原有可用 CUDA 指针。不要单独移动或删除这些依赖目录。移动整个安装目录后，运行普通“安装 / 继续”修复虚拟环境路径。

每次打开新 App 会后台检查设备，不下载组件或加载模型；开始转换前再次验证。检测结果显示在全文转换设置中。自动模式下 GPU 不可用则使用 CPU；手动指定不可用设备会明确报错。仅本地 Marker 模型推理受益，远程 API、下载和数据库不会获得 CUDA 加速。显存不足/设备故障的恢复规则见 [转换说明](MARKDOWN.md)。

此功能需要包含 CUDA 改动的匹配源码和预编译程序；旧 Release 与先前构建的 CPU 独立安装包不会自动更新。当前实测 Windows RTX 4070 Ti SUPER + 驱动 591.74 + cu126；cu128/RTX 50 系仍需相应机器验证；Mac MPS 已通过隔离合成 PDF 转换验证。

安装引导是独立 WinForms EXE，使用 Windows 自带的 .NET Framework；主程序通过 Tauri/WebView2 显示界面。两者均未做 Authenticode 签名，系统可能显示未知发布者提示；正式公开分发前可另行签名，不通过关闭系统安全功能解决提示。

安装登记位于 `%LOCALAPPDATA%\ScholarNoteLM\installations.json`。不要只移动 EXE 或删除源码。移动整个安装目录后，先重新运行“安装 / 继续”，修复 Python 虚拟环境中的目录路径，再检查环境；研究工作目录按原有重连流程处理。Windows 与 macOS 的 `runtimes/` 不能互相复制。

命令行检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-windows.ps1 -Check
```

此命令只为当前脚本进程设置执行策略，不修改系统的永久策略。

## 文件位置

```text
ScholarNoteLM/
  ScholarNoteLM.app          # 从 Release 解压，不提交 Git
  ScholarNoteLM.exe          # Windows 主程序，与 .app 按平台二选一
  ScholarNoteLM-Setup.exe    # Windows 环境安装引导
  source-manifest.json       # Windows 程序对应的源码清单
  install-environment.cmd   # Windows 源码安装入口
  install-environment.command # 安装/继续安装/检查；日常直接打开 app
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

源码配套 `.app` 与安装目录配套使用，不应只把 `.app` 单独移到 `/Applications` 后删除源码目录。程序优先寻找旁边的源码；系统将下载程序临时转移到隔离位置时，可使用安装器登记的目录；找不到或有多个匹配安装时要求选择安装目录。安装目录和研究工作目录是两个不同概念。

安装登记文件位于 `~/Library/Application Support/ScholarNoteLM/installations.json`，只记录安装路径。程序包含源码校验清单，错误版本会明确报错。更新时请取得完整匹配的一组源码和程序；不要只替换 Python 源文件或只更新 app。

系统参考资料独立管理：源码随附 `services/reference/jcr/default-2025.xlsx`，首次使用自动校验并启用；已有 JCR 配置保持不变，用户仍可上传其他分区表或恢复内置默认。MeSH 可在设置中从官方来源下载；未提供 Sci-Hub Bloom 索引时会提示不可用并保留后续全量重试，不把开发者的 `data/reference/` 随源码复制给新用户。

## 保留已有开发环境

已有正常安装不需要重跑安装器。脚本拒绝覆盖不属于它管理的环境。当前用户可直接打开本次构建的根目录 `.app`，现有配置、模型、运行时与研究资料继续使用。

安装状态保存在 `runtimes/install-state.json`。同一依赖清单的未完成安装可再次执行；损坏文件会报错而不会被默默忽略。依赖版本变更使用新的干净目录，不做当前环境的破坏性原地升级。

## 维护者构建

Windows 维护者先安装 Microsoft Visual Studio Build Tools 的“使用 C++ 的桌面开发”（MSVC x64 与 Windows SDK），再在安装引导中勾选“开发工具”，或运行 `scripts/install-windows.ps1 -DevTools`。此选项安装项目内 Rust 1.98.1 和前端依赖，不自动安装系统级 C++ 编译工具。

```powershell
runtimes\downloader\Scripts\python.exe scripts/build-windows-release.py
```

产物位于根目录的两个 EXE，以及 `dist/release/` 内的 Windows ZIP、匹配源码 ZIP 和 SHA-256 文件。源码必须与嵌入 EXE 的清单一致；修改源码后重新构建，不手动绕过校验。

维护者才需要 Xcode Command Line Tools、Rust 与前端开发依赖。干净目录可额外使用 `scripts/setup-runtime.py --apply --dev-tools` 安装开发依赖。

```sh
runtimes/downloader/bin/python scripts/build-source-release.py
```

产物为根目录 `ScholarNoteLM.app`，以及 `dist/release/` 下的 `ScholarNoteLM-0.6.4-macos-arm64.zip`、`ScholarNoteLM-0.6.4-source.zip` 和各自的 SHA-256 文件。构建前生成源码清单并嵌入程序，产物只含桌面前端与 Rust 程序，不捆绑用户数据、密钥、Python 环境或模型。

源码公开范围、检查和发布步骤见 [发布说明](RELEASING.md)。模型与字体许可见 [资源说明](../scripts/install/ASSET_NOTICES.md)。模型走网盘不改变其原始许可证要求。

## 验证

```sh
runtimes/downloader/bin/python scripts/test-runtime-setup.py
runtimes/downloader/bin/python scripts/test-runtime-conversion.py --root /绝对路径/干净安装目录
```

第二项在一次性研究项目中生成人工 PDF，使用真实本地 Marker 转换，不调用模型 API。完整流程测试使用本机模拟模型服务。安装实测应限制 PATH，确认未依赖全局 Python/npm/Rust；开发机上的此项验证不等于已在无 Command Line Tools 的另一台 Mac 或所有 macOS 14+ 版本完成实机验收。

Mac 源码安装已通过全新环境安装、原生窗口、重启及离线 MPS 转换验证。独立版须另行验证包内运行时、移动路径、不可用网络下的依赖检查及实际转换。开发机验证不代表另一台无 CLT 的真机、所有 macOS 14+ 版本或下载隔离路径均已验收。

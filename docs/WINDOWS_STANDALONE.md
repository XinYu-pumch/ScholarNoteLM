# Windows 完整离线安装版

这是源码安装版之外的可选分发方式。完整包用于网盘分发；用户不需要 Git、系统 Python、Node、Rust、CUDA，也不必另取模型。初次使用仍需选择研究目录、配置自己的模型服务。PubMed、下载来源和远程 Embedding/LLM 仍需要网络；离线安装不等于所有业务离线。

## 用户安装

1. 下载 `ScholarNoteLM-<版本>-windows-x64-standalone-setup.exe`，可用同名 `.sha256` 校验。
2. 双击安装，默认安装到当前用户的 `%LOCALAPPDATA%\ScholarNoteLM-Standalone`。安装包包含完整 WebView2 安装程序，缺少时离线安装；C++ 运行库放在程序自己的目录，不要求安装系统编译工具。
3. 使用桌面或开始菜单的 **ScholarNoteLM Standalone** 启动。首次启动选择自己的研究目录并配置服务。

安装目录中，顶层 `ScholarNoteLM-Standalone.exe` 是独立版入口；`app/ScholarNoteLM.exe` 是与源码安装版相同的主程序。入口会修复 Python 虚拟环境中的绝对路径。不要绕过入口，也不要仅移动 EXE。移动完整安装目录后重新创建快捷方式，入口会按新位置修复路径。

不要安装到现有源码安装目录，不要装到需要管理员权限写入的系统目录。独立版与源码安装版分别保存设置；不要同时操作同一个研究项目。程序运行期间安装器拒绝覆盖。

卸载移除安装器登记的文件，不递归删除生成的配置、数据库、缓存或研究目录。重新安装同一版本保留这些用户文件。跨版本更新依赖时须先验证迁移；本版没有自动更新机制，不承诺任意未来版本可直接覆盖。

## 构建准备

在 Windows x64 上准备：

- 同一份源码对应的 `ScholarNoteLM.exe`、`source-manifest.json` 和 `dist/release/ScholarNoteLM-<版本>-windows-x64.zip`。构建器检查三者一致，并保留主程序的源码校验。
- 通过源码安装器准备的 Windows 运行环境，以及 `scripts/install/assets.json` 中全部模型和字体。
- 官方 Inno Setup 7 编译器 `ISCC.exe`。可在独立的项目工具缓存中安装，不属于最终运行依赖。
- 官方 WebView2 **x64 Evergreen Standalone Installer**，不是联网 bootstrapper；缓存名为 `MicrosoftEdgeWebView2RuntimeInstallerX64.exe`。
- Visual Studio 2022 Build Tools 提供的 `VC/Redist/MSVC/<版本>/x64/Microsoft.VC143.CRT`。

工具下载地址和已验证 SHA-256 记录在 `scripts/standalone/tools.json`。WebView2 官方地址会更新，如果哈希变化，应由维护者核对官方来源和 Microsoft Authenticode 签名后显式更新清单，不能自动接受新文件。不要从 `System32` 抽取 DLL 代替可再分发目录。

官方文档：

- https://jrsoftware.org/isdl.php
- https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution
- https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files

## 构建命令

在源码根目录执行，按本机 Visual Studio 版本替换 `--vc-crt`：

```powershell
runtimes\downloader\Scripts\python.exe scripts/build-windows-standalone.py --vc-crt "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Redist\MSVC\14.44.35112\x64\Microsoft.VC143.CRT"
```

可选 `--iscc <ISCC.exe>`、`--webview-installer <完整离线安装程序>`、`--stage-only`。默认工具路径为 `cache/standalone-tools/inno/ISCC.exe` 和 `cache/standalone-tools/MicrosoftEdgeWebView2RuntimeInstallerX64.exe`。

添加 `--include-cuda` 可同时打包源码安装器已准备好的 CUDA 环境和独立 CPU 回退环境。构建器核对 CUDA 环境与当前依赖锁的一致性，只复制受管理的环境；不会复制或安装系统 NVIDIA 驱动，也不会下载 CUDA。默认不带此参数仍生成 CPU 包。

CUDA 包会更大，首次安装和移动安装目录后，独立入口会一起修复 CUDA Python 的路径。每次打开 App 仍由原有应用逻辑检测实际可用设备；不兼容的 GPU 或驱动使用 CPU。每个包包含一个 CUDA 配置，具体 PyTorch 版本和驱动基线记录在安装说明与 `standalone-manifest.json`；本次 Windows 0.6.4 包为 `2.9.1+cu126`，不承诺该配置支持所有 NVIDIA 显卡（例如需 cu128 的新架构）。

CPU 包仍是单个安装 EXE。CUDA 与模型合并后超过 Inno Setup 的单 EXE 4.2 GB 上限，因此 CUDA 包输出安装 EXE 与配套 `.bin` 数据文件，并自动合成 `ScholarNoteLM-<版本>-windows-x64-standalone-cuda.zip`。网盘分发该 ZIP 及其校验文件；用户完整解压后双击 EXE，不能单独移动或只下载 EXE。所有依赖均在包内，不需要联网获取安装数据。

输出在 `dist/standalone/`：完整安装 EXE、SHA-256、文件清单、编译日志和独立 staging 目录。每次构建创建新目录，不修改现有运行环境，也不自动删除旧构建。打包器不联网、不安装依赖、不上传网盘或 GitHub。

构建包含公开源码、现有预编译主程序、运行时、锁定模型、字体、下载器所需的 Node 包、浏览器和第三方许可。排除真实配置、系统数据库、研究项目、下载记录、缓存、开发工具链、Git 信息，以及包含旧机器路径的 pip 命令入口。Python 的 `pyvenv.cfg` 在目标目录生成，不从开发电脑复制。

安装文件清单逐项生成，后续 staging 中出现的测试缓存或私人文件不会被通配符纳入安装器。`standalone-manifest.json` 记录每个打包文件的 SHA-256、源码提交和是否存在未提交变更。

原主程序及业务源码不因独立打包而改变。新入口、安装器模板和构建脚本只用于独立版；macOS 源码安装和 Windows 源码安装入口继续保留。

## 验证与发布

```powershell
runtimes\downloader\Scripts\python.exe scripts/test-windows-standalone.py
```

安装到 `tmp/` 下的全新目录后，可运行带中文/空格路径的安装验证：

```powershell
runtimes\downloader\Scripts\python.exe scripts/test-windows-standalone.py --installation "完整的临时安装路径"
```

此测试破坏并修复临时安装的 Python home，限制 PATH，污染继承的全局 Python 路径，使用不可用网络代理，然后校验全部文件、Python/Marker 导入和 Chromium 离线页面。不会访问用户研究目录。日常完整性检查可运行 `ScholarNoteLM-Standalone.exe --check`，日志在 `app/tmp/standalone-check.log`。

发布前还需验证独立版桌面启动、真实本地模型 PDF 转换、重启、目录迁移，以及卸载保留设置。独立的全新 Windows 机器/虚拟机、缺少 WebView2 的安装、Windows 10 和无开发工具环境须分别记录验收结果，不能用开发机测试代替。

当前 EXE 未进行 Authenticode 签名；正式分发可另行签名，然后重新生成校验值。目标为 Windows 10/11 x64（Intel/AMD），不包含 ARM64。

大包只通过网盘发布，脚本、模板、清单和本文放在同一 GitHub 仓库；源码配套 Windows 程序放在 GitHub Release。统一规则见 [上传与发布约定](RELEASING.md)。网盘同时提供校验文件和匹配源码入口。保留模型卡、字体及第三方许可；模型和 JCR 数据的许可不随主项目 GPL 自动改变，详见 `scripts/install/ASSET_NOTICES.md` 和 `THIRD_PARTY_NOTICES.md`。Mac 完整版需要独立的 Mac 构建、路径和签名验收。

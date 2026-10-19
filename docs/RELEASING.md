# 发布源码安装版

## 发布内容

- GitHub 仓库：源码、文档、依赖锁文件、安装清单、测试及维护者指定随附的 `services/reference/jcr/default-2025.xlsx`；保留第三方许可文件。
- GitHub Releases：与该源码版本一致的 macOS `.app` ZIP、Windows x64 EXE ZIP 和各自 SHA-256；同时附上匹配的源码 ZIP。仓库保留一个当前 Release，包含两平台可用产物。只附当前源码 ZIP。旧平台程序等待重编译时，必须在附件名与说明中明确旧版本不兼容当前源码，并提供历史源码标签；不能将旧二进制重新标成新构建。
- Mac 完整独立版：按 [构建说明](MACOS_STANDALONE.md) 提供内置环境与模型的 App，用户不依赖源码安装目录。完整独立包只保留本地或另行提供网盘，不上传 GitHub Release；GitHub 仅上传源码配套的小体积 Mac ZIP。
- 网盘：源码配套版的 `models/`，保留原始模型卡和许可说明。发布说明给出下载地址和版本；仓库的 `scripts/install/assets.json` 校验文件字节。
- 不上传本机 `config/`、`data/`、`workspace/`、运行时、缓存、日志、研究输出、资源备份 ZIP 或 `.git` 目录本身。

`services/downloader/resources/jina-embeddings-v4/tokenizer.json` 是有意保留的分词器资源，不是用户模型或研究数据。`services/marker/vendor/marker/config/` 是 Python 配置代码，区别于根目录含凭据的 `config/`。

## 发布检查

1. `git status` 确认无个人数据进入暂存区。运行 `scripts/audit-public-source.py` 检查可达 Git 历史的常见密钥格式、私人目录和大文件；报告只输出位置、不输出密钥。自动模式扫描不能证明不存在所有形式的敏感内容，新增示例和文档仍需人工检查。
2. 检查源码中示例路径、旧测试脚本和第三方许可；JCR 仅纳入指定的源码资源表，不上传本机 `data/reference/` 中的历史版本、索引或其他参考文件。第三方参考数据不因主项目采用 GPL 而改变原有许可。MeSH 可由用户从官方入口获取。
3. 完成 Python、Rust、前端、首次工作目录及隔离流程测试，再构建预编译程序。
4. 使用匹配源码和程序从干净目录安装，测试 Finder 启动、中文/空格路径、缺少模型提示、模型补齐后的离线转换、工作目录重连与重启。
5. 上传新产物并核对远端附件大小与校验和，确认保留的 Windows 原附件完整且已注明配套版本后，再删除其他旧 Release（保留历史 tag 和提交）。打 tag 后发布配套源码与程序；不要把程序 ZIP 放进 Git 历史。若源码发生变化导致校验不符，重新构建程序，不手动改校验清单绕过检查。

项目没有设置 GitHub 上传目标时，仅准备本地文件，不自动创建公开仓库、推送、上传网盘或发布 Release。

## 签名与平台

Windows 在 Windows x64 上运行 `runtimes\downloader\Scripts\python.exe scripts/build-windows-release.py`；ZIP 含主程序、环境安装引导、源码清单和许可证。当前产物未做 Authenticode 签名，发布前应在干净 Windows 机器验收环境安装、WebView2 缺失安装、目录迁移、中文路径及离线转换。Windows 10 最低目标还需对应真机验收。macOS 的发布流程继续独立执行；Windows 验收不能替代 Mac 回归。

当前构建脚本提供 macOS arm64 的 ad-hoc 签名，尚无 Developer ID 签名和公证。它不等于 Apple 认可的开发者签名。正式签名后需重新生成程序 ZIP 与校验值；不要在签名之后再修改包内容。

最低系统目标为 macOS 14，需进一步用对应版本真机验收。Intel Mac 必须准备独立的 Python wheel 锁、模型运行验证和 x86_64 程序，不能只给当前程序改名。

## 第三方代码与资源

Marker 适配源码在 `services/marker/vendor/`，包含 GPL-3.0-or-later 许可。源码公开、程序分发及修改版本应保留适用版权和许可材料。字体为 SIL OFL，原始声明见 `scripts/install/FONT_NOTICE.txt` 和 `FONT_LICENSE.txt`；模型许可与代码许可分别处理。主项目采用 GPL-3.0-or-later；第三方资源保留自身许可，不统一改为 GPL。

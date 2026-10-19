# Mac 独立应用

独立版把应用、配套源码、Python 依赖、Marker 模型、Node、Chromium 和字体装在一个 `ScholarNoteLM.app` 中。Apple Silicon / macOS 14+ 用户无需 Git、系统 Python、Node、Rust 或 Xcode，也不必另取 models。PubMed、远程 Embedding 和 LLM 仍需要网络与用户自己的服务配置。

## 使用

取得维护者单独提供的、名称包含 `macos-arm64-standalone` 的文件，解压后将 `ScholarNoteLM.app` 放到 Applications 或其他文件夹，打开即可。不要从压缩包内部直接启动。第一次启动选择研究工作目录并配置模型服务。

独立版的设置、数据库与运行缓存保存于 `~/Library/Application Support/ScholarNoteLM-Standalone/`；研究文献与稿件保存于用户选择的目录。App 包内资源不会在运行时改写。移动整个 App 后，启动入口会重新连接资源，设置不丢失。不要移动 App 内单个文件，也不要同时用两个版本操作同一工作目录。

独立版与源码安装版分别保存设置。不会复制开发者 API Key、历史系统配置或研究项目；原有研究项目应由用户选择其工作目录。替换 App 不删除设置；删除 App 也不删除研究目录。未来版本涉及存储格式变化时仍需单独做迁移验证，不承诺任意版本降级。

选择已有工作目录后，启动会自动识别其中有效的 `project.json` 并登记旧项目。此前已经选择目录但未显示旧项目的安装，更新 App 后重启即可补齐登记。重复 ID、损坏或不兼容的项目会提示，回收站内容不会恢复；识别过程不改写研究文件。详见 [项目存储](PROJECT_STORAGE.md)。

当前为 ad-hoc 签名，未完成 Apple Developer ID 签名与公证；首次下载运行可能被 macOS 安全检查拦截。仅在确认来源与校验和后，按 macOS 的“隐私与安全性”界面提示允许打开，不需要全局关闭 Gatekeeper。

## 构建与验证

在已准备好运行时、模型和开发工具的 Mac 源码目录中执行：

```sh
runtimes/downloader/bin/python scripts/build-source-release.py --standalone
```

先生成源码配套的根目录 App，再生成 `dist/macos-standalone/` 下的独立 App 和 ZIP。已有匹配源码配套 App 时可单独运行 `scripts/build-macos-standalone.py`。构建器校验模型、程序与源码；只复制公开源码和指定运行资源，拒绝指向包外的链接，不包含 Rust 工具链、Git、用户数据和配置。

```sh
runtimes/downloader/bin/python scripts/test-macos-standalone.py
runtimes/downloader/bin/python scripts/test-macos-standalone.py --app "/path/to/ScholarNoteLM.app" --state "$PWD/tmp/standalone-check"
```

后者使用包内 Python、隔离的用户状态目录、有限 PATH 和不可用网络代理，校验资源哈希、依赖导入与 Chromium 离线启动。开发者还应在解压副本中验证原生窗口、中文/空格路径、移动重启、实际 MPS 转换及隔离业务流程，不能用打包成功代替功能验证。`SCHOLARNOTELM_STANDALONE_HOME` 只用于指定独立版的状态目录，测试时必须指定 `tmp/` 下的隔离位置。

包内保留第三方和模型许可。GitHub 只存放打包脚本与源码；完整独立 App 保留本地或由维护者另行通过网盘分发，不上传 GitHub Release。Release 中的普通 Mac 程序 ZIP 是源码配套版，仍需要对应源码、运行环境和 models。

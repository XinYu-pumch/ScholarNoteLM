# 从干净源码安装

当前安装入口针对 **macOS Apple Silicon**。它从公开依赖仓库安装环境，使用仓库内的 Marker 适配代码；不需要 BADR，也不复制开发者的虚拟环境。Windows、Intel Mac 和 Linux 需要各自的依赖锁定与实机验证，不能复用此环境包。

## 保留现有安装

已经能正常启动的开发目录无需运行安装脚本。新入口不会由 app 启动自动调用，不修改旧启动脚本或缓存签名。

`setup-runtime.py` 默认只预览；即使加 `--apply`，发现未由它管理的 `runtimes/`、`node_modules/` 或 Cargo 环境也会拒绝覆盖。要试装，请另建干净源码目录。不要删除现有运行环境来绕过保护。

## 新用户安装

1. 取得干净源码，以及随该源码版本提供的 `marker-1.6.0-assets.zip`。
2. 安装 Apple Xcode Command Line Tools（`xcode-select --install`）和 [uv](https://docs.astral.sh/uv/getting-started/installation/)；验证时使用 uv 0.6.6。uv 是引导工具，之后应用使用项目内 Python。
3. 在源码根目录执行：

```sh
# 只预览
uv run --no-project --python 3.12 scripts/setup-runtime.py --assets /绝对路径/marker-1.6.0-assets.zip

# 安装到这个干净源码目录
uv run --no-project --python 3.12 scripts/setup-runtime.py --apply --assets /绝对路径/marker-1.6.0-assets.zip

# 检查安装；不调用模型 API，不读取研究项目
runtimes/downloader/bin/python scripts/setup-runtime.py --check

# 构建、启动
./scripts/npm-local.sh run build
./scripts/npm-local.sh run research:build
./scripts/npm-local.sh run desktop
```

安装包括 Python 3.12.9、downloader/Marker 环境、检索环境、Node 20.19.0、npm 锁定依赖、Playwright Chromium，以及本地 Rust 1.98.1 工具链。工具链安装不修改 shell PATH；使用仓库已有的 `npm-local.sh` / `cargo-local.sh`。`--without-dev-tools` 仅用于后端环境验证，跳过 npm、Chromium、Rust，不代表桌面已可启动。

依赖来自 PyPI/npm/Rust/Node 官方分发入口，安装过程需要网络。Python 依赖锁文件包含完整版本和包哈希；Node 与 rustup 安装器也校验固定哈希。安装器为下载子进程读取系统代理，保留显式设置的代理环境变量，不改系统或 app 配置。网络限制导致下载失败时，修复连接后可在同一安装目录重复执行；已校验的资源保留。安装器不会关闭 TLS 校验，也不会偷偷改装更新版本。

安装状态存于 `runtimes/install-state.json`。仅同一清单的安装可继续；依赖清单变化应使用新的干净目录，而不是覆盖正在使用的 app。完成安装不代表模型服务已经配置，LLM/Embedding 密钥由用户自行填写。

## 模型与字体资源

`scripts/install/assets.json` 列出模型/字体的精确相对路径、公开来源 URL、字节数及 SHA-256。模型版本与当前 `services/marker/vendor/marker/models.py` 一致，字体使用经哈希核对的 Go Noto v7.0 文件。Git 保留清单与代码，不存放约 2.2 GB 的模型资源。

不传 `--assets` 时安装器尝试清单中的上游地址。旧 Datalab 地址在验证时返回 403，因此当前推荐随源码提供匹配资源包。下载失败明确报错，不替换为其他版本，也不在日常离线转换时尝试补下载。

维护者可以从已有完整安装生成资源包：

```sh
runtimes/downloader/bin/python scripts/install_assets.py --output dist/resources/marker-1.6.0-assets.zip
```

导出器只读取清单内的模型与字体，逐文件校验后创建 ZIP，并重新读取 ZIP 验证。不会打包 BADR、Python 环境、配置、密钥、项目或缓存。安装器只接收清单中的具体文件，不直接解压 ZIP 提供的任意路径；不覆盖内容不同的现有文件。输出同名包已存在时拒绝覆盖。

资源包保留模型原始卡片、字体版权说明及 SIL OFL 文本。代码、模型和字体的许可证不同，见 [资源许可说明](../scripts/install/ASSET_NOTICES.md)。多数模型卡标注 CC BY-NC-SA 4.0，inline-math 卡片的声明不完整；技术验证通过不等于已完成公开/商业分发授权审核。

## 源码与发行版的边界

新安装使用独立环境；检索环境以相对 `.pth` 引用 Marker 依赖，解释器链接指向一起安装的本地 Python，不再记录开发者的用户名路径。不要把旧环境整体复制来替代安装器；旧安装中的绝对路径仍保留，以免影响正在使用的 app。

当前 Tauri 构建出的 `.app` 仍需要 ScholarNoteLM 目录中的 Python 服务、环境和模型。本次安装入口解决了从零准备这些资源的问题，**不会把旧 `.app` 自动升级成完整发行包**。后续制作发行版需选择整目录分发或调整 bundle 资源布局，并另行处理签名、公证、可写数据目录、升级和平台验收。

JCR 由用户加载有权使用的参考文件；MeSH 可在设置中下载官方词库。不会将开发者现有 `data/reference/`、JCR 文件或系统配置复制给新用户。缺失 Sci-Hub Bloom 时不承诺首轮命中筛选可用，原下载器仍保留补救路径。它们与 Marker 环境安装分别管理。

## 验证与维护

```sh
runtimes/downloader/bin/python scripts/test-runtime-setup.py
runtimes/downloader/bin/python scripts/test-runtime-conversion.py --root /绝对路径/新安装源码目录
```

第一项验证旧环境保护、资源哈希失败、路径隔离和离线包读取。第二项创建一次性项目和人工 PDF，通过真实独立 Marker worker 转换为原稿/清洗稿，不调用付费模型、不使用真实论文。后续工作流测试使用本机模拟模型服务，参见 [开发说明](DEVELOPMENT.md)。

macOS Apple Silicon 的干净环境已验证：624 项 Python 测试（4 项跳过）、37 项 Rust 测试、前端构建、桌面进程启动，以及综述、问答、向量和完整文献流程的隔离集成测试。整目录移动后检查解释器与资源，并重新执行真实离线 PDF 转换。该结果不替代其他平台或最终签名发行包的验收。

维护依赖时修改 `scripts/install/*.in`，在目标平台生成新的完整哈希锁文件，并从干净目录复验，不能直接把当前 `pip freeze` 中的所有旧包当作产品依赖。Marker 源码是仓库维护的适配版本；普通 PyPI 安装不能覆盖它。旧 `setup-marker-local.py` 只保留为历史环境导入工具，不是公开安装入口。

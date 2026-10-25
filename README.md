# ScholarNoteLM

本地优先的生物医学文献研究桌面应用：PubMed 检索 / Zotero 导入 → PDF 或摘要 → Marker 转 Markdown → 分块与 Embedding → 综述大纲、正文和文献问答。

项目分为**源码版**和**独立 App 版**：GitHub 仓库保存源码（含两平台独立版打包脚本），GitHub Releases 提供 Windows/macOS 源码配套预编译程序；完整独立版和单独的 `models/` 通过网盘发布。用户可直接安装独立版，也可取得匹配源码、预编译程序和 models 后安装环境使用。上传位置、版本对应及发布顺序统一见 [上传与发布约定](docs/RELEASING.md)。

支持 macOS Apple Silicon 与 Windows x64 的源码配套安装。Windows 用户将同版本发布包中的 `ScholarNoteLM.exe`、`ScholarNoteLM-Setup.exe` 和 `source-manifest.json` 放入源码根目录，再放入网盘提供的 `models/`，双击安装引导；日常直接打开主程序。具体步骤见 [安装说明](docs/INSTALLATION.md)。Mac 保留 MPS 加速；Windows 可选安装 NVIDIA CUDA 加速，默认自动检测设备，保留 CPU 回退。普通使用不需要 Rust、C++ 编译器或 CUDA Toolkit。

另有可选的 [Windows 完整离线安装包构建流程](docs/WINDOWS_STANDALONE.md)：将环境和模型一起打包为供网盘分发的安装 EXE。该流程新增独立入口，保留现有源码安装版和主程序；大型产物与个人数据不提交 Git。

Mac 用户也可使用 [完整独立 App](docs/MACOS_STANDALONE.md)：包内包含运行环境、模型与浏览器，无需克隆仓库或额外安装。设置保存在用户的 Application Support 目录，研究文件保存在用户选择的工作目录。

本文是使用与开发入口。按 **2026-10-26 的当前源码**核对，包版本为 `0.6.5`；版本号不代表旧打包副本已同步更新。开发约束见 [AGENTS.md](AGENTS.md)，功能细节见 [文档索引](docs/README.md)。文档与源码冲突时以源码为准。

## 1. 产品约定与已知边界

### 当前功能与约定

| 范围 | 当前行为 | 详细说明 |
| --- | --- | --- |
| 文献来源 | PubMed 记录及 PMID 是文献身份；检索式独立筛选、执行，合并去重；Zotero DOI 映射到 PubMed 后导入来源快照 | [检索与导入](docs/SEARCH_WORKBENCH.md) |
| 检索助手 | 流式讨论、MeSH 核验、检索式建议；用户加入并执行后才检索 PubMed | [检索助手](docs/SEARCH_WORKBENCH.md) |
| 全文获取 | 多来源下载、暂停/恢复/重试；没有全文时可用摘要，获取阶段完成不代表 PDF 齐全 | [下载](docs/PDF_DOWNLOADS.md) |
| Markdown | 固定 Marker、本地离线、禁用 OCR；只清洗参考文献，保留原稿、图片与编辑历史 | [转换](docs/MARKDOWN.md) |
| 索引与检索 | 段落分块、远程 Embedding、SQLite 向量缓存、余弦召回；项目独立绑定模型 | [向量化](docs/VECTORIZATION.md) |
| 综述 | 独立工作区、单份当前大纲、准备材料后联合撰写；续写保留完整片段，只补缺失单元 | [工作区](docs/REVIEW_OUTLINES.md)、[协议](docs/REVIEW_PROTOCOL.md) |
| 文献问答 | 新提问统一为项目范围主题问答，多轮召回与按需历史证据；旧概览记录保留 | [问答](docs/LITERATURE_QA.md) |
| 阅读与笔记 | 只读 PDF / 摘要、阅读位置、手写笔记、单篇全文对话；使用完整未清洗 Markdown 或摘要 | [阅读](docs/READING.md) |
| 导出 | 综述 JSON、Markdown、单文件离线 HTML、Word；保留证据、图表和引用绑定 | [工作区](docs/REVIEW_OUTLINES.md) |
| 资源与文件 | 系统配置/模型/运行时留在应用目录，研究项目可迁移到用户指定位置 | [存储](docs/PROJECT_STORAGE.md)、[生命周期](docs/ARTIFACT_LIFECYCLE.md) |

下列决定已经生效，不应依据旧规划恢复：

- 不内置演示项目；默认进入文献库。项目菜单提供切换、创建和永久删除。
- 项目文件夹和综述工作区名支持 1–64 个中文、英文字母、数字或下划线；不允许空格、连字符及 Windows 保留名，英文不区分大小写。
- GUI 不再提供 XML 上传、手动关联 PDF 入口；后端保留相应接口与旧来源读取。手工放入 `pdf/<PMID>.pdf` 后可执行本地文件检查，文件名对应关系由用户负责。
- 不恢复重排、BM25 / MedCPT、PaddleOCR、清洗策略开关、旧版单篇精读 RAG、Chroma。现有单篇全文聊天是独立功能。
- 综述工作区只有一份当前大纲，不提供工作区内的大纲版本管理。未迁移的旧 schema-1 布局直接报错；当前代码不会自动迁移它。
- 每个终末标题使用原文 query，不翻译中文、不拼接父标题；默认每节召回 7 块、写作并发 3。并发允许任意正整数，实际活跃请求不超过待写单元。
- 综述工作区独立运行，不使用项目级综述文件锁或等待队列；状态刷新、导出和其他工作区任务不阻塞当前生成。同一工作区仍检查活动任务与大纲修订号，取消按任务标识单独记录，避免被并发进度更新覆盖。
- 完整写作材料冻结文献与 Embedding 模型，切换项目模型或清空活动索引后仍可使用；未完成材料不能跨模型拼接。正文完成度与当前模型设置是否相同分开判断。
- 同版本重装后，选择保留的完整工作目录即可发现项目。Markdown 不因计算设备变化而过期；缺少 Embedding 配置/密钥时仍显示本地索引，重新配置同一端点、模型与版本后复用已有向量，不复制密钥到项目。不同模型索引保持隔离。
- 失效判定以实际输入为准。配置 ID、LLM 密钥/超时、并发、其他模型图片开关不让新产物过期；历史哈希须精确验证，不能猜测恢复为最新。旧签名键不得随意删改。
- 系统有 HTTP(S) 代理时跟随系统，没有时直连；分流由代理软件决定，不绑定 Clash。新请求适应代理变化，本机回环保持直连，已建立连接不强行迁移。
- 模型设置采用“设置分类 / 模型供应商 / 配置详情”布局，内置 DeepSeek、`opencode_go`、`z.ai`、`moonshot`、`mimo`、`qwen` 和 `grok`，各保留一份配置。新增五家在添加模型时自动载入对应思维预设，z.ai 和 moonshot 可在国内/国际官方地址间选择。DeepSeek 官方模型的思考参数在独立模块中实现。特殊请求头、端点、思考档位和各模型的思考输出策略在独立模块内实现（Go 的 Gemini、GPT、Muse、Claude 显式请求摘要）；普通 OpenAI 兼容配置不按名称自动转换；可逐模型手动选择 Gemini / DeepSeek / Qwen / GLM 以及 Claude / Grok / Kimi / MiMo / MiniMax 专用预设，或通用思考预设；Gemini、Grok、Claude 各只保留 `Gemini· Native`、`Grok· Native`、`Claude· Native`，分别使用 Google 原生、Responses、Messages 协议，其余预设沿用 Chat Completions；“服务端默认”不添加思考参数，由服务商决定默认行为，Generic Reasoning Effort 已删除。已删除的预设须手动重选，不自动迁移配置或切换协议。逐模型思考按钮打开弹窗，可设置强度和接口支持的思考输出；测试连接报告实际参数、思考文本及已报告用量，另可主动进行错误参数对照检查。见 [供应商维护说明](services/llm_providers/README.md)。
- 界面语言与内容语言独立；切换中文 / EN 不翻译已有研究内容。新内容默认语言只初始化新综述/对话；已有大纲另建另一语言综述，重试和分支沿用原轮次语言。
- UI 视觉与交互按 [Design System](docs/UI_DESIGN.md) 维护：聊天输入可达、状态反馈不挤动列表、设置分类固定、未保存草稿有离开保护。Zotero 下载地址及下载速度/超时默认只读，支持分组编辑、保存、取消和恢复默认。纯视觉修改只改样式。

### 输入、数量与质量边界

- **内置 2025 JCR 分区表**：随源码提供，首次使用自动校验并启用；保留用户已选参考表，也可上传替换或恢复默认。见 [检索规则](docs/SEARCH_WORKBENCH.md)。
- **PubMed 候选窗口保持 9,999**；EFetch 每批 100，直到符合摘要/JCR 条件的数量达标或候选耗尽。日期先由 PubMed 按发表日期限定；不足数量与候选窗口边界会在来源状态中说明，见 [检索规则](docs/SEARCH_WORKBENCH.md)。
- 检索助手发送当前分支全部有效历史，不设单条输入字符上限。文献问答和单篇全文对话也不设问题字符上限；问答历史材料按需取回，并非每轮重发全部旧材料池。
- 综述大纲与正文片段实时显示已接收的正文、思考字符数；正文计数仅在选中片段的详情中显示，不在累计进度下方重复列出；思考文本和摘要均单独计数，不混入正文。综述正文不设请求字符预算、不截断材料；`contextChars` / `limitContext` 仅保留历史签名兼容。大纲不限制标题数量、单标题字符数、CSV/响应总字符数或树深度，结构校验仍保留。
- 普通 OpenAI 兼容调用不发送应用侧输出 token 上限。Go 与普通 Claude 预设的原生 Messages 协议要求 `max_tokens`，使用模块登记的模型公开输出上限；其他协议不增加应用输出上限。服务商自身限制仍可能使请求失败。
- 取消 LLM 字符限制不等于取消 Embedding 的分块、配额、并发、重试或下载预算。各阶段仍按对应专题文档执行。
- 引用校验确认结构与来源绑定，**不保证论断科学正确**。大纲看到的摘要未必进入某节写作材料，跨节仍可能矛盾；中文 query 的效果依赖模型。短正文、资助和声明等按既定清洗规则保留，可能占用召回名额。
- 原文转换错误、图表拆分、缺失图注和模型误读不会由结构校验自动修复；目前不自动全篇事实审查。总结/改写的压缩程度仍需人工评价。
- 原有 Mac 开发以 Apple Silicon 为主；Windows CPU 与 CUDA 12.6 已在本机完成隔离 PDF 转换验证，Mac MPS 已通过隔离合成 PDF 转换验证。扫描 PDF 可能因 OCR 关闭而无正文；源码安装版支持 Apple Silicon / macOS 14+，完整签名公证和其他系统版本实机验收另行进行。

## 2. 启动与验证

普通用户按 [源码安装版指南](docs/INSTALLATION.md) 取得匹配的源码和预编译程序，双击 `install-environment.command` 准备运行环境，放入网盘下载的 `models/`，之后直接打开根目录的 `ScholarNoteLM.app`。无需系统 Python、Git 或 Xcode Command Line Tools；没有 Git 可以下载源码 ZIP。首次启动先选择研究工作目录，已有安装沿用原配置。源码版和独立版都会在启动时识别工作目录中的有效旧项目，补齐本机登记；无需重新创建项目或生成文献、索引和综述。

开发者在项目根目录执行（需要开发工具）：

```sh
./scripts/npm-local.sh run desktop        # Tauri 开发版
./scripts/npm-local.sh run research:build # Rust 研究桥接 CLI
./scripts/npm-local.sh run dev            # 浏览器调试
./scripts/npm-local.sh run build          # 前端构建
runtimes/downloader/bin/python scripts/build-source-release.py # 源码安装版 .app
```

不要同时启动独立 Vite 和 Tauri dev 争用 1420，也不要多实例编辑同一项目。前端热更新，Rust 按需重编译；已经运行的 Python worker 不热替换。日常预编译程序不使用开发服务器。旧 `.command` / `.cmd` 启动器已移除，开发仍可使用上述命令。见 [开发说明](docs/DEVELOPMENT.md) 和 [发布说明](docs/RELEASING.md)。

验证按改动范围选择，完整要求见 [AGENTS.md](AGENTS.md)：

```sh
runtimes/downloader/bin/python -m unittest discover -s services/downloader/tests
./scripts/cargo-local.sh test --manifest-path apps/desktop/src-tauri/Cargo.toml --bin research-cli
./scripts/npm-local.sh run build
```

涉及综述、问答、向量或完整流程时追加相应隔离集成脚本，见 [开发与测试](docs/DEVELOPMENT.md)。所有 UI 脚本先看再跑；有的连接已有开发服务，有的依赖旧的本机快照。使用 `tmp/` 下的 `SCHOLARNOTELM_ROOT` 和本地模拟服务，不能把真实项目当测试夹具。截图和结果 JSON 是忽略的运行产物，不提交。

## 3. 架构与代码入口

```text
React / TypeScript UI
  ├─ Tauri 原生模式：invoke / Channel → Rust research::dispatch
  └─ Vite 浏览器模式：/__research → research-bridge.ts → research-cli
                                                    │
                           Rust：PubMed、JCR、MeSH、检索助手、配置
                                                    │
                           Python RPC：services/downloader/engine.py
                                                    │
                 独立进程：下载 / Marker / 向量化 / 综述大纲 / 综述写作
```

没有需要手工常驻启动的通用 Python Web 服务。`services/downloader/` 名称是历史沿用，**里面不只有下载代码，综述与向量核心也在这里**。

| 修改目标 | 主要文件 |
| --- | --- |
| 页面导航、共享状态、保存 | `apps/desktop/src/App.tsx`、`context.tsx`、`storage.ts` |
| 前端 RPC、流式聊天 | `apps/desktop/src/research-api.ts` |
| 浏览器 RPC 桥接 | `apps/desktop/research-bridge.ts`、`vite.config.ts` |
| Rust 研究引擎 | `apps/desktop/src-tauri/src/research.rs` |
| 原生入口 / CLI | `apps/desktop/src-tauri/src/main.rs`、`src/bin/research-cli.rs` |
| 检索管理 / 助手 / 服务设置 | `SearchWorkbench.tsx`、`SearchChat.tsx`、`ResearchSettings.tsx` |
| 文献库及处理流程卡片 | `Library.tsx`、`LiteratureWorkflow.tsx`、`literature-workflow.css` |
| 下载 UI / API | `Downloads.tsx`、`download-api.ts` |
| Markdown / Embedding / 召回设置 | `Markdown.tsx`、`Vector.tsx`、`RetrievalSettings.tsx` |
| 综述工作区与大纲 | `Review.tsx`、`services/downloader/review_service.py`、`review_worker.py` |
| 综述正文、批次进度和重试 | `ReviewWriting.tsx`、`services/downloader/review_writing.py`、`review_write_worker.py` |
| BADR 提示词和片段格式 | `services/downloader/review_format.py` |
| 正文召回、Embedding 配置 | `review_retrieval.py`、`retrieval_settings.py` |
| 写作 LLM SSE / JSON 解析 | `review_llm.py` |
| 文献问答与设置 | `LiteratureQA.tsx`、`qa.css`、`services/downloader/qa_service.py`、`qa_worker.py` |
| HTML / Word 装配 | `review_export.py`、`review_export.css`、`review_export.js` |
| 下载与 Python 总入口 | `services/downloader/engine.py`、`badr_sources.py` |
| 工作目录与文件生命周期 | `storage.py`、`corpus_files.py`、`artifact_state.py` |
| 转换、清洗和 Marker 进程 | `services/downloader/markdown_service.py`、`services/marker/worker.py` |
| 段落分块、元数据与向量缓存 | `services/downloader/vector_chunks.py` |
| Embedding / 索引 / 限速 | `vector_service.py`、`embedding_limits.py`、`services/vectors/` |
| 主题 / 组件 | `tokens.css`（设计 token）、`design.css`（最后加载的组件层，规范见 `docs/UI_DESIGN.md`）、`styles.css`、`ui.tsx`、`Select.tsx` |

表中未注明路径的前端文件在 `apps/desktop/src/`；Python 文件在 `services/downloader/`。

## 4. 数据安全与维护入口

`config/embedding.json` 和 `data/research/research.sqlite3` 含明文凭据，不能打印、分享或提交。项目数据库不复制系统密钥，但研究正文和请求日志仍是用户资料。`workspace/` 及自定义工作目录未经明确要求不得修改、清理或调用真实模型。

运行时、Marker 模型和下载浏览器不是普通缓存。磁盘清理先查看 [本地维护](docs/LOCAL_MAINTENANCE.md)；自动清理工具不删除当前程序、研究数据或安装环境。新产物的日志压缩、XML 共享、图片快照与稿件去重见 [项目存储](docs/PROJECT_STORAGE.md)。

`main` 是主分支，新工作在分支中完成验证后合并。变更理由写入提交信息，不再新增按日期堆积的说明；已被现行文档取代的旧规划和实跑报告可从 Git 历史查阅。BADR 是历史设计参考，不是运行时依赖，也不应从中复制凭据。

## 5. 许可证

主项目采用 [GPL-3.0-or-later](LICENSE)。第三方代码、字体和模型分别遵循原始许可，见 [第三方说明](THIRD_PARTY_NOTICES.md)。

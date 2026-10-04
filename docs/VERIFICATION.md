# ScholarNoteLM 验证记录

> 本文件按日期保留历史测试记录，旧功能曾通过测试不表示它仍存在。当前测试结果见 [精简验证](APP_SIMPLIFICATION_20260928.md)；清理后的运行验证见 [清理报告](../logs/storage-cleanup-20260928/REPORT.md)。

## v0.4.0 PDF 下载 · 2026-09-19

- 下载引擎 13 项测试通过：正文/附件识别、S3 分页及前缀边界、多版本 current、PMID 冲突、PDF/MD5 校验、503 重试、重复批次保护、暂停/继续/取消、崩溃恢复、宿主退出暂停、默认关闭增强补救及开启后的回退顺序、Bloom 截断校验、已有 PDF 复用。
- Rust CLI → Python → 官方 PMC S3 实际链路通过：PMC4860105 下载为 27019327.pdf，2,111,028 字节、27 页，MD5 `8a84a83ba61a0aa6ae43ca0d1a20ea69` 与官方一致，未下载补充 PDF。
- Chromium 和 WebKit UI 检查通过：合并结果入口、设置开关持久化、文献库文件状态、版本/来源、报告、任务逐篇详情、浅/深色和 1000 px 窗口无横向溢出。没有浏览器运行时异常。
- TypeScript / Vite 构建、macOS Apple Silicon Tauri v0.4.0 调试包构建完成。项目内 Python 运行时为原生 arm64。
- 更新前备份旧应用与研究/下载数据库。已更新 dist/macos/ScholarNoteLM.app 并启动，原生窗口确认 v0.4.0 和既有研究集合保留；Tauri IPC 实际加载 PDF 下载设置，增强补救复选框为关闭。应用包本地 ad-hoc 签名校验通过。
- 真实下载和 UI 测试使用 tmp/pdf-live-verification 隔离数据，未对用户的 123 篇当前集合执行全量下载，未使用用户 LLM 凭据。
- 机器结果：DOWNLOAD_LIVE_TEST.json、DOWNLOAD_UI_TEST.json；截图：docs/screenshots/download-*.png。
- Windows 平台分支已实现但未构建或实机验证；本轮没有验证各外部镜像的实时成功率或大型文献批次吞吐量。PDF 转 Markdown 和向量化尚未接入。


## v0.3.1 消息与设置显示 · 2026-09-19

- 修复旧版结构化检索式只有标题、正文未显示的问题：完整表达式显示与单独复制可用，整条回答复制也包含表达式。
- 推理改为可访问的显式折叠按钮，测试流式到达期间手动收起不会重新展开，完成后默认收起，之后可自由展开/收起；旧版策略说明独立折叠，没有伪造旧记录不存在的推理。
- 全部选择器替换为统一自绘菜单；验证弹窗顶层、方向键、Home/End、Enter、Esc、文献库筛选、阅读切换、问答范围。
- 模型设置拆为宽度受限的连接卡片与生成卡片，1440 px / 1000 px、浅色与深色截图已检查，密钥输入框宽度断言通过。
- TypeScript / Vite 构建通过。Chromium 与 WebKit 26.6 界面回归通过，无页面异常；仅使用隔离数据和受控流式服务，未调用用户真实模型账号。
- 详细结果：`WORKBENCH_UI_TEST_RESULTS.json`、`WEBKIT_UI_TEST_RESULTS.json`。新截图：`settings-models-v031.png`、`model-dropdown-v031.png`、`legacy-message-v031.png`、`model-settings-compact-v031.png`。

## v0.3 检索式与聊天重构 · 2026-09-19

- TypeScript、Vite 生产构建通过；Rust 核心 8 项测试通过。
- 后端集成通过：单条独立筛选、默认 30 条、不限日期/JCR、多个来源的 JCR 条件合并、空草稿、XML 状态、密钥保留与脱敏。
- 本地 SSE 模型测试通过：接收到首批推理即实时显示；仅推理也判定连接成功；配置 10 秒等待超时而模型持续输出 12 秒仍正常完成；请求中不存在输出 token 上限字段。
- 对话测试通过：独立对话、分支、编辑/重生成保留原对话、取消后立即重发、截断流保存部分内容与错误提示。不使用真实模型密钥，未测服务商模型质量。
- Playwright 通过实际 Vite → Rust CLI → SSE 模型链路测试：新建直接加行、双击详情、独立筛选、模型下拉、流式推理自动折叠、Enter 换行、⌘/Ctrl + Enter 发送、编辑重发、重新生成、显式分支、新对话与刷新恢复。
- 1440×950 与 1000×720 窗口检查通过：聊天外层不滚动，输入框始终可见；浅/深色消息底色均已检查。无浏览器运行时异常。
- 真实 PubMed 回归通过：按单条检索式的数量与日期配置执行 ESearch/EFetch；3 条完整元数据、失败保留旧结果、零命中替换与历史全量模式均验证通过。
- v0.2 数据迁移测试通过：旧项目筛选复制到旧条目、旧聊天迁入独立对话；新条目继续默认 30 条，互不影响。
- macOS Apple Silicon v0.3 桌面包构建完成，已更新 `dist/macos/ScholarNoteLM.app` 并实际启动；原生辅助功能树确认新版单行检索工作台、真实旧条目和 v0.3 标识。Tauri IPC 读取正常。流式链路在浏览器/CLI 环境验证；未向用户的真实模型服务发测试请求。
- 更新前已在 `backups/` 保存旧版应用与研究数据库备份。Windows 未构建或运行验证。
- 截图：`workbench-queries-v03.png`、`settings-models-v03.png`、`workbench-chat-v03.png`、`workbench-chat-compact-v03.png`、`workbench-chat-dark-v03.png`；均来自独立测试数据。

## v0.2 检索工作台 · 2026-09-19

- TypeScript 类型检查、Vite 生产构建通过。
- Rust 核心测试 8 项通过：PMID/DOI 层级解析、缺少 PMID 拒绝、日期合法性、检索语法与字段检查、MeSH 同义词索引与规范字段解析、来源合并/归档/快照、模型地址路径。
- 后端集成测试通过：BADR JCR 22,249 行、缺失值兼容、错误文件不替换当前版本、多类别分区、去重与来源删除、草稿版本冲突、模型列表/连接协议、密钥脱敏与保留/清除。
- 真实 PubMed 测试通过：ESearch/EFetch 获得 3 条完整文献、错误字段不覆盖旧结果、零命中替换当前集合但保留快照、指定 PMID 的完整收集。
- 检索助手流程测试通过：受控模型服务提取概念，实际本地 MeSH 查词，模型返回结构化建议，真实 PubMed 试检索；不会自动改变集合，需明确加入草稿。没有使用用户密钥，未测试真实服务商模型的生成质量。
- MeSH 官方 2026 数据已真实下载、校验与索引：31,110 个主题词、76 个限定词、324,046 个 SCR，合计 355,232 条记录、996,332 个 Term 表达。再次检查确认未变化时复用当前索引。
- Playwright 界面测试通过：草稿、XML 导入、去重、归档/恢复、JCR 未匹配排除、文献库同步、XML 导出、模型配置、JCR 错误提示、浅色/深色、1000px 窗口无横向溢出；无页面异常。
- macOS Apple Silicon v0.2 调试应用构建成功，原生窗口启动与 Tauri IPC 读取工作台已确认。Windows 未构建或运行验证。

详细机器结果：

- `RESEARCH_TEST_RESULTS.json`
- `PUBMED_LIVE_TEST_RESULTS.json`
- `ASSISTANT_TEST_RESULTS.json`
- `WORKBENCH_UI_TEST_RESULTS.json`

截图在 `docs/screenshots/`；`workbench-ready.png` 和 `settings-mesh-ready.png` 使用真实应用配置，其他新增界面测试截图包含明确的测试文献，不用于学术引用。

超 10,000 条日期分区逻辑已实现，但本轮未发起大规模全量联网抓取；实际模型服务、PDF/MD/RAG 流程仍需后续配置和接入。

---

# UI 原型验证记录

日期：2026-09-19

## 构建

- TypeScript 严格类型检查通过。
- Vite 前端生产构建通过。
- Tauri macOS Apple Silicon 调试版构建和 `.app` 打包通过。
- 实际打开 `dist/macos/ScholarNoteLM.app`，原生窗口正确显示文献库和综述界面。
- 原生端调用 Rust 导出命令成功，Markdown 文件实际写入 `data/prototype/exports/`。

## 浏览器端流程验证

通过 `scripts/smoke-test.mjs` 验证：

1. 文献搜索、状态筛选、空结果、收藏与刷新后恢复。
2. 演示问答、证据不足回答、引用片段、来源阅读与笔记保存。
3. 综述编辑、大纲新增、生成期间人工编辑保留、实际 Markdown 导出内容。
4. 模拟任务取消、重试与完成。
5. 新项目隔离、示例检索添加、PubMed XML 元数据导入。
6. 深色主题保存与刷新恢复、390 px 窄窗口导航和无页面横向溢出。

最终测试未捕获浏览器运行时异常。

## 视觉检查

检查文献库、问答、综述、项目概览，以及浅色、深色与窄窗口布局。截图保存在 `docs/screenshots/`。

原生窗口另经 macOS 辅助功能树与截图检查，确认导航、表格、编辑器、存储状态和导出反馈可用。

## 验证中修正的问题

- 保存状态以最新完整状态是否落盘为依据，避免较早请求完成时误显示“已保存”。
- 演示生成结束时追加到最新正文，保留生成期间的人工编辑。
- 浏览器与原生端导出统一写入项目内目录。
- 主导航提供稳定的辅助功能名称。
- 提升桌面文献标题、正文和元信息的阅读字号。

## 范围限制

- 本次未在 Windows 上编译或运行，Windows 安装包尚未交付。
- 未执行真实 PubMed 网络检索、PDF 下载、全文解析、向量化或模型调用。
- 未验证大规模文献性能、多窗口并发编辑、正式发行签名/公证。
- 当前以单用户原型快照保存，暂不支持多个窗口同时编辑。
- 视觉方案已经实现，是否作为最终风格仍待用户评审。


## 0.5.0 项目存储更新

- 13 个下载测试、8 个 Rust 测试及研究服务集成检查通过。
- 项目迁移集成检查通过：38 篇当前文献、22 份 PDF、检索历史与下载报告保留；项目数据库不携带模型密钥。
- 按当前 XML 打包、失败保留旧包、清空当前项目范围、外部工作目录迁移及迁移后的真实后台进程写入通过。
- Chromium 与 WebKit UI 检查通过：新建项目目录、工作目录迁移、重启保存、打包、清空确认取消、浅深色紧凑布局。
- macOS 原生 0.5.0 已构建、替换并签名；真实数据迁移后核对 39 个 PDF/摘要文件哈希一致。
- 真实项目未执行清空；恢复备份位于 backups/storage-migration-v1。
- Windows 未实机运行。

## 0.5.1 Bloom 延迟补救

- 下载引擎 24 项测试通过（原有 13 项 + 新增 11 项）：502 后补救成功、疑似验证页后 PMC 补全即停止 Sci-Hub、永久证书错误不重复、同域入口故障不影响文件下载、Retry-After 秒数/日期与健康状态恢复、补救次数上限、长限流延期、等待中暂停恢复、请求中断后预算保留、总预算取消慢请求、手动补救只选择当前集合内缺失有效 PDF 的已命中文献。
- Chromium / WebKit 均通过：实际 Rust RPC → Python 的手动补救筛选、报告、等待状态和次数、未完成批次按钮禁用、浅深色及 1000 px 无横向溢出。网络来源在隔离测试项目中关闭；运行中的等待状态由 UI fixture 提供，后台等待/暂停由引擎测试覆盖。无页面异常。
- TypeScript / Vite 与 macOS Tauri 0.5.1 构建通过，更新 `dist/macos/ScholarNoteLM.app`，签名验证通过并已启动。原生窗口确认 0.5.1 与原有 38 篇纳入集合正常加载。
- 升级前保存应用和下载数据库到 `backups/v050-before-retry`；升级前后 73 个项目 XML/PDF/Markdown 文件 SHA-256 一致。未清空或重试真实项目下载。
- 参数是初始值，尚未通过真实镜像吞吐量对比验证；未向镜像发送本轮测试请求，未验证实时下载成功率。Windows 未实机验证。
- 机器结果：`RETRY_VERIFICATION.json`、`RETRY_UI_CHROMIUM.json`、`RETRY_UI_WEBKIT.json`。截图：`screenshots/retry-tasks-*.png`。

## 0.5.2 调度回归修复

- 29 项下载测试通过；新增 38 篇多条目竞争、全镜像 429 延期、等待不消耗 HTTP 预算、不同 DOI 故障阈值与旧冷却状态迁移检查。
- 同一个 17 篇 Bloom 命中 + 21 篇未命中的回归测试，加载 backups/v051-before-scheduler 中的旧代码可复现失败，修正后通过。结果保存在 SCHEDULER_REGRESSION.json。
- 使用实际 curl_cffi 客户端访问本地 HTTP 测试服务器：首轮 17 篇均实际访问两个入口（34 次），第二轮这 17 篇全部在非命中文献之前成功，随后处理 21 篇未命中条目。未发送外部镜像请求；记录见 SCHEDULER_HTTP_TEST.json。
- Chromium / WebKit 界面通过：延期状态显示、延期条目的实际 RPC 重试、请求预算说明、手动 Bloom 筛选、等待状态与按钮禁用。TypeScript / Vite 与 macOS Tauri 0.5.2 构建通过。
- 应用更新到 dist/macos/ScholarNoteLM.app，ad-hoc 签名检查通过，原生启动确认 0.5.2 与原有 38 篇集合。升级前后 73 个项目 XML/PDF/Markdown 哈希一致；应用和下载数据库备份位于 backups/v051-before-scheduler。
- 没有自动重跑真实项目下载；外部镜像验证码、限流与实时下载成功率不在本轮受控验证结论中。Windows 未实机验证。


## 0.5.3 S3 前置与固定下载队列

- 下载测试 42 项通过。覆盖 S3 成功跳过其他来源、S3 总时限、Unpaywall 持续缓慢传输/候选切换/整篇时间预算、增强慢速补救默认关闭、第三个 Sci-Hub 镜像成功、每镜像入口串行且不同镜像并行、跨进程入口互斥与退出释放、暂停恢复预算、38 篇分组补救和真实请求计数。
- 本地 HTTP 集成使用真实 curl_cffi/httpx 客户端：同一镜像入口并发峰值 1，不同镜像整体并发峰值 2；17 个 Bloom 命中文献首轮各访问两个镜像，第二轮先于 21 个未命中文献完成补救。持续返回少量数据的响应在测试总时限到达后取消，部分文件清理成功。未向外部镜像发送测试请求。
- Chromium、WebKit 检查通过：实际 RPC 手动补救与延期重试、更新后的来源顺序与预算说明、总时限默认值和修改后的实际保存、增强补救默认关闭、1000px 深色布局无横向溢出。
- TypeScript/Vite 与 macOS Tauri 0.5.3 构建通过；已更新 dist/macos/ScholarNoteLM.app，ad-hoc 签名验证通过。原生窗口确认 0.5.3 与原有 38 篇集合。
- 73 个项目 XML/PDF/Markdown 文件哈希不变。旧应用、引擎、界面文件和下载数据库备份在 backups/v052-before-s3-first。
- 没有自动重跑用户项目下载；实时站点成功率和新顺序的实际总耗时仍需真实批次观察。Windows 未实机验证。汇总见 S3_FIRST_VERIFICATION.json。

## 2026-09-20 · 综述正文与方案 7

- 综述工作区移除版本 UI；旧 `versions/` 与其中的 benchmark 保留，当前大纲迁至工作区根目录。
- 当前 gut/test1 核对：162 个标题、109 个终末标题、45 个 BADR 写作单元；迁移前后当前 CSV 字节一致。
- 28 项综述测试、13 项分块/向量测试、7 项文件生命周期测试通过（合计 48 项）。覆盖混合深度、稳定 ID、引用范围、修复、并发上限、来源变化拒绝发布、取消保留、过期状态及 MedCPT 缓存清理。
- 真实 Rust RPC + 独立 Python 大纲 worker 集成测试通过：流式响应、取消、无效 CSV/断流不覆盖现有大纲、原始大纲恢复。
- 正文集成测试加载真实本地 MedCPT Article/Query 和 Qwen3-Reranker，使用隔离的 9 篇测试摘要与本机模拟 LLM，完成 4 个终末查询、3 个写作单元，每个终末查询返回 7 块。验证继续时跳过最新内容、三种导出、取消 HTTP 等待且保留完成正文、产物不含测试密钥。
- 本地检索禁止所有 socket 连接，对冻结实验 `1.1.1_leaf` 的相同 50 个候选重跑，新实现 Top 7 及顺序与原方案 7 完全一致。
- Playwright 实际页面测试通过：工作区迁移、无版本控件、双标签、默认并发 3 / 文本块 7、完整 162 节目录、空证据、全文预览、1100px 窗口无横向溢出、无浏览器异常。
- TypeScript / Vite 构建通过；仍有既有主 bundle 大于 500KB 的体积提示。
- 开发版已运行，源码热更新可用。本次未调用用户配置的远程 LLM，未替用户批量生成正式正文；Windows 尚未实机验证。

运行日志：`logs/review-writing-unit.log`、`logs/review-writing-integration.log`、`logs/review-retrieval-parity.log`、`logs/review-writing-ui.log`、`logs/review-writing-build.log`。

## 2026-09-20 · API 召回与分步综述

- 按最终要求移除正常流程中的 BM25 / MedCPT 召回，历史代码和模型保留；原始终末标题直接发给已验证的 Embedding API。
- 默认无重排；候选数量遵循直接 Top K 或 max(候选数量, Top K)，Qwen3 可选、只在准备阶段加载。
- 30 项综述测试、13 项向量测试、6 项 Embedding 连接测试、6 项检索选项/限速测试、7 项工件状态测试通过（共 62 项）。
- 真实 Rust RPC → 独立 Python worker → 本机 Embedding / LLM 测试服务通过：4 个中文原文查询、3 个混合深度单元、Top 7；准备阶段没有写作 LLM 请求，写作阶段不重复召回，发送内容与 prompt_section 文件完全一致，section JSON、3 种导出、断点复用、取消保留正文均通过。
- 在全部 socket 连接被禁止的情况下，实际 Qwen3 对冻结 50 候选重排的 Top 7 与先前实验完全一致，约 12 秒。此项只验证重排一致性，不代表新 API 召回的医学质量评估。
- Playwright 读取真实 gut 工作区（162 节点）验证两个阶段按钮、无并发上限、保留用户已有并发值、候选数仅在设置页、默认不重排、1100px / 1600px 布局及无浏览器异常。截图见 docs/screenshots/。
- TypeScript 检查和 Vite 构建通过；已有 bundle 大小提示不阻断构建。开发版已启动。
- 测试未使用用户远程 API 密钥，未生成用户真实综述正文。Windows 未实机验证。

## 2026-09-20 · BADR 综述文件与导出对齐

- 直接移植 BADR 的分段提示词、单节点引用修复提示词与引文标点规范化函数；公开 JSON 为同名 6 个字段，数字标题编号映射至内部稳定 ID。
- 35 项综述单元测试通过；真实 Rust RPC、两阶段 worker、本机 Embedding / LLM 集成测试通过，未调用用户远程服务。
- 使用 BADR 提供的 section_1.json 导出样例：Playwright 验证三栏、PMID 点击、当前小节素材和 PubMed 链接；LibreOffice 成功将新 Word 转换为 PDF 供视觉检查。
- Python 依赖 python-docx 1.2.0 / Markdown 3.10 已加入项目 requirements 和本地 downloader 虚拟环境，安装缓存保存在 app/cache/uv。
- 现有提示词与正文保留；新的格式指纹会提示重新准备。

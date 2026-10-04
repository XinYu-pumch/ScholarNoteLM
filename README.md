# ScholarNoteLM

以 PubMed 文献集合为基础的一站式研究桌面应用：检索与项目管理 → 获取 PDF / 摘要 → 本地 Markdown 转换 → 文本块与向量检索 → 综述大纲和正文撰写，以及基于项目证据的多轮文献问答。

**本文是新开发者 / 新 Codex 对话的接手入口。** 最后核对：**2026-09-24**。包版本仍为 `0.6.0`，不能仅凭版本号判断功能进度。当前主要在 **macOS Apple Silicon 开发版**上运行；Windows 是目标平台，尚未实机验证或提供已验证安装包。

## 1. 接手先读：现在做到哪里了

当前应用已有真实检索、下载、转换、向量化和综述生成流程，**不是只有 UI 的原型**。文献问答已接入真实多轮检索；部分阅读展示仍含原型逻辑，不能把演示数据当作真实研究结果。

| 模块 | 当前状态 |
| --- | --- |
| 项目与存储 | 项目目录可由用户选择；系统资源与项目产物分离 |
| 检索工作台 | 每条检索式独立筛选、执行，按 PMID 去重合并 XML |
| 检索助手 | 真实 LLM 流式聊天，设计检索式；分支、编辑重发、新建/重命名/删除对话 |
| JCR / MeSH | JCR 上传校验；官方 MeSH XML 构建本地索引、应用运行期间自动检查更新 |
| PDF 下载 | 真实多来源下载、镜像队列、暂停/恢复/重试、逐批次报告 |
| Markdown | 固定使用 Marker，内置仅清洗参考文献；原稿与替换历史保留 |
| 文本块 / 向量 | 段落拆分、Embedding API、Chroma、向量缓存、可视化文本块调试 |
| 综述大纲 | 基于摘要的真实 LLM 生成，完整树编辑、CSV 校验、导出完整提示词 |
| 综述正文 | Embedding API 正文召回；先准备提示词，再生成片段、按大纲装配 |
| 导出 | BADR 风格片段 JSON、Markdown、带引用详情的 HTML、Word |
| 文献问答 | 项目范围 agent 取证、可选 RCS、三模型角色、逐篇阅读、流式回答与证据快照 |

### 当前有效的产品决定

以下约定来自已确认的需求；不要根据早期规划或遗留代码反向恢复旧方案：

1. **PubMed 是文献条目的唯一来源**，以 PMID 作为文献身份。允许导入 PubMed XML、补充以 PMID 命名的本地 PDF。
2. **先使用开发版，不为每次修改重新打包。** 旧 `dist/macos/ScholarNoteLM.app` 不会随源码更新。
3. 系统模型、运行时、依赖、参考数据、配置、可配置缓存留在应用根目录；项目数据由用户指定工作目录。
4. 项目文件夹及综述工作区名称只允许 **1–64 个英文字母/数字**，不要求两者都出现；不允许中文、空格、下划线、连字符及 Windows 保留名。显示名称/描述可中文。
5. 每个综述工作区只有一份当前大纲，**不再提供工作区内的版本管理**；历史 `versions/` 保留但不继续作为新功能入口。
6. 大纲深度不预设上限；导出格式受 Markdown/HTML 六级标题、Word 样式层级限制，但必须保留完整编号和所有节点。
7. Query 使用**终末标题原文**；中文不翻译英文，不默认拼接父标题。
8. 正常综述召回使用**已保存且验证通过的 Embedding API**，常用 `Pro/BAAI/bge-m3`；BM25、MedCPT 的执行代码和模型已移除。
9. 不提供重排；Qwen3 重排代码和模型已移除。
10. 每节默认 7 个文本块、写作并发默认 3，放在综述撰写页；并发允许任意正整数，不设人工上限。直接返回 topK，不设置额外候选池。
11. 单次写作请求字符预算**默认关闭**。兼容字段 `contextChars=90000` 仍保留，只有 `limitContext=true` 才生效。不向聊天模型发送应用侧 `max_tokens` / `max_completion_tokens`。
12. 保留已经确认的段落分块方法。内部 metadata 支撑追踪、去重和失效判断；**给写作 LLM 的素材仅需 PMID + 原文**，不要因此删除数据库内部必要字段。
13. PDF 下载尝试结束但未取得全文，有摘要时可视为获取阶段“最新”，后续使用摘要。**获取阶段完成不等于 PDF 存在**。
14. 用户要求现代、紧凑、优雅的 UI：统一自绘下拉菜单、对齐卡片、减少口号和冗余说明；聊天输入框始终可见。

### 2026-09-28 界面与模型精简（当前有效）

对话侧栏统一收窄，两种对话均有按提问编号的目录。模型选择、视觉能力、默认模型和连接/图片测试合并；Embedding 配置管理启用状态及 RPM/TPM。文献库“更多”使用独立浮层。转换固定 Marker，内置仅参考文献清洗；删除 PaddleOCR、MedCPT、BM25 排序、Qwen 重排和主题问答自动补入全文。主题问答采用与综述相同的正文召回与位置关联图表，共享历史正式回答，按需读取历史引用。重试原地替换当前消息，保留尝试日志；多个对话可同时生成。

实施、迁移和验证见 [精简记录](docs/APP_SIMPLIFICATION_20260928.md) 与 [当前问答上下文](docs/QA_CONTEXT.md)。以下带日期条目是历史记录，冲突时以本节为准。

### 历史更新记录

以下记录描述对应日期的版本。旧清洗策略、重排选项、补读全文和部分对话行为已被 2026-09-28 的实现取代；请按现行功能文档操作。

### 2026-09-22 PubMed 书籍章节 XML 兼容

修复 `PubmedBookArticle` 被忽略导致整批检索报“部分文献元数据未完整返回”的问题。PubMed XML 可混合期刊文章和书籍章节，两者都按主体 PMID 解析；保留书籍章节的原始 XML、章节作者、书名、摘要和章节日期，不将参考文献中的 PMID/DOI/PMCID 当作本条身份。同步覆盖当前文献集合、摘要、向量索引、下载发布校验、Zotero 与打包。真正的记录不匹配会显示请求/解析数量及缺失/额外 PMID，原始批次保留。

在《HUS与基因》保存的 5 份批次 XML 上离线重放，30/40 条均完整导入及进入下游读取；未修改真实项目结果。回归入口：`scripts/test-pubmed-books.py [XML文件...]`、`services/downloader/tests/test_pubmed_books.py` 和 Rust parser tests。

### 2026-09-22 Agent 阅读与可选 RCS（历史记录）

- 所选范围的全部有效文本块始终参与向量召回，不先筛论文，不引入独立 reranker，不继承综述 Qwen3 设置。
- **RCS 默认关闭**：每个 query 直接召回 `b=topK`（默认 8）块，不调用证据模型评分/整理。开启后，每个 query 召回 `a=rcsCandidateK`（默认 24）块，由证据模型按用户问题评分、生成上下文摘要和连续摘录，保留最多 b 块；a 必须 ≥ b。评分是相关性，不是研究质量。多 query 合并按块 ID 去重；读取上下文可追加原文。
- Agent 选择搜集证据、读取上下文、精确定位、检查覆盖或生成回答；取消固定的每轮摘录和双模型回答前复核。保留规划/充足性决策，但关闭 RCS 时直接检查原文。语义检索默认最少 1 / 最多 3 轮，读取动作另受默认 12 步、每步最多 6 项限制。
- 输入区提供主题问答、单篇精读、项目概览。后两者直接分批阅读每篇已准备的文本块，不依赖论文/块的向量 Top-N；没有已准备文本的论文标为未准备，摘要单独标记。界面区分范围、完整读取、入池、引用与未完成阅读。逐篇阅读本身不打相关性分数。
- 三种可独立选择的模型角色：检索规划、证据阅读、回答；前两者留空时沿用回答模型。证据模型默认并发 3，用于 RCS 和逐篇阅读，普通主题问答关闭 RCS 时不调用此角色。
- 证据卡保留来源版本、上下文说明、反证/背景/限制关系、原文摘录及偏移。评分或摘录格式无效时退回未评分原文，不把格式失败算作无关；已明确无关的材料不为凑 b 强行补入。RCS 成功卡按问题、历史、要点、模型、原文及提示版本缓存。
- 已完成模型响应、query 向量保存检查点。失败/取消/中断的消息可“继续未完成步骤”：创建新的运行并复用完全匹配的已完成工作，保留原记录；源文件、范围、配置或流程版本变化则拒绝恢复，需重新生成。取消和来源变化仍阻止发布。
- 回答前冻结可引用的材料，生成后做本地引用范围校验，默认不追加模型深度核查。材料容量不足时明确标记节选和省略；逐篇已读不表示全部原文都进入最终回答。

实现、参数、测试与限制见 [Agent 阅读重构](docs/QA_AGENT_20260922.md)。以下 9 月 21 日的固定循环和双模型描述是历史行为，以本节为准。

### 2026-09-22 文献问答侧边对话管理

文献问答改为与检索助手一致的左侧对话列表：新建、切换、重命名、删除集中在侧栏，分支带独立图标，当前对话高亮。顶部只保留当前标题和模型选项，移除对话下拉菜单。侧栏可收起/展开，窄窗口保持输入区可见。已有对话、分支和引用快照不迁移、不改写。

### 2026-09-21 对话管理、Embedding 多配置与界面整理

- 文献问答的每条已结束回答提供复制、重新生成、从此处分支；重新生成会在该问题之前分叉，再用当前模型配置回答原问题，保留原对话及原范围。问答与检索助手都支持新建、重命名、删除对话。删除不影响已建立分支及其引用快照。
- 新生成消息和模型选择使用 `配置名称/模型名称`；配置名禁止重复。历史记录若未保存配置名称，保留原模型 ID，不猜测来源。
- Embedding 支持具名多配置、新建/删除、获取模型列表、手动填写模型、独立验证及密钥显隐。常规读取只返回密钥是否存在；点击眼睛后才读取明文。旧单配置读取兼容，首次保存时迁移，模型缓存身份保持不变。
- “召回与重排”选择已保存并验证的 Embedding 配置，文献向量化和查询召回共用该选择。保存其他配置不会自动切换当前配置；切换模型不会删除缓存，已有对应模型的有效缓存可复用，新模型缺失的向量需正常建立。
- 数字输入使用编辑草稿，删除全部数字时保持空白，失焦时恢复上次有效值，不再立即填入 0；温度仍可清空为服务默认值。macOS `Cmd+,` 打开设置。
- PDF 下载设置精简说明，Zotero、并发与请求参数、Sci-Hub 镜像、Bloom 索引归入默认收起的“高级”，后两者分别展开。“开放获取”说明邮箱无需注册 Unpaywall；“增强补救”仅提示开启后延长下载时间。
- Markdown 设置仅提供“保守清洗方案”，新配置默认启用段落清洗，去除旧 BADR 与额外删行控件；保存时清除额外删行规则，不自动重新清洗现有原文。旧算法仅保留历史兼容实现。
- 全局使用低饱和灰绿层次、浅色内容卡片和局部深色重点，覆盖设置、聊天和综述工作台；模型配置的新建/删除按钮同排同样式。

验证与存储细节见 [本次界面与配置更新](docs/WORKSPACE_POLISH_20260921.md)。

### 2026-09-21 文献问答与供应商多模型

- 文献问答使用当前项目或选定 PMID 的真实原文，替换演示入口。默认每个 query 8 块、每轮最多 3 个 query、最少 1 / 最多 3 轮（包含首轮），可在设置修改；**问答不使用 reranker**。
- 支持相邻块、论文章节、精确词语、文献元数据工具；保存每轮查询、证据和停止原因。只生成 query 向量，不因提问隐式向量化整个项目。有效缓存可复用，不要求 Chroma 发布登记已完成。
- 结构化输出增加独立协议适配：接受唯一完整 JSON、代码围栏和已知完整 DSML 调用标签，再做阶段字段和工具参数校验。错误格式每次调用最多修复一次、整次问答最多 2 次、额外请求累计最多 60 秒；原调用网络错误、取消和输入变化不按格式错误吞掉。修复仍失败时按阶段退回原问题检索、保留原文或停止补查作有限回答，界面明确显示未完成步骤。材料过长时标记原文节选及未送入回答模型的块，完整快照保留。
- 工具过程实时推送：显示规划输出、每轮补查理由、实际 query / 查找词、命中证据与状态。摘录的大小写/空白差异会定位回原文；实质不匹配时仅修复或舍弃该摘录，不因单条摘录中止全部问答。问答与检索助手统一调整了消息、工具与警告的配色和对比度。
- 检索规划、缺口判断和回答前核对均逐项校验 query / 工具参数。模型只返回 `["exact"]` 等不完整调用时，记录缺项并跳过该项，保留其他查询和已有证据，错误反馈给后续规划；不猜测缺失查找词。取消、原文/配置变化等错误仍中止发布，不能被工具容错吞掉。
- 检索模型与回答模型分别选择，可共用一个模型或选择同一供应商下不同模型。供应商配置支持获取列表后多选、手动添加和默认模型；地址、密钥、温度、超时对其全部模型共享。旧单模型配置兼容，检索助手和综述继续使用默认模型。
- 引用 `[E1]` 对应本轮具体块，点击查看原文快照、PMID、章节和文本行号；没有可靠 PDF 页码映射。证据不足和语义核查问题明确展示，模型辅助核查不等于科学事实证明。
- 配置页连接测试与问答共用 Python 流式客户端，可独立选择要测试的具体模型，不改变默认模型；等待完整正文，仅收到推理不算通过。连接建立失败最多自动重试一次；收到响应后的断流不重发。问答保存失败阶段、底层异常类型、主机和尝试次数，避免只显示笼统的网络错误。
- 问答逐阶段流式显示接口提供的 `reasoning_content` / `reasoning` / 文本型 `reasoning_details`，与正式输出分开，运行时展开、完成后可回看；不推测接口未提供的内部推理。超时按连续无网络数据计算，持续收到推理或心跳不因缺少正文而断开。
- 检索工作台“执行全部”按当前列表顺序逐条获取 XML，一条完成后等待 2 秒再开始下一条；跳过禁用、归档、空白检索式及已导入 XML，失败停止后续执行。离开页面停止派发后续检索。侧栏宣传卡片已移除，浅色模式用低饱和灰绿深色强调当前导航、用户消息、主要按钮与检索表头。
- 回答后的模型深度核查改为**可选、默认关闭**；摘录与引用编号校验始终启用。开启后明确显示正文已生成、核查进度与耗时，总等待最多 60 秒，超时保留回答并标记核查未完成。历史核查意见保留，界面可展开逐条对照来源。
- 支持取消、对话历史和 Markdown/证据导出；源文件/配置变化阻止发布。项目清理等待问答停止，活动问答阻止删除项目。旧原型 messages 保留但不当作真实问答。
- 已用隔离项目、本机模拟 LLM/Embedding 和真实 Rust RPC/worker 验证。尚未进行用户真实服务的速度/质量评测；逐篇阅读已在 9 月 22 日接入，笔记联动和 PubMed 外部扩展仍为后续范围。

实现、参数与验证入口见 [文献问答](docs/LITERATURE_QA.md)。

### 2026-09-20 工作区与文献流程更新

- 导航：项目概览 → 检索工作台 → 文献库 → 综述工作台 → 文献问答 → 阅读与笔记。概览仅统计当前项目，索引/综述统计来自真实服务。
- 综述主题、大纲默认只读；点击“编辑”进入草稿状态，保存退出或取消。新建工作区可选择 LLM 或 CSV 文件；CSV 校验通过后原样保存为 `imported.csv`，规范化大纲保存为 `outline.csv`，支持恢复导入原稿。
- 文献库主按钮为“一键更新文献”，由独立后台进程依次同步文件、增量下载、转换、索引。三个卡片按钮各自只执行一个阶段；单独转换不再受旧 `autoIndex` 设置影响。每张卡片的“更多”提供维护操作。
- 清空 PDF / Markdown 会级联清空下游；清空索引同时删除 Chroma、Embedding 缓存和文本块。先停止并等待相关任务退出，XML、笔记和已有综述保留；提示词准备状态失效。轮询不自动重建清空的数据。
- “重建 Chroma 索引”复用有效向量缓存；“强制重新计算向量”显式清除当前模型缓存后重算。metadata 更新不改变 Embedding 输入时只同步 metadata；篇名属于 Embedding 输入，实际改动会更新对应向量。
- Chroma 同步完整篇名、作者、期刊、发表日期、章节路径等字段；SQLite/JSONL 保留完整嵌套 metadata。日期保留来源精度，不补造月日。详情显示完整篇名，并可复制完整 metadata。

实现及验证记录见 [工作区与文献流程更新](docs/WORKSPACE_UPDATES.md)。以下旧流程描述与这里冲突时，以本节为准。

### 推荐阅读顺序

先读本文的架构、数据约定、综述实现和最近审查，再按任务阅读对应源码。`PROJECT_PLAN.md` 和部分 `docs/` 是历史阶段文档，存在过期描述，例如“综述未接入”“MedCPT/方案7”“默认90000字符限制”及旧 `data/projects/` 路径。**当前需求与实际源码优先；不要把历史方案编号当作实现规格。**

2026-09-28 已同步主要功能与开发文档；阅读入口见 [文档索引](docs/README.md)，磁盘清理与运行依赖见 [本地维护](docs/LOCAL_MAINTENANCE.md)。早期规划与日期记录仍保留，但不能作为当前操作说明。

## 2. 日常运行与开发

所有命令在应用根目录执行。本机路径为：

```text
/Users/yuxin/AI_developing/ScholarNoteLM
```

### 启动现有开发版

双击 `开发启动 ScholarNoteLM.command`，或：

```sh
./scripts/npm-local.sh run desktop
```

前端保存后热更新；Rust/Tauri 修改后增量编译并重启窗口。Python RPC 的下一次调用、后台任务的下一次进程启动会读取新代码，**已经运行的 Python 任务不会热替换**。正在跑下载、Marker 或写作时，先检查任务状态再决定是否需要重启。

1420 端口已占用时，先确认已有开发版是否正在运行，避免重复启动。不要为了代码生效清空项目，不要同时打开多个应用实例编辑同一项目。

### 浏览器开发与构建

```sh
# 构建 Vite 桥接使用的 Rust CLI；修改 research.rs 后也需重新构建
./scripts/npm-local.sh run research:build

# 浏览器开发：http://127.0.0.1:1420
./scripts/npm-local.sh run dev

# TypeScript 检查 + Vite 生产构建
./scripts/npm-local.sh run build

# 仅需要独立打包时使用
./scripts/npm-local.sh run desktop:build -- --debug --bundles app
```

不要同时运行独立 Vite 和 Tauri dev 去争用同一个端口。Tauri 构建输出位于 `cache/tauri-target/debug/bundle/macos/`；旧启动器 `启动 ScholarNoteLM.command` 打开的是 `dist/macos/` 中的副本。

### 项目内运行时

| 路径 | 用途 |
| --- | --- |
| `runtimes/node/` | Node/npm；优先使用 `scripts/npm-local.sh` |
| `runtimes/rust/`、`cache/cargo/` | Rust 工具链；优先使用 `scripts/cargo-local.sh` |
| `runtimes/downloader/` | 下载、项目管理、综述服务、写作 HTTP 请求、Word 导出等 |
| `runtimes/marker/` | Marker / Surya / PyTorch；Chroma 相关任务也使用此环境 |
| `runtimes/retrieval/` | 综述及问答检索、NumPy、HTTP 请求 |
| `runtimes/playwright/` | 正式 Sci-Hub 后台 Chromium 下载与 UI 检查共用的浏览器 |
| `models/marker/` | 本地 PDF 转换模型 |

2026-09-28 已清理编译和安装缓存，当前开发版程序及 CLI 保留；下次源码编译会重新生成中间文件。`runtimes/retrieval` 通过 `.pth` 共享 Marker 的基础依赖，不能单独删除 Marker 环境。详见 [本地维护](docs/LOCAL_MAINTENANCE.md)。

不要直接用系统 Python 替代这些环境。现有 macOS 虚拟环境与二进制不能复制到 Windows 直接使用。当前 Mac 环境已经准备好；全新机器的完整安装/发行方案仍需完善，不能把此目录当作已经验证的通用安装包。

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
| Embedding / Chroma / 限速 | `vector_service.py`、`embedding_limits.py`、`services/vectors/` |
| 主题 / 组件 | `tokens.css`、`styles.css`、`ui.tsx`、`Select.tsx` |

表中未注明路径的前端文件在 `apps/desktop/src/`；Python 文件在 `services/downloader/`。

### RPC 调试要点

CLI 为 `cache/tauri-target/debug/research-cli`。直接调用时必须设置 `SCHOLARNOTELM_ROOT`，输入为 `{"action":"...","args":{...}}`，输出为 `{"ok":true,"data":...}` 或错误对象。项目参数是项目 ID，不能假定永远等于文件夹名；路径须通过存储映射解析。

综述主要 RPC：`review.writing.status`、`prepare`、`start`、`retry`、`cancel`、`section`、`preview`、`export`、`settings`。文献库新增按钮对应 `download.start`、`markdown.reconcile`、`markdown.start`。

`review_service.rpc()` 已持有项目综述锁。不要在其同步子调用里重复获取同一非重入文件锁；后台 worker 自己持锁。曾通过真实 CLI 集成测试发现过这种重复加锁导致的“无法启动撰写进程”，不能仅靠直接调用 Python 函数的单元测试判断。

## 4. 文件布局与数据约定

### 系统资源：位于应用内部

```text
ScholarNoteLM/
  apps/desktop/                 # React + Tauri + Rust
  services/                     # Python 服务与后台任务
  scripts/                      # 启动、构建、测试、环境准备
  config/
    storage.json                # 工作目录与项目 ID → 文件夹映射
    markdown.json               # Marker 设备、文字提取 worker；清洗固定内置
    embedding.json              # Embedding profiles、活动配置、RPM/TPM 与凭据
    embedding-verification.json # 多个配置指纹各自的连接验证记录
  data/
    research/research.sqlite3   # 共享模型服务配置等系统设置
    research/downloads.sqlite3  # 共享下载设置
    research/embedding-rate.sqlite3 # 跨进程 Embedding 限速
    reference/                  # JCR、MeSH、Sci-Hub Bloom
    prototype/state.json        # 全局 UI / 项目列表等历史快照状态
  models/                       # 仅保留 Marker 本地模型
  runtimes/                     # 本地运行时与测试浏览器
  installers/                   # 保留的依赖安装材料
  cache/                        # npm、Cargo、模型及应用缓存
  logs/                         # 开发与应用级日志
  tmp/                          # 临时文件、隔离测试目录
  backups/                      # 历史迁移和修改前备份
  experiments/                  # 下载、worker、检索对比实验
  workspace/                    # 默认工作目录，可在设置中改到其他位置
  dist/                         # 前端构建结果与旧桌面包
```

模型密钥是本地配置，数据库/JSON 未统一做应用层加密；不要把这些文件的内容打印进日志或复制到交接文档。也不要默认 `.gitignore` 已覆盖所有敏感路径，尤其是 `config/embedding.json` 和用户工作目录。

“文件保存在 app 内”是可配置资源的目标；操作系统 WebKit、Xcode 等系统组件不完全由应用控制，不能承诺操作系统绝不写入其他目录。

### 项目文件：位于用户工作目录

项目选择统一使用左上方下拉菜单，侧栏不再重复列出“我的项目”；侧栏可滚动，短窗口仍能访问任务中心。菜单中的“删除当前项目”要求输入项目显示名称确认，将完整项目文件夹移入原工作目录 `.trash/<文件夹名>-<唯一标识>/`，从项目列表移除，保留文件备份（仍占磁盘空间）；不影响其他项目、Zotero 或全局配置。运行中的检索/聊天持有存储锁，下载、转换、索引、综述及待启动流程未结束时拒绝删除；暂停下载须先取消。删除最后一个项目后进入可创建新项目的空白页。已删除项目 ID 留有记录，旧请求不能重新创建该项目；迁移工作目录仅迁移现有项目，`.trash` 留在原位置。

```text
<workspace>/<ProjectFolder>/
  project.json
  literature_without_pdf.txt   # 当前集合缺失有效 PDF 的 PMID
  literature_pdf_sources.txt   # 当前集合全部有效 PDF 的来源汇总与逐篇清单
  pubmed/
    current.xml                 # 当前有效文献集合的派生 XML
    queries/                    # 单条检索式执行结果与历史
    snapshots/                  # 合并集合快照
    exports/
  pdf/<PMID>.pdf
  pdf/redundant/<PMID>.pdf       # 移出当前集合的 PDF
  abstracts/<PMID>.md           # PubMed 摘要，不冒充全文
  markdown/<PMID>.md            # 清洗后全文
  markdown/raw/<PMID>.md        # Marker 原稿
  markdown/assets/<PMID>/
  vectors/
    chunks.sqlite3              # 文本块、文档版本、Embedding 缓存与索引登记
    chroma/                     # Chroma 持久化索引
    chunks/                     # 可导出的逐篇 JSONL
    sources/                    # 文本版本快照
  metadata/
    research.sqlite3            # 本项目检索式、文献成员关系、助手对话
    downloads.sqlite3           # 本项目批次、尝试日志、来源缓存、文件登记
    markdown/<PMID>.json         # 转换指纹与清洗记录
    corpus-membership.json      # 成员关系及生命周期编号
  logs/<task-id>/                # 下载 / 转换 / 索引报告
  review/<ReviewName>/           # 当前真实综述工作区，见下一节
  notes/                        # 阅读与笔记页的笔记
  qa/                           # 真实问答对话、逐轮证据、任务与导出
  packages/current-literature.zip
```

`pubmed/current.xml` 是下游判断有效 PMID 的依据，但它由检索数据库导出；**不要通过手工删 XML 来代替在工作台归档/停用检索式**。同一 PMID 只要仍被其他启用来源纳入，就留在当前集合。

### 文件生命周期与“最新”

- 移出当前 XML：只备份 PDF 到 `pdf/redundant/`；对应 Markdown、摘要、文本块和向量数据删除，不再为这些派生文件备份。
- 重新纳入：先恢复通过校验的冗余 PDF，再重新生成 Markdown 和索引。生命周期编号防止旧任务写回已经失效的结果。
- 以内容 SHA-256、模型/清洗/拆分/输入模板签名判断是否最新，不仅看文件时间戳。
- 用户替换 PDF 后，Markdown/索引应失效；用户编辑清洗稿时保留编辑，并使索引失效；只改 worker 数不使已有 Markdown 失效。
- 有 PDF 但对应 Markdown 未就绪时，索引等待转换，不使用旧全文伪装最新。
- 无 PDF 时，向量数据可直接读取 XML 摘要；磁盘上是否存在 `abstracts/<PMID>.md` 不是能否使用摘要的唯一依据。
- 获取阶段“摘要替代且最新”要求有实际下载尝试和失败/延期记录，并有可用摘要。当前有效 PDF 的 `pdfState` 仍按文件是否通过校验判断；用户删除此前成功的 PDF 不会直接被视为下载失败。
- 手工放入 `pdf/<PMID>.pdf` 后，点击“获取 PDF → 更新”：校验文件、登记本地来源、刷新派生状态；该操作不发起下载或 Marker 转换。文件名映射由用户负责，PDF 可读性校验不等于内容确实属于该 PMID。
- 清空 PDF / 摘要是显式调试操作，不用于日常刷新。打包只收录当前 XML 对应文件，新包成功后替换旧包。

## 5. 各阶段的当前行为

### 检索、聊天与参考数据

2026-10-01：Zotero 导入改为可搜索的文件夹树和右侧范围预览，支持跨分支多选。父文件夹自动包含全部子文件夹，重叠范围及标准条目去重；一次多选保存为一个来源快照，报告保留所选文件夹完整路径。再次打开恢复本项目上次选择与展开状态；选择改变后需重新预览。

2026-09-30 新增 **文献来源 → 导入自 Zotero**，原“检索式管理”改名为“文献来源”；移除 XML 上传和手动关联 PDF 的界面入口，已有 XML 来源仍可读取、停用与归档。

- 只读 Zotero localhost API 的个人文献库，选择集合后递归读取全部子集合，按条目 key 去重。预览保存标准条目快照；没有有效 DOI 的条目跳过并记录。
- DOI 每 50 个一批，以带引号的 `"DOI"[aid]` OR 检索；随后批量 EFetch XML，再与文献自身 DOI 精确核对。引用列表中的 DOI 不参与匹配。无匹配、歧义和请求失败分开记录；歧义条目不自动纳入或绑定 PDF。
- 每次导入创建一个独立 Zotero 来源快照，不生成可执行的 PMID 检索式，不提供更新/重新检索按钮。重复 PMID 在文献库去重，但保留全部来源；来源支持改名、停用和归档。
- Zotero 来源不继承日期、目标数量、JCR 或“必须有摘要”筛选，也不参与统一筛选设置。
- 只读取本次选中条目的附件；复用现有标题白名单、补充材料排除和优先级，**不限制 linkMode 或附件 HTTP URL**。校验可读本地 PDF 后复制为 `pdf/<PMID>.pdf`，保留 Zotero 原文件；已有项目 PDF 不覆盖。原下载流程的末轮 Zotero 补救仍沿用其旧规则。
- 后台任务离开页面仍继续；文献来源与任务中心均可查看进度、取消和逐条报告。提交前取消不创建来源；提交后取消保留已存元数据及 PDF。快照、PubMed 批次 XML 和报告位于 `metadata/zotero-imports/<任务ID>/`。
- 验证：Rust 22 项、Zotero Python 44 项、项目任务 Python 12 项及隔离界面验收通过。真实 PubMed 使用 PrimaryMN 的 253 个 DOI，6 批全部映射到预期 PMID；第二次导入新增来源且复用 PDF，原 PrimaryMN XML 未改变。脚本：`scripts/test-zotero-import-live.py`（隔离 Zotero 模拟服务 + 真实 PubMed）、`scripts/test-zotero-import-ui.mjs`；真实 Zotero 库的端到端导入尚需启用本地 API 后使用。

检索式通过“＋”直接新增表格行，包含标题、简写检索式、排序、数量、日期、JCR 和执行状态；双击可编辑详情。默认相关性、30 条，日期和 JCR 为空。JCR 是取得 PubMed 结果后的本地筛选，不是 PubMed 字段。

检索助手只负责设计检索式、使用本地 MeSH 核验，不自动探测 PubMed 命中数。用户确认加入管理页后再明确执行。聊天 Enter 换行，macOS Cmd+Enter / Windows Ctrl+Enter 发送；仅消息区域滚动。只展示服务实际返回的推理内容，可展开/收起，生成结束自动折叠。

JCR 默认文件来自 BADR 的本地副本，上传通过列名与记录校验才激活。MeSH 使用 NLM 官方压缩 XML 批量源建立 SQLite 索引，包含主题词、限定词及可选 SCR；应用运行期间定期检查更新，不安装应用关闭后仍运行的系统任务。详见 [检索工作台](docs/SEARCH_WORKBENCH.md)，其中旧存储路径和“未接入模块”段落需按本文理解。

### PDF 下载

当前顺序：**有效本地 PDF / 冗余恢复 → PMC S3 + Europe PMC getPdf 双路并行 → 历史来源缓存 / Sci-Hub Bloom 首轮 → Unpaywall → Sci-Hub 补救轮 → 可选增强补救 → Zotero 本地补充**。增强补救位于设置中，默认关闭；Zotero 始终在全部网络来源之后，不受 Fast OA / 增强补救开关影响。

- **2026-09-21：正式 Sci-Hub 传输改为后台 Playwright Chromium**，不再使用 `curl_cffi.AsyncSession`。`scihub_retry.py` 保留队列、Bloom、历史缓存、镜像互斥、两轮与预算；`scihub_browser.py/.mjs` 负责 Python/Node 通信和真实页面导航、渲染 DOM、原生下载/浏览器响应。Sci-Net 仍按最终文件主机独立标注；PMC S3、Unpaywall、Europe PMC、Zotero 的访问客户端不变。
- 浏览器按批次延迟启动、重复使用；每篇每轮独立临时 context，同篇文章页与文件共享 Cookie；仅经过 Altcha 验证的同站点 Cookie 可在当前批次内跨篇复用，批次退出即丢弃，不持久化登录。状态/设置查询不启动浏览器。运行时要求项目内 Node、`node_modules/@playwright/test` 及匹配的 `runtimes/playwright` Chromium；缺失或崩溃明确报错，不回退 HTTP。保持 TLS 校验；支持有界 Altcha 工作量证明协议，不提供人工验证码界面、图像识别或其他挑战的自动处理。
- 页面导航、DOM 等待、完整响应体和原生下载都计入 12 秒入口 / 30 秒文件与每轮 75 秒实际请求预算。取消/暂停关闭 context，批次结束回收 sidecar/Chromium/临时文件；异常退出与宿主退出有清理路径。自动脚本子请求另行计数，嵌入 PDF/文件子请求受阻止后由原文件调度器显式下载。发布前复查当前 DOI、集合生命周期、任务控制和目标文件指纹，避免覆盖后来补入的 PDF。
- **2026-09-29：PMC 双路并行。** 仅处理已有有效 PMCID 的文献，不再按 PMID 补查。S3 按 PMCID 数字正序（默认并发 5），Europe PMC `https://europepmc.org/api/getPdf?pmcid=PMC编号` 按倒序（默认并发 4）；共享任务状态、同篇独占、成功跳过、失败互补。getPdf 默认单次总时限 60 秒、最多 3 次尝试，限流共享冷却；不需要开启增强补救。暂停/继续保留已完成来源和请求预算，报告单独统计双路墙钟耗时。
- PMC S3 根据 PMCID 找版本，读取官方版本 JSON 的 `pdf_url`，核对 PMID/PMCID，不用补充材料 PDF 凑正文；校验后以 PMID 命名。
- Bloom 命中不是下载成功保证；未命中也不代表永远无法获取。报告区分“找到入口/文件”“实际下载成功”“失败/延期”。
- 同一镜像入口同时最多一个请求，不同镜像可并行；镜像锁跨本应用的项目进程共享。
- 各轮尽量遍历可用镜像，但受请求预算、锁等待、退避及取消限制，**不能宣称每篇每轮一定尝试完所有镜像**。
- 下载后校验 PDF 签名、页数、可用校验和，再原子发布。Sci-Hub / Sci-Net 另做 DOI 或完整标题身份检查；明确错档继续其他候选，证据不足/扫描件保留到 `logs/<batch>/identity_pending/<PMID>/`，不计下载成功、不进入正式 `pdf/` 或自动转换/索引。已有本地文件与其他来源的规则不变。按批次保留 TXT / JSON / JSONL 报告。
- Sci-Hub 解析完整候选列表，跳过 `data:` 等占位地址；404/410 才触发同主机有限分片补救，最多额外刷新入口两次。每镜像仍是一次已记账的访问机会，内部重放/刷新均计入预算，暂停恢复不重置；429/Retry-After 不提前重试。没有加入实验 CDN。
- Altcha 由独立 `scihub_altcha.py` 模块处理：挑战 GET/提交 POST 通过当前 Chromium 页面显式 `fetch`，文章与 PDF 仍是页面导航/浏览器下载；同站点验证全过程持有原入口锁，不回退 curl。算法、工作量、时间和响应大小均有上限；取消可终止。身份检查在可终止辅助进程中复用原 PDF 校验，并在发布前核对同一暂存文件指纹。
- 下载批次结束以及“获取 PDF → 检查本地文件”完成后，原子覆盖项目根目录的 `literature_without_pdf.txt`：按当前 XML 列出缺少有效 PDF 的 PMID，每行一个、按数值排序；全文齐全时保留空文件。损坏 PDF 计入缺失，移出 XML 的文献不列入；日志目录内同名文件继续保留批次语义。
- 同时更新项目根目录的 `literature_pdf_sources.txt`：列出当前集合所有有效 PDF（不限于本批下载）的 PMID、相对文件名、具体来源，并汇总各来源数量。保留 Sci-Hub、Sci-Net、Zotero、PMC S3、Unpaywall、Europe PMC、用户提供/关联等来源；来源须对应当前文件的 SHA-256，无法确认时明确标记未知。替换文件不沿用旧来源，冗余备份/损坏/缺失文件不计入；无有效 PDF 时覆盖为总数 0 的报告。
- 文献库的“下载”独立运行下载；主流程按钮接续下载、转换与索引。“更新”只检查本地文件，“执行转化”启动 Marker。

- Zotero 本地地址在“设置 → PDF 下载”中配置，默认 `localhost:23119`（旧配置兼容），留空跳过；自动补齐协议/API 路径，只连本机且绕过环境代理。只读个人库元数据和本机附件，不启动 Zotero、不修改库/设置、不同步/下载、不访问附件原始网址、不读库数据库。
- 以当前 PubMed DOI 精确匹配全部重复父条目，完整分页后合并附件；仅放行 PDF + `imported_url` + 附件自身 HTTP(S) URL + 精确标题白名单。未知标题绝不兜底。规则正式资源为 `services/downloader/resources/zotero-pdf-title-list.v2.json`；排除明确补充材料/目录标记，按优先级、实际大小、完全并列随机选择，记录附件 key 与稿件类型。
- 2026-09-21 白名单 v2 保留 v1 全部条目与优先级，仅新增附件标题 `PDF.pdf`，优先级 600（最低，在 Preprint PDF 的 510 之后），稿件类型为 unspecified-pdf。匹配的是附件标题，不是磁盘文件名；其他 DOI、URL、导入类型、排除补充材料与 PDF 校验条件继续适用。
- Zotero 探测 2 秒、请求 3 秒、每 DOI 15 秒、整个阶段 60 秒，最多 2 个可终止辅助进程，内部预留清理时间。文件复制/哈希/解析/发布均纳入预算，超时或取消杀掉辅助进程并清理 staging；发布复用同一暂存文件的校验并复查生命周期，避免再次无界解析。不可用/无匹配只跳过，保留原有失败/延期语义，两份缺失清单与下游接续使用最终结果。
- 本机真实 Local API 只读探测返回 403，未启用或更改设置；成功复制、分页、异常、取消及独立下载 worker 均用 `tmp/` 隔离 fixture 验证。Windows/Linux 的对应分支尚未实机验证，详见下载文档。

浏览器专项与真实应用入口隔离验证：`test_scihub_browser.py`、`scripts/test-scihub-browser-integration.py`；38 篇调度回归 `scripts/test-scheduler-http.py` 现使用真实 Chromium（OA 部分仍用 httpx）。早期浏览器验证及当时的小样本结果见 [浏览器传输验证](docs/SCIHUB_BROWSER_VALIDATION.md)；本轮增强与独立 Altcha 验收见 [增强验证记录](docs/SCIHUB_ENHANCEMENTS_VALIDATION.md)。

详细来源、镜像锁及超时行为见 [PDF 下载](docs/PDF_DOWNLOADS.md)。运行时使用应用内的 `badr_sources.py`，不依赖原 BADR 目录继续存在。

### Marker 与清洗

单批次串行处理论文，**整批复用一套模型**；worker 是 pdftext 页级文字提取进程数，不是同时转换的论文数。默认自动：少于 40 页用 1，40 页及以上用 4；实际数量受页数约束。模型在本地，转换禁止网络，不调用 LLM。

沿用 BADR 的非 OCR 模式（`disable_ocr=True`）；扫描 PDF 可能失败。保留 `markdown/raw/` 原稿，清洗可重做。参考文献清洗固定内置，不提供策略选项或关闭开关。当前仅清洗参考文献（包括明确标注的本文引用格式），不删除短段、标题、图注、列表或页眉页脚。详见 [Markdown](docs/MARKDOWN.md) 和 [图表关联证据](docs/positional-evidence-resources.md)。

### 分块、Embedding 与索引

当前 splitter：`paragraph-period-balanced-8192-alltext-resources-v3`。

1. 空行分段，不合并短段、不添加 overlap。
2. 段落超过 **8192 个 Python Unicode 字符**，选择靠近中点的英文句号 `.` 二分，仍超长则继续二分。
3. 小数点不作为优先句界；无合适句号时按字符中点拆分。
4. 所有非空短块保留；分类 metadata 不改变原文块。召回时排除少于 100 字符的 heading，长 heading、短正文和图注保留。

Embedding 输入仅为 chunk 原文，模板版本为 `chunk-body-only-v2`；论文标题和章节路径只保存在 metadata 中，不拼入向量、关键词排名输入。旧的带标题向量使用不同索引版本，须重新建立索引，不能直接复用。**字符数不是 token 数**；模型拒绝超长输入时明确报错，不静默截断。文本块浏览器展示 PMID、原文、行号/上下文、metadata。完整图表独立保存，按同一份清洗稿的位置关联到文本块；召回后补入问答和综述材料。

`vectors/chunks.sqlite3` 中的 Embedding 缓存与 Chroma 的“某篇文献当前索引已发布”是不同状态。综述 API 召回可直接复用向量缓存进行余弦排序，不等于所有文献都已标记 Chroma 索引最新。遇到“生成缺失 API 向量”时，应检查模型身份、输入哈希、模板/文本版本和摘要块是否已有缓存，不能仅凭缺失数量断言为无 PDF 文献。

Embedding 请求使用当前 Embedding 配置中的共享 RPM/TPM 限速，默认 60 RPM / 120000 估算 TPM 是应用值，不代表供应商账号配额；429 遵循 Retry-After。验证绑定实际服务配置与凭据指纹，修改后需重新验证。

## 6. 综述生成：实现与文件协议

### 大纲与写作单元

大纲输入为综述主题、可折叠额外要求、BADR 提示词和当前 XML 的摘要合集。保存完整 `prompt.txt` 供用户手动发送给其他 LLM。生成有活动状态、可取消；失败不覆盖原大纲。

CSV 为序号/标题两列，校验父子关系、顺序、同级连续编号等，最多 1000 个标题但不限制深度。稳定节点 ID 与显示编号分离。

`review_writing.tree_units()` 沿用 BADR 的混合深度装配思路：同一父节点的直接子节点全部为叶节点时可组成一个单元；同层深浅混合时独立叶节点单独处理。必须保证每个叶节点恰好属于一个单元。**写作单元数不等于叶节点数，也不等于大纲总行数。**

### 第一步：准备综述提示词

1. 对终末标题原文召回已有块，不改变 chunking。
2. 实际召回数 = 写作页 `topK`；不足时不重复填满。
3. 只使用当前已验证的 Embedding 配置，不加载本地重排模型。
4. 按单元生成 `review_parts/prompt_section_<编号>.json`：每个标题独立检索，同一写作单元共享去重后的文本池与图表池，检索来源保留为记录。图表内容保存在 `review_parts/resources/`；同名 TXT 为阅读预览。
5. 只准备材料，不调用写作 LLM。`prompts/<稳定ID>.json` 保存证据、计划和文件哈希，用于恢复与失效判断。

字符预算默认关闭；用户主动开启后，超预算会提示提高或关闭预算，保持同级终末标题联合撰写，不自动拆分节点，也不截断材料。改成更强的写作模型不等于一定需要重做召回；应根据输入签名判断。

### 第二步：生成综述

读取 JSON 材料包，校验结构、关联关系及外置文件哈希，补入完整表格与勾选支持图片输入的模型所需图片后发送，**不再次召回或重排**。按用户并发运行，接收 SSE 正文和实际推理活动；超时按连续无新数据计算。

模型输出 JSON，正文引用使用 `[E1]` 或 `[R1]`。程序校验节点覆盖、标题和当前单元证据 ID，将合法引用转换为 PMID，并保存原始引用映射。结构或引用失败时使用同一完整共享池联合修复一次，仍失败不发布。不是所有 JSON/网络错误都自动重试。应用里：

- **生成综述**：跳过最新成功正文，生成缺失/过期项。
- **重试失败项**：只重新执行失败项；已成功结果保留。
- **重新生成此单元**：显式重写选中单元。
- 批次进度按已结束任务计数，成功/失败/进行中/待处理/取消独立展示。100% 已处理不等于全部成功。
- `logs/<run>/result.json` 保留每轮状态及错误，避免下轮覆盖 `writing-job.json` 后失去失败原因。
- 文件、源文献或配置在任务中变动时，不能发布与当前输入不一致的结果。

### 公共片段格式与导出

`review_parts/section_<编号>.json` 的新格式为 `review-unit-object-refs-v3`，包含 `unit_id`、`sections`、`citation_validation`、`citation_scopes`、`evidencePool`、`resources`、`retrieval`、`markdown_content`。每个 section 保留原始 `sourceBlocks`、绑定资源的 `blocks`、兼容文本 `sourceMarkdown` / `markdown`、`citationRefs` 和协议版本。同处连续引文按 PMID 去重展示，内部证据 ID 全部保留。对外节点编号仍为大纲编号。

同一单元的终末子标题可以使用整个共享池；父标题导语不引用。检索来源不再作为排他性引用权限。旧 BADR 风格片段仍可读取，但不会标记为新格式最新结果。图表仅作材料时不自动进入正文；模型可选择完整资源块，也可生成摘取/合并后的带引文结构表格。原表与生成表共用编号序列，图片单独编号；正文通过 `{{ref:R1}}` / `{{ref:T1}}` 引用，由程序装配编号与跳转。确定性校验检查对象存在、表格行列及每行证据 ID，不调用 LLM 做语义后验证。详见 [正文图表与引用展示](docs/review-resource-blocks.md) 和 [共享写作材料包](docs/review-shared-pool.md)。

HTML 为离线阅读页面：低饱和深绿工具栏、连续正文、可折叠目录与当前章节定位、阅读进度；引用详情默认收起，点击 PMID 后按小节展开对应素材。窄屏使用可关闭侧栏，支持键盘操作；打印 / PDF 隐藏阅读控件。CSS 与脚本内嵌，打开页面无需联网。新导出的引用详情包含共享正文、完整关联表格与内嵌图片；表格使用安全的 Markdown/HTML 渲染。旧字符串素材继续兼容。Word 通过 python-docx 生成。装配按完整大纲顺序，不按异步完成顺序，组织标题也保留。`citation_validation.passed` **仅代表格式/范围检查通过，不是论断已被科学证据证明**。

### 工作区布局和外部文件修改

```text
review/<ReviewName>/
  review.json                    # 名称、描述、迁移记录
  outline-state.json             # 主题、要求、修订与生成状态
  outline.csv / generated.csv    # 当前大纲 / 最初生成稿（恢复默认）
  nodes.json                     # 稳定节点 ID
  source.xml / abstracts.txt     # 大纲生成来源快照
  prompt.txt / prompt.json       # 大纲完整提示词
  response.txt                   # 大纲模型原始返回
  writing-settings.json
  writing-job.json               # 当前/最近批次状态
  retrieval/<leaf-id>.json       # 各终末小节选中的块、分数与检索参数
  prompts/<unit-id>.json         # 准备计划、文件哈希和证据
  review_parts/
    prompt_section_*.json         # 正式共享材料包
    prompt_section_*.txt          # 自动生成的阅读预览
    resources/                   # 按内容哈希保存的表格与图片
    section_*.json               # 公共综述片段
  sections/<unit-id>.json         # 内部正文、完整 metadata、签名、模型与任务信息
  logs/<run-id>/
    input.json                   # 冻结输入和任务列表
    result.json                  # 本轮结果/错误；早期历史运行不一定有
    *.prompt.json / *.response.txt
    *.repair.prompt.json / *.repair.response.txt
    worker.log
  exports/                       # md / html / docx 静态导出
  audit/                         # 实际综述审查报告
  versions/                      # 仅旧版迁移保留
```

公共片段被删除后，`saved_unit()` 不从内部 `sections/` 缓存复活正文；公共文件若与内部记录不一致，也不能直接认定为已验证结果。删除/修改正式 JSON 或资源文件会使准备状态失效；TXT 预览不参与判断。撰写页空闲可见时约 2.5 秒检查一次，运行中约 1.2 秒；实际延迟还受 RPC 耗时影响。当前已打开正文和预览也会刷新。

这是文件变动检测，**不是对任意外部编辑文件的自动导入**。已导出的 HTML/Word 是静态快照，文件变化后需重新导出。不要删私有 sidecar 来“清缓存”，否则会失去继续编辑、证据追踪与签名信息。

## 7. 2026-09-20 真实项目快照与未解决问题

当前主要示例为 `workspace/gut`，综述为 `workspace/gut/review/test1`。下面是审查时快照，后续应重新查询状态，不要硬编码进 UI 或测试期望：

| 指标 | 快照 |
| --- | ---: |
| XML 文献 | 105 |
| PDF / 已转换全文 | 85 / 85 |
| 未取得全文、使用摘要 | 20 |
| 文本块 | 8259（并非全部用于综述召回） |
| 大纲标题 / 终末小节 / 写作单元 | 162 / 109 / 45 |
| 生成正文段落 | 152，另有 10 个纯组织标题 |
| 引用标记 / 不同 PMID | 552 / 85 |
| 当前成功写作单元 | 45 / 45 |

完整报告：[综述审查-2026-09-20.md](workspace/gut/review/test1/audit/综述审查-2026-09-20.md)，机器检查：[audit-2026-09-20.json](workspace/gut/review/test1/audit/audit-2026-09-20.json)。工作目录以后迁移时，沿配置找到对应项目再读取。

### 对内容质量的当前认识

用户认为较弱 LLM 会造成表意错误，这与部分观察一致。但本次检查还发现**上游材料选择问题**，不能把全部问题归给写作模型，也不能保证换模型就解决：

- **1.2、8.5.2**：版权、致谢、利益冲突、参考文献残片进入最终材料；其中部分 Qwen3 分数很高，重排分数不等于证据可靠。
- **5.5.2 / 6.3.1**：同一项目中，前者未召回相关实验而称材料不足，后者已引用同一通路的实验，造成跨章节不一致。
- **2.1.1**：新生动物实验被写成“新生儿”，存在物种边界问题。
- **9.1.2 / 9.4.1**：方向表述、人体/动物证据及条件限定有问题。
- **2.1.1 / 2.1.2**：来源表述存在差异，综述未整合解释，不能简单归类为模型凭空捏造。
- **9.4.2**：目标是 Trp/AhR，主要材料却是胆汁酸受体背景，小节未充分回答标题。

全量结构/引用范围检查未发现 PMID 越界、节点漏装或 HTML 引用串位，但这是与语义支持不同的一层检查。报告完成重点材料核对，没有声称逐句验证全部医学结论。

**尚未修复**：非证据块的可靠过滤、块分类/标题路径质量、检索不足判定、跨章节一致性与事实核验。当前检索仅排除已标记为 `reference/heading` 的块；部分 References 下的内容被错误标为 paragraph，因此仍进入候选。后续可在保持段落分块不变的前提下改进，但本次未自动改规则、重召回或改写用户正文。

最近审查后，用户的 45 份原始片段及提示词保持不变。**仅点重试会复用原提示词，不能修复选错的证据材料。** 新任务应先明确要优化写作模型、检索、提示词还是校验，不将相关建议视为已经实现。

### 上次失败与计数问题

初轮 45 个单元留下 25 份完整响应，20 项没有完整响应文件；已有 25 份能解析 JSON。完整响应在 JSON 校验前保存，因此不能将这 20 项统一认定为 JSON 校验失败。这些请求也未达到当时 90000 字符预算。旧日志未保留具体异常，无法可靠区分网络、超时或服务响应结束错误。

下一轮仅重试 20 项，全部成功，约 223 秒。现已增加明确重试入口、实时独立计数及逐轮 `result.json`，以后定位失败应优先读本轮记录。

另外，审查时 UI 的 Chroma 已发布索引数为 0，但综述使用了缓存 Embedding 并已生成。这两种登记状态不同，不能只看到 0 就认定全文/摘要没有向量，也不能直接清空缓存重做。

## 8. 验证与工作方式

先检查现有任务和所选工作目录，再做改动。测试优先使用 `tmp/` 下隔离项目、本机模拟 LLM/Embedding 服务；不要为了验证状态管理批量重新下载、转换或调用用户真实模型。

### 常用检查命令

```sh
./scripts/npm-local.sh run build

./scripts/cargo-local.sh test \
  --manifest-path apps/desktop/src-tauri/Cargo.toml --bin research-cli

# 综述、大纲、BADR 片段格式
runtimes/downloader/bin/python -m unittest discover \
  -s services/downloader/tests -p 'test_review*.py'

# 文件状态、摘要替代、用户补充 PDF
runtimes/downloader/bin/python -m unittest discover \
  -s services/downloader/tests -p 'test_artifact_state.py'

# 按本次改动选择 test_vectors.py / test_corpus_markdown.py / test_downloads.py 等
# 全部 downloader 测试入口：
runtimes/downloader/bin/python -m unittest discover -s services/downloader/tests

# 真实 Rust RPC + 独立 worker + 本机模拟 API，临时项目隔离
runtimes/downloader/bin/python scripts/test-review-writing-integration.py

# 已启动 Vite 开发服务后：
PLAYWRIGHT_BROWSERS_PATH="$PWD/runtimes/playwright" TMPDIR="$PWD/tmp" \
  runtimes/node/bin/node scripts/test-review-progress-library-ui.mjs
```

最近一轮相关后端检查共 **94 项**通过：综述 39、文件状态 11、向量 13、Markdown/同步 18、下载 13；这个数字是选定测试集，不是全项目测试总量。另通过两阶段写作集成、模拟 JSON 失败后仅重试失败项、外部删除 prompt/section、取消、导出与 UI 检查。前端构建通过，仍有 Vite bundle 体积提示。

`scripts/test-review-progress-library-ui.mjs` 读取本机 `gut/test1`，拦截写操作和部分状态；它依赖现有项目快照，不是空白安装通用测试。文档中的成功记录不替代未来改动后的对应验证。

以下测试应按需要单独选择：

| 测试 | 范围 / 注意点 |
| --- | --- |
| `scripts/test-review-integration.py` | 大纲与工作区 |
| `scripts/test-review-writing-integration.py` | 独立 worker、两步写作、重试、文件缺失、取消、导出 |
| `scripts/test-review-reader-ui.mjs` | 离线 HTML 目录、引用作用域、窄屏侧栏、键盘操作、打印与无外部请求 |
| `scripts/test-vectors-integration.py` | Chroma 与索引任务 |
| `scripts/test-markdown-corpus.py` | XML 变化、PDF 归档恢复与派生文件 |
| `scripts/test-literature-workflow.py` | 实际 Marker 流程，不是轻量检查 |
| `scripts/test-pubmed-live.py`、`test-download-live.py`、`test-source-cache-live.py` | 会访问真实外网，不是离线回归 |
| `scripts/test-workbench-ui.mjs` 等 | 需要开发服务和测试浏览器，读取各脚本说明 |
| `scripts/visual-check.mjs` | 早期原型截图脚本，会切换并保存真实主题设置，可能不适用于当前页面 |

修改分块、Embedding 输入、检索策略或提示词协议时，检查对应签名/版本与缓存失效逻辑。不要只改 UI 而不改实际请求，也不要用演示数据补足真实失败结果。文件删除、外部替换、取消后继续及混合层级大纲都是关键回归场景。

## 9. BADR 参考与进一步阅读

本机参考源码：

```text
/Users/yuxin/AI_developing/BADR专业/BADR_重构0603_fetchpaper版
```

用户提供的 BADR 产物样例：

```text
/Users/yuxin/Documents/PubmedResearch/content/zmj0606/prompt.txt
/Users/yuxin/Documents/PubmedResearch/content/zmj0606/review_parts_cn/prompt_section_1.txt
/Users/yuxin/Documents/PubmedResearch/content/zmj0606/review_parts_cn/section_1.json
/Users/yuxin/Documents/PubmedResearch/content/zmj0606/review_parts_cn/zmj0606_Review.html
```

参考对象包括 PubMed 接口、JCR 校验、下载来源、Marker 转换与清洗、大纲提示词、混合层级写作单元、片段 JSON、HTML/Word 装配。它们是参考资料，不是应用运行时依赖；也不要从 BADR 复制凭据。原始长提示词无需每次整份加载，先看格式和代码。

| 文档 / 实验 | 用途 |
| --- | --- |
| [PROJECT_PLAN.md](PROJECT_PLAN.md) | 早期完整产品规划，不代表全部已实现 |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | 开发版启动与热更新 |
| [PROJECT_STORAGE.md](docs/PROJECT_STORAGE.md) | 工作目录迁移与数据分离 |
| [ARTIFACT_LIFECYCLE.md](docs/ARTIFACT_LIFECYCLE.md) | 内容指纹、归档、派生文件失效；PDF 摘要替代规则以本文更新为准 |
| [MARKDOWN.md](docs/MARKDOWN.md) | Marker、worker、清洗与离线运行 |
| [VECTORIZATION.md](docs/VECTORIZATION.md) | 分块、向量缓存与调试浏览器 |
| [REVIEW_OUTLINES.md](docs/REVIEW_OUTLINES.md) | 大纲与两阶段写作；旧预算说明已被本文取代 |
| [PDF_DOWNLOADS.md](docs/PDF_DOWNLOADS.md) | 下载队列、来源顺序、报告 |
| [SEARCH_WORKBENCH.md](docs/SEARCH_WORKBENCH.md) | 检索/聊天/MeSH；含早期存储说明 |
| [UI_DESIGN.md](docs/UI_DESIGN.md) | 视觉方向；当前页面以源码及截图为准 |
| `experiments/marker-workers-20260920/` | worker 本机样本实验 |
| `experiments/retrieval20260920/` | 历史召回/重排对比，不代表现行配置 |
| `experiments/scihub-20260920/` | 历史下载排障实验 |
| `docs/screenshots/` | 页面验证截图，注意生成日期与是否模拟状态 |

尚未完成的主要产品能力是问答真实研究问题质量评测与逐篇全面筛查、综述证据质量的进一步保障、跨平台安装/发行与 Windows 实机验证。下一次开发应依据用户的新指令选择范围，不自动启动这些全部工作。

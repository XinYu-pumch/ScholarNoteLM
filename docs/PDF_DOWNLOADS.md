# PDF 下载（0.6.0）

## 入口与行为

- 文献库：下载缺失 PDF、下载选中、单篇下载、打开 PDF、关联本地 PDF（25 MB 以内）、导出当前集合 PDF 压缩包。
- 任务中心：按批次查看真实状态、逐篇来源/错误、暂停、继续、取消、重试失败、下载报告和日志文件夹。
- 设置 → PDF 下载：按开放获取、Zotero、Sci-Hub 镜像分组；下载速度与超时可展开调整。Bloom 固定使用随应用提供的 `data/reference/download/scihub.bloom`，不再提供用户导入或路径配置。
- 缺少 Unpaywall 邮箱会跳过该来源，其他来源继续。没有真实 PubMed 记录的示例文献不可下载。

## 来源顺序

校验已有 PDF → PMC S3 + Europe PMC getPdf 双路并行 → 历史来源缓存 / Sci-Hub Bloom → Unpaywall → Sci-Hub 补救 / 重试 → Zotero 本地补充。
成功的文件立即退出后续来源。2026-10-03 起停用额外的 OA 慢速补救、Europe PMC 深度回退和 PMC 慢速补救；旧配置中的 enhanced 开关不再生效。常规开放获取和 Zotero 来源保留。

BADR 的 DOI 规范化、Bloom 读取、镜像轮换及独立镜像锁、Europe PMC 候选解析逻辑提取到 `services/downloader/badr_sources.py`；不在运行时引用 BADR。启用 TLS 校验，正文落地前统一经过 PDF 校验。

PMC S3 使用 `prefix=PMCID.&delimiter=/` 发现版本，支持分页，读取版本 JSON 中的 `pdf_url`，不从 `media_urls` 中挑选附件。核对 PMCID、PMID 和版本；多版本尽量使用 ID Converter 的 current 标记，无法确定时记录选择依据，不将最大版本号宣称为最新版。JSON 无正文或获取失败时进入后续来源，不猜附件地址。

第二步仅处理批次记录中已有有效 PMCID 的文献。缺少或格式无效的 PMCID 直接跳过双路阶段，不再逐个 PMID 查询补全；后续 DOI 来源照常处理。

S3 采用正常证书验证，对网络异常、429、500/502/503/504 有限退避重试。PDF 写入批次 staging，验证 PDF 签名、可读页数、官方 MD5（若有），生成 SHA-256，再原子移动到 `pdf/<PMID>.pdf`。

## PMC 双路并行（2026-09-29）

- S3 按 PMCID 数字部分正序领取任务，默认并发 5；Europe PMC 按倒序领取任务，默认并发 4。两路共用完成状态，同篇只允许一路持有下载任务，校验并发布成功后另一来源跳过。
- 一路失败即可由另一路领取，无须等整轮结束。每篇每来源每轮只进入一次，来源内部仍有有限重试；两路都未成功才进入 Sci-Hub 等后续步骤。
- 队列入口先筛选有效 PMCID，S3 和 getPdf 均只处理这一集合；不按 PMID 补查。没有有效 PMCID 的文献不消耗双路并发槽位、请求或超时预算，直接留给后续来源。
- 新来源只调用 `https://europepmc.org/api/getPdf?pmcid=PMC编号`，无须 DOI、API key、Cookie 或 ZIP/FTP。Fast OA 开关同时控制双路 PMC 与 Unpaywall。
- getPdf 默认连接上限 15 秒、单次总时限 60 秒、最多 3 次（初次 + 2 次重试）；瞬时网络故障、429、500/502/503/504 有限重试，退避 2、4 秒并遵守 Retry-After。429 对本批 getPdf 队列共享冷却，不阻塞 S3。要求等待超过 60 秒时延期，避免长时间占用整个队列；403/404 不盲目重试。500 不解释为文章不存在。
- 流式写入 staging，拒绝超过 250 MiB、不足 1024 字节、不以 `%PDF-` 开头或结构不可读的文件；统一校验可读页数、SHA-256 后原子发布。错误 JSON / HTML 不进入文献库。取消、暂停和请求超时清理临时文件。
- 暂停/继续保留每来源已完成状态，以及 getPdf 已消耗请求次数；“重试失败”重置该篇周期预算。原有有效 PDF 始终复用。
- 下载报告分开记录 `pmc_s3` 与 `europe_pmc_getpdf` 的请求和成功数；`pmc_parallel` / `pmcParallelWallSeconds` 为双路阶段墙钟耗时。两来源的耗时有重叠，不能相加当作阶段总耗时。getPdf 保留 PMCID URL、状态、错误响应摘要、字节、首字节和传输时间，错误响应流量不计为 PDF 传输量。

实现：`services/downloader/pmc_parallel.py`（共享调度）、`europe_pmc_pdf.py`（直接 getPdf），沿用 `engine.py` 的发布、校验和任务生命周期。设置页支持修改 getPdf 并发、请求总时限和最大尝试次数；新增默认值兼容旧配置。

## 正式 Sci-Hub 浏览器传输（2026-09-21）

正式 Sci-Hub 两轮及历史文件/文章页缓存均使用 **Playwright headless Chromium**，通过真实 `page.goto()`、渲染后的 DOM、浏览器 `download` 事件 / `response.body()` 取得内容。不使用 Playwright APIRequestContext，不再调用 curl_cffi，也不在浏览器故障时静默回退。`badr_sources.py` 的旧 Sci-Hub 兼容函数也委托同一实现，Europe PMC 等其他客户端保持原状。

实现：`scihub_browser.py` 是 Python 批次所有者，延迟启动项目 Node sidecar `scihub_browser.mjs`；JSONL 标识符对应并发命令，响应体通过专用临时目录交换，不把大文件编码进控制通道。Chromium BrowserServer 仅监听本机回环随机端口，连接地址不写入报告。最多由原有工作队列驱动的 4 个文章会话；浏览器进程批次内复用，每篇每轮新建无持久化 context，同篇镜像页与文件共享该 context。文件导航使用文章页 Referer；仅将验证成功的站点 Cookie 在当前批次内跨篇/跨轮复用，保留 Cookie 的域、路径、到期等属性；其他会话 Cookie 不共享。不加载用户 Chrome 配置，批次结束丢弃验证 Cookie，不保存长期登录态。

DOM 加载后最多等待 1.5 秒出现有效 PDF 候选或验证提示；空 `data:` object 不再提前结束等待，这段等待也受剩余实际预算限制。仅支持下述有界 Altcha 协议，不增加人工浏览器界面。关闭自动 iframe/object/PDF 文件子请求，DOM 仍保留链接；脚本/CSS/普通 XHR 可运行。在响应头阶段另行阻止 URL 未带 `.pdf` 的自动 PDF/二进制响应，避免嵌入查看器绕过显式文件来源并发控制。当前文章页保留到显式验证协议完成或下一次导航，随后由现有文件锁下的新页面显式导航到 PDF；context 与 Cookie 保持不变。

单次 Python 总超时包含延迟启动、导航、DOM、完整响应/下载和进程通信；Node 也对全操作设时限。入口最多 12 秒、文件最多 30 秒、每篇每轮累计 75 秒；锁等待单独最多 30 秒。body 和浏览器原生下载完成后才交给原 PDF 校验器，HTML/验证码/查看器外壳/未完成文件不能成功。其他来源的既有校验规则不变。Sci-Hub / Sci-Net 在基础 PDF 校验之外做下述三态身份检查，**不要求每份 PDF 必须抽取到 DOI**，可以使用完整标题；历史文件哈希仍核对，但同哈希不再单独充当身份确认依据。单体响应最多 250 MiB，DOM 最多 4 MiB。

暂停、取消、单请求超时先关闭对应 context，终止导航与未完成下载；关闭卡住时结束整批浏览器，其他请求明确报告浏览器失败。context 清理最多等待 1.5 秒，sidecar 退出最多等待 2 秒，超过后强制终止。Python 正常退出关闭 stdin；进程意外退出时 Node 监听 stdin EOF 关闭 Chromium 并清理临时目录；sidecar 崩溃则 Python 根据已登记浏览器 PID 回收其 POSIX 进程组。恢复继续沿用已消耗预算，显式重试开启新周期。没有长驻浏览器服务。

日志的 `transport=playwright-chromium`、`browserVersion`、`method`/`transferMethod` 表示真实客户端；`browser-rendered-dom`、`browser-download`、`browser-response-body`、`browser-response-status` 区分取得内容的方式。原 `entryRequests/fileRequests` 仅计显式调度调用；挑战 GET、POST 和入口重放属于显式入口请求，另用 `requestType` 标记，协议传输标为 `browser-challenge-fetch`；`browserRequests/automaticRequests/blockedAutomaticRequests/failedRequests` 记录浏览器请求事件，包含重定向/阻止/原生下载导致的导航中断事件，不等同于文献失败数。保留最终主机、HTTP 状态、字节、总耗时和分类原因。错误信息只输出安全类别，不保存 Cookie、挑战 salt/signature、原始异常调用栈或 URL 查询/签名参数；挑战路径标识也作脱敏。浏览器不可用/崩溃标为延期、供修复后重试，403/429/验证页等继续走既有镜像健康规则。

Sci-Hub 发布继续使用 batch staging、PDF 校验、`publish()`、原子替换、来源缓存和两个项目报告；在文件锁和数据库事务内额外复查当前 DOI、成员生命周期、清空标记、批次控制、宿主存活及目标文件指纹。等待期间新放入或替换的项目 PDF 不覆盖，移出集合的文献不写回。

运行时要求：`runtimes/node/bin/node`（Windows 分支为 `runtimes/node/node.exe`）、项目安装的 `@playwright/test` 及其 `playwright-core`、版本匹配的 `runtimes/playwright/` Chromium。沿用本机已有 Node/Playwright/Chromium，不在运行时自动安装或下载浏览器。Python 仍使用原 downloader 环境。源码修改后下一次下载 worker 启动生效；已有 worker 不会热替换，先让任务结束或暂停，再启动新 worker。本次不修改前端/Rust，也不重新打包旧桌面应用。

历史实验只作为参考，其初版额外 DOI 文本门槛和早期 `invalid_pdf` 数字不作为正式成功标准。

## 候选、身份与有限补救（2026-09-21 增强）

- `scihub_candidates.py`：按 citation_pdf_url → 下载链接 → object/iframe/embed → 其他明确 PDF/storage 链接提取，去重，每页最多 12 个。忽略 data/about/javascript/blob/片段占位；缩减超长内联 data 负载，保留有引号/无引号属性的 DOM 解析能力。不从绝对 URL 中截取路径后擅自更换主机。
- 文件返回 404/410 后，才对 `/storage/<shard>/<rest>` 尝试同主机同 rest 的 `2024`、`zero`；这些只是候选，不宣称是万能分片。不因单文件 404 禁用整个分片。候选仍不可得时最多额外刷新文章页两次；每轮去重文件地址最多 24 个，且受原时间预算约束。429、带 Retry-After 的响应沿原健康模型延期，不截短服务器等待时间。不新增 sci.bban.top 兜底。
- `scihub_identity.py`：在可终止进程内调用原 `engine.validate_pdf()`，再读取前两页，排除明确 References/Bibliography 后的文本；DOI 保留标点，或用完整标题归一化/字符 5-gram 高覆盖匹配。没有 DOI 不直接判失败。标题高覆盖阈值为 0.75；仅在文本充分、标题覆盖极低并有不同 DOI/PDF 标题等冲突证据时判 mismatch，其他情况归入 unverifiable。这是启发式身份检查，不等于人工确认，也不是语义质量保证。
- 每次身份检查最多 4 秒；超时、文本抽取失败和扫描件均为待核验。记录检查政策版本、实际 PDF SHA-256、DOI/完整标题身份键及历史缓存哈希是否相同。已有本地 PDF 不自动重判、删除或重新下载。
- match 才发布；mismatch 继续其他候选/来源；unverifiable 的原文件及 JSON 说明原子移入 `logs/<batch>/identity_pending/<PMID>/`，正式 `pdf/` 不落地，不计下载成功，不进入 Marker/全文索引，后续来源仍可补齐。批次 TXT/JSON/JSONL 记录原因及路径，项目缺失/来源报告继续只按正式有效文件计算。可人工核验后使用原有“关联本地 PDF”功能；不新增审批界面。摘要替代规则仍适用。
- 正式发布复用辅助进程的 PDF 校验结果，在原生命周期 guard 外再核对暂存文件的设备/inode/大小/mtime/ctime；不用第二个不可终止的解析线程重复检查。原 staging、原子发布、缓存及来源报告机制不变。

## Altcha 独立实现与验收

`scihub_altcha.py` 仅实现页面声明的同 origin `/captcha/challenge/<id>` 与 `/captcha/solution/<id>` 协议。未知挑战继续分类失败，不尝试图像验证码或通用网页自动点击。模块允许 SHA-256/384/512，maxNumber 最大 1,000,000、计算最多 2 秒，每 1024 次枚举让出事件循环以响应取消；未知算法、超额工作量和异常格式拒绝。单个协议响应最多 64 KiB，禁止跨站重定向。

文章/PDF 请求仍使用真正 Chromium 导航、渲染 DOM 与浏览器下载。仅挑战协议通过已打开的当前页面 `fetch` 执行，使用同一 context 的 Cookie，不使用 curl 或 Playwright APIRequestContext；GET、POST、计算、重放都纳入本轮预算。验证由原 origin 入口锁串行化（跨项目文件锁继续有效），不让自动挑战脚本绕过显式调度。每镜像每次访问最多处理一次挑战；验证后再次返回挑战时结束该镜像，不无限循环。

仅成功验证后捕获该 origin 的 Cookie 到批次 sidecar 内存，新文章 context 按原 Cookie 属性导入。进程内共享，不写应用配置/数据库，不加载或保存长期浏览器登录档案；Chromium 自身使用临时目录，批次/取消/异常收尾沿既有清理路径删除。不同项目进程不共享 Cookie，但共用原入口互斥锁。单纯状态/设置查询不会启动浏览器或验证。

历史实验的 120/120 是文件下载口径，不作为正式成功率承诺；其 identity 脚本原本未接入下载成功判定。

## 持久化与文件

0.5.0 起，项目文件保存在用户选择的工作目录，系统参考数据仍保存在应用安装目录。详见 [项目存储说明](PROJECT_STORAGE.md)。

- `pubmed/`：XML 与快照。
- `pdf/<PMID>.pdf`、`abstracts/<PMID>.md`：原文与摘要。
- `logs/<批次ID>/`：报告、逐篇日志和批次清单。
- `literature_pdf_sources.txt`：项目当前有效 PDF 的来源汇总及逐篇清单，下载完成或“检查本地文件”后自动更新。
- `metadata/downloads.sqlite3`：当前项目下载数据库。
- `packages/current-literature.zip`：当前 XML 匹配的 PDF / 摘要包，每次成功打包替换旧包。

下载完成不会标记为已索引，也不会删除已有 Markdown。删除/归档检索式不删除历史文件；恢复纳入可以复用有效 PDF。关联本地 PDF 由用户确定文献身份，应用校验文件可读性。

每个项目只允许一个未完成批次，避免重复下载。每个项目使用独立下载进程和数据库，批次内按来源并发。批次固定创建时的文献快照。继续保留原批次配置；失败重试读取最新设置并保留旧尝试日志。报告按批次汇总全部尝试，并区分最终失败、跳过和未完成。

桌面应用退出后，下载进程检测宿主退出并暂停当前批次；下次在任务中心继续。崩溃后根据进程锁恢复为暂停。恢复是文献级重试，不是 HTTP Range 字节级断点续传。开发模式的 CLI 批次可在 Vite 页面关闭后继续运行。

## 运行与验证

Rust RPC 管理受信任的 PubMed 集合输入并调用本地 Python 下载服务；队列控制和文件记录由下载服务的 SQLite 持久化，独立后台进程执行网络请求。数据不会仅保存在浏览器中。

当前 Mac 已准备项目内运行时。其他机器先准备对应平台的 uv，再运行 `python scripts/setup-downloader.py`；运行时、虚拟环境和依赖缓存均定向到项目根目录。Windows 的进程启动、文件打开、文件锁分支已实现，但尚未在 Windows 实机验证。

- `runtimes/downloader/bin/python -m unittest discover -s services/downloader/tests`
- `runtimes/downloader/bin/python scripts/test-download-live.py`：隔离目录中真实下载 PMC4860105，对应 PMID 27019327，校验正文 Key、官方 MD5、文件名。
- `PLAYWRIGHT_BROWSERS_PATH="$PWD/runtimes/playwright" runtimes/node/bin/node scripts/test-download-ui.mjs`
- 同上加 `UI_BROWSER=webkit` 检查 WebKit。

批量下载的成功率受各来源可用性影响。本轮没有对用户项目执行全量下载，也没有使用用户 LLM 密钥。

## Sci-Hub 队列与镜像约束

- 两轮都使用固定工作队列，工作数最多 4 个且不超过配置的镜像数量；不一次为所有文章创建运行任务。队列内等待不消耗单篇请求预算。
- 每个镜像入口同时最多一个请求；不同镜像可并行。优先选择空闲入口，再参考近期成功记录；初始顺序按文章轮换。
- 入口锁按规范化 origin（协议、域名、有效端口）共享。同一应用目录下的不同项目工作进程也使用 OS 文件锁，系统锁文件位于 `data/locks/download-entries/`；进程退出会释放锁。同一批次的文件下载使用独立的存储源信号量（每源最多 2 个并发），不会被同域入口故障直接禁止。
- 首轮先尝试当前 DOI + PMID 对应的历史来源（最多两个文件地址、一个文章页），不受 Bloom 命中限制；随后只对 Bloom 命中条目尝试镜像入口。补救轮覆盖所有剩余 DOI，先完成命中组，再开始未命中组。Bloom 不可用时仍保留补救轮。
- 一篇文章一轮每个镜像只有一次已记账的访问机会；其内部允许一次 Altcha 握手及入口重放、404/410 后最多额外刷新入口两次，所有子请求都记账。取消旧的两个入口限制。成功、实际浏览器访问累计达到 75 秒、锁等待累计达到 30 秒，均会结束当前条目的这一轮。无法尝试完的情况记录延期，不宣称全部镜像已失败。
- 入口单请求最多 12 秒（设置中的请求超时更小时采用较小值），文件单请求最多 30 秒。浏览器总预算与锁等待预算分别计数；整批不设 180 秒硬上限，避免大集合被截断。
- 429 / Retry-After 保留服务器要求的退避时间；TLS 错误停用相应入口至批次结束。普通 403、验证页、无 PDF 链接只影响当前文章。来自三个不同 DOI 的连续网络/临时 5xx 故障才使整个镜像暂不可用。暂不可用的镜像不会在工作队列中反复等待，剩余条目明确延期。
- 两轮之间通过 Unpaywall 自然间隔，不额外强制等待 20–40 秒。每篇每阶段保持独立临时浏览器会话并启用证书校验。
- 两轮的已用浏览器访问/等待时间、已请求镜像均持久化。继续批次不会再次请求已消耗的镜像（包括中断请求）；显式重试失败/延期项才开启新的有限周期。继续时仍可访问该轮尚未消耗的镜像。

## 完整下载时间限制

设置中可修改以下三个总时限，配置快照用于新批次；旧批次缺失字段时采用默认值。

| 范围 | 默认值 | 包含内容 |
| --- | --- | --- |
| Unpaywall 单个文件 | 45 秒 | 连接、响应和持续缓慢传输 |
| Unpaywall 单篇文章 | 60 秒 | 元数据请求与全部候选文件 |
| PMC S3 单篇文章 | 60 秒 | 版本发现、元数据、下载与重试等待 |

没有有效 PMCID 时不发送查询或 PDF 请求。达到时限取消请求、关闭连接并清理不完整文件，文章继续另一来源或后续阶段。HTTP 请求超时与总时限同时生效。

Unpaywall 超时后不再进入额外的慢速补救。摘要仍明确标记为 PubMed 摘要，不冒充全文。

## 下载报告

- `stage_runs` 记录真实阶段墙钟耗时，暂停/继续的执行段分别保存。报告同时列出并发文章累计时间和 HTTP 请求累计时间，不混用为带宽。
- Sci-Hub 按 Bloom 命中/未命中统计成功；S3 统计找到官方正文的文章数与实际成功数。
- S3 / Unpaywall 也记录实际元数据与文件请求次数，不再将未记录的数据默认为零。历史未记录数据以 null / None 表示。
- 文件请求记录最终主机、字节数、总请求时间和平均传输量；httpx 流式请求额外记录响应头、首个响应体字节时间及重定向数。这些速率包含连接/等待开销，不是纯带宽。
- JSONL 保留逐次原因；TXT / JSON 保留逐篇阶段结果。暂缓与确定失败分开，任何来源超时且未获其他全文的文献可显示为待重试。
- 手动“重试 Bloom 命中未完成项”仍只选择当前集合中历史命中且缺少有效本地 PDF 的文章；先尝试 S3、Unpaywall，再进入 Sci-Hub 补救。

验证：下载测试、`scripts/test-scheduler-http.py`（真实 Chromium / httpx 访问本地测试服务器）、`scripts/test-retry-ui.mjs`（Chromium / WebKit，隔离目录中的实际 RPC）。


## 历史来源与 Sci-Net（0.5.4）

- 支持 `div.pdf iframe[src]`，相对 PDF 地址基于重定向后的文章页解析，去除 `#view` 等片段。
- 最终文件来自 Sci-Net 时显示 `Sci-Net`，不再全部记为 Sci-Hub。
- 来源存放在项目 `metadata/downloads.sqlite3` 的 `source_cache`，按 PMID + 规范化 DOI 隔离。清空 PDF / 摘要不清除此表。
- 自动回填应用旧成功下载记录，以及旧日志中确实观察到、DOI 匹配的 Sci-Net 文章页；文章页只是候选，不视为已下载。
- 已有哈希的地址优先。缓存文件必须通过 PDF 格式、页数校验，且与已验证哈希相同；内容变化或没有旧哈希时，需在正文中找到目标 DOI。失效或身份不符时继续其他来源。扫描件无法核对正文时，不通过这个缓存身份校验，但仍可尝试常规来源。
- 不缓存带查询参数的临时签名链接，不记录 Cookie 或认证信息。暂停后不重复本阶段已消耗的缓存请求；显式失败重试重新给予有限机会。
- JSON / TXT 报告包含来源缓存成功数，逐次请求包含 `known-file`、`known-page-file`、`entry-file` 路径和实际来源。
- 本轮把实验中逐篇核对 DOI 与哈希的 14 个地址写入 gut 来源缓存，没有复制实验 PDF 到项目文献库。导入记录见 `SOURCE_CACHE_SEED.json`。

正式引擎对原 20 篇样本实测：14 成功、6 未取得，约 40.06 秒；9 篇 Bloom 命中、5 篇未命中；来源分别为 Sci-Hub 9、Sci-Net 5。测试目录独立于 gut，重新从网络取得全部成功文件，并再次检查正文 DOI。见 `SOURCE_CACHE_LIVE_TEST.json`。这是此次样本实测，不保证网站后续可用性。

## Zotero 本地补充（2026-09-20）

Zotero 是最后的可选补充来源：常规网络下载阶段结束后，才处理本批次仍缺 PDF 且有 DOI 的文献；随后执行原有最终失败/延期判定、摘要回退和报告。它独立于 Fast OA 开关。独立“下载”仍只下载；项目整体流程和原有已明确选择的转换接续照常执行。

“设置 → PDF 下载 → Zotero 本地地址”默认为 `localhost:23119`，旧配置自动采用默认值；留空跳过。支持省略 `http://` 和 `/api/`，重复 `/api/` 会规范化。只允许本机回环 IP / localhost，不使用环境代理，不跟随 HTTP 重定向。只读取个人总库，不扫描群组，不写 Zotero 库/设置、不启动 Zotero、不触发同步/下载、不读 Zotero 数据库、不访问附件保存的原始网址。API 不可用时不要求用户开启任何设置。

### 保守选择规则

- DOI 只移除首尾空白、明确的 `doi:` / `http(s)://(dx.)doi.org/` 包装并忽略大小写，不删除 DOI 合法标点。搜索结果只作为候选，必须核对父条目 DOI 精确相等，排除删除条目、附件、笔记；不按标题或正文模糊匹配。
- 完整分页汇总所有重复 DOI 父条目的附件，attachment key 去重；只接受 `application/pdf`、`imported_url`、附件自己的有效 HTTP(S) URL，以及精确命中正式白名单的附件标题。未知标题即使只有一个 PDF 也拒绝；父条目 URL 不可替代附件 URL。
- 白名单位于 `services/downloader/resources/zotero-pdf-title-list.v2.json`。使用审查快照中的全部 aliases / priority / kind，不依赖 `tmp/` 或 Zotero 安装目录。标题仅作 NFKC、去首尾空白、连续空白折叠和 casefold；不去括号、不按子串放行。
- 标题、原文件名及 URL 路径中的明确 Supplement/Supporting Information/目录/中文补充材料标记，以及 `mmc1`、`MOESM1`、`ESM`、`supp1` 等带边界的路径命名会排除。URL 只检查解码后的路径，不扫描域名、查询参数或片段。普通 data、table、figure、support、s1、appendix 不直接排除正文。
- 优先级小的先选，同优先级按本机实际文件字节数降序，完全并列时随机。跨父条目统一排序，成功选择的 key 写入批次进度、来源记录和报告，状态查询不会重新抽签。保留 fulltext / accepted-manuscript / submitted-manuscript / preprint / unspecified-pdf 类型，不将所有文件声称为正式出版版。
- 只读取实际存在、非空的本机普通文件。只读 `/api/users/0/items/<key>/file/view/url` 返回 `file://` 后，由 Python 本地解码读取（空格、中文、百分号只解码一次），不会请求原始网址。损坏、加密不可读、变化中或复制失败的首选文件，尝试下一候选。分页或候选元数据不完整则整篇跳过。

### 附件名称优先级（2026-09-21，v2）

数值越小越优先。v2 保留原 v1 全部规则，仅新增用户指定的 `PDF.pdf`；原 v1 资源保留作为历史快照。新增名称按既有标准规范化后精确匹配，不扩大为任意 `.pdf` 文件名。

| 优先级 | 附件标题 |
| --- | --- |
| 10 | PubMed Central Full Text PDF |
| 20 | ScienceDirect Full Text PDF |
| 30 | Springer Full Text PDF |
| 40 | SAGE PDF Full Text |
| 100–131 | 其他已确认的出版社/数据库全文标题，各自优先级见白名单资源 |
| 200 | Full Text PDF / Fulltext PDF / Full Text / Fulltext / 全文 |
| 210 | Full Text PDF (Open access) |
| 211 | Full Text PDF (Free) |
| 220 | Fullext PDF（历史拼写） |
| 300 | Accepted Version / 已接受版本 / 接受的版本 |
| 400 | PDF |
| 500 | Submitted Version / 已提交版本 / 送出的版本 |
| 510 | Preprint PDF |
| 600 | PDF.pdf（新增，最低） |

同优先级先选本机实际字节数更大的文件；优先级和大小均相同再随机选择，成功选择记录在批次中。`PDF.pdf` 的稿件类型为 `unspecified-pdf`，不推断为正式发表版本。它仍须满足 DOI 精确匹配、`imported_url`、附件自身 HTTP(S) URL、补充材料排除与本机 PDF 可读性校验；仅磁盘文件名为 `PDF.pdf` 不会让未知附件标题通过。

### 时限、发布与收尾

| 范围 | 上限 |
| --- | --- |
| 每次进入阶段探测一次真实 Local API | 2 秒 |
| 每个 HTTP 请求（包括持续响应） | 3 秒 |
| 每 DOI 的查询、路径解析、文件读取/复制/校验、锁与发布 | 15 秒 |
| 整个 Zotero 阶段，包括排队 | 60 秒 |
| 同时工作的 DOI 辅助进程 | 2 |

内部提前保留进程回收与诊断写入时间，因此实际查询窗口略短于表中上限；辅助进程强制结束后回收等待最多 0.5 秒。SQLite 等待在本阶段限为 0.2 秒；收尾批量写入诊断，避免对每个排队条目重复等锁。OS/磁盘故障不作绝对时限保证。单个 API 响应最多 4 MiB，每 DOI 累计最多 80 MiB；每个列表最多 50 页 / 5,000 项；单 PDF 最多 256 MiB。超过限制保守跳过，不使用部分候选集合。

探测访问个人库 API，而不是 Connector ping。403/404/501、拒绝连接、错误 JSON、重定向等跳过阶段，不逐篇重复探测；中途服务不可用时停止后续查询。普通 Zotero 错误不暂停整批，不新增网络阶段的 deferred 标记；原有失败/延期含义保留。暂停/取消仍传递给下载控制逻辑，已成功的其他文献保留，未完成项由原控制流程转为 paused/cancelled。

文件复制、哈希、pypdf 校验和发布在可终止的独立进程内完成，超时/取消强制结束并回收；不使用无法终止的解析线程。文件复制至批次 staging，核对复制前后源文件指纹及校验前后暂存文件指纹。统一 `publish()` 内在文件锁下再次检查当前 DOI、成员生命周期、清空标记、任务控制和目标文件变化，复用同一份暂存文件的校验，不再进行一次无界解析；原子发布为 `pdf/<PMID>.pdf`。新出现或改变的项目 PDF 不覆盖。

来源记录包括 Zotero、DOI、父条目/附件 key、附件标题、规则 ID/版本、优先级、实际大小、SHA-256、稿件类型与来源域名；不保存附件原始 URL 的查询参数。TXT/JSON 报告、JSONL 事件和逐篇进度能看到结果及跳过/中断原因。批次结束后的项目根目录 `literature_without_pdf.txt` 和日志目录的同名批次清单均使用最终状态。

### 验证与平台范围

- `runtimes/downloader/bin/python -m unittest discover -s services/downloader/tests -p test_zotero.py`：本机模拟 API、小型 PDF、超时/取消/卡住解析/锁竞争/生命周期变化等隔离测试。
- `runtimes/downloader/bin/python scripts/test-zotero-integration.py`：真实 Python RPC 和独立下载 worker，模拟慢响应和成功路径，检查代理绕过、报告、两份缺失清单、转换接续；不使用用户真实库或模型。
- 本机 Zotero 9.0.6 安装资源只读核对了个人库和文件 URL 路由；真实 Local API 探测返回 403，确认跳过行为。真实库附件成功复制未做端到端验证；全部成功路径使用隔离 fixture。
- macOS 已实际验证。Windows 的文件 URL 驱动器解码、隐藏辅助进程与终止分支已实现，Windows/Linux 尚未实机验证；不支持远程 UNC 文件 URL。
- 不重新打包桌面应用。重新打开开发版后，在设置中保留默认地址即可；服务不可用时正常结束。

本轮结果：全量后端 195 项通过（含 Zotero 专项 34 项），独立下载 worker 离线集成测试通过，前端 TypeScript/Vite 构建通过（保留已有 >500 kB 体积提示）。

## 项目级 PDF 来源报告

项目根目录的 `literature_pdf_sources.txt` 与 `literature_without_pdf.txt` 使用相同的刷新时机：下载批次正常完成，以及“获取 PDF → 检查本地文件”完成后；一键更新文献的文件检查步骤也会刷新。报告使用整个当前 XML 集合，而非本批次选中的文献，原子覆盖旧报告。

内容为更新时间、有效 PDF 总数、各具体来源数量，以及按 PMID 数值排序的逐篇列表（PMID、相对 PDF 路径、来源）。来源包括 Sci-Hub、Sci-Net、Zotero、PMC S3、Unpaywall、Europe PMC、用户提供或关联等；不合并为笼统的“其他”。不包含原始下载 URL、认证参数或 Zotero 本机存储路径。

来源记录须与实际有效文件的 SHA-256 匹配。没有匹配记录则标记未知；手工补充/替换后执行检查，登记为用户提供；恢复冗余 PDF 时仅在文件哈希一致时保留原来源。缺失、损坏、已移出当前集合的备份文件不进入来源清单。没有有效 PDF 时仍生成总数为 0 的报告；当前 XML 缺失或损坏时保留上次报告，避免误清空。

验证入口：`test_missing_pdf_report.py`（两个触发入口、全项目统计、替换与删除、归档恢复、未知来源及空集合），以及 `scripts/test-zotero-integration.py` 的真实独立下载 worker 离线测试。

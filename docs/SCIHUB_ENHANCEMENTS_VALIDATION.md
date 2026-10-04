# Sci-Hub 浏览器增强验证 — 2026-09-21

本轮保留正式 Playwright Chromium，接入多候选解析、身份检查和有限分片/页面补救；Altcha 独立实现与验收。没有改为 HTTP 下载，没有新增 CDN、前端验证码界面或长期登录功能，没有重新打包。

## 实现与范围

- `services/downloader/scihub_candidates.py`：真实 DOM 候选，忽略占位链接，有限同主机分片变体。
- `scihub_identity.py`：复用正式 PDF 校验，独立可终止进程内检查 DOI/完整标题，三态结果与文件哈希绑定。
- `scihub_altcha.py`：同站点有界挑战协议、合作式可取消计算、算法/工作量上限。
- `scihub_browser.py/.mjs`：保留当前页面供显式协议请求，成功验证的 Cookie 仅批次内按站点共享；导航/下载仍是真实 Chromium。超时关闭 context 后，后续镜像可使用新的 context，浏览器崩溃不回退 HTTP。
- `scihub_retry.py`：所有候选复用原入口锁/文件信号量、请求与等待预算。每镜像一次访问机会，内部验证重放/刷新分别记账，恢复不重新获得机会。
- `engine.py`：待核验文件保存到批次日志；正常发布使用原 guard/原子操作并复查暂存文件指纹。来源顺序、Bloom 两轮和 Zotero 最后补充保持不变。

备份：`backups/scihub-enhancements-20260921-022637/`。未改动 Zotero 库或设置。

## 隔离验证

实测环境：macOS Apple Silicon，项目内 Python 3.12、Node/Playwright，Chromium `153.0.8010.12`。Windows/Linux 未实机验证。

| 检查 | 结果 |
| --- | --- |
| 全量 `services/downloader/tests` | **226 项通过，71.217 秒** |
| 新增 `test_scihub_enhancements.py` 独立执行 | **12 项通过** |
| `scripts/test-scihub-browser-integration.py` | **通过**，真实 Rust RPC → 独立 worker → 本地 HTTP fixture → Chromium |
| `scripts/test-scheduler-http.py` | **通过**，38 篇本地调度，17 个命中组先于 21 个未命中组完成 |
| Node 语法检查 / Python 编译检查 | **通过** |

新增专项覆盖：SHA-256/384/512、超大/未知/不可解挑战、求解取消、同 origin 限制；真实 Chromium 协议 GET/POST/重放、批次 Cookie 复用与跨批次清除；动态链接与空 object；明确错档后尝试下一候选、标题匹配但无 DOI 的 PDF、扫描件待核验；404 分片补救、有限页面刷新、429 不扩散请求、挑战循环退出、协议取消。

保留并通过的浏览器检查包括 inline/attachment、非 PDF、403/429、完整响应体超时、暂停/取消、Node/Chromium 异常退出、宿主退出、临时资源回收及日志脱敏；新增同逻辑会话超时后能继续下一镜像的检查。

RPC 集成实际验证 Altcha、JavaScript 链接、原生附件下载、身份结果和来源登记；缓存复用、移出集合及用户替换文件时禁止覆盖；待核验 PDF 确实落入日志目录、仍在缺失清单中，未进入 Markdown/向量流程；暂停/恢复的请求机会不重放、显式重试可继续。

本轮未修改前端或 Rust，因此未重新运行前端/Rust 构建，也未重新打包。

## 已有实验文件离线复核

使用实验 `out/result_v4_120.json` 的 DOI/标题和当时目录中的 120 份 PDF，以本轮身份规则复核：**114 匹配、5 待核验、1 不匹配**。那份已知哲学论文错档仍被拒绝。5 份待核验包括扫描件及身份信号不足的文献，不当成已证实错档。

这是启发式规则的本地复核，不是人工逐篇确认，也不是本轮外网成功率。实验记录标题存在截断，多个实验共用 PDF 目录，缺乏每轮不可变哈希清单，因此不能据此追溯保证原始每轮文件身份。正式运行使用完整项目标题。明细见 [离线记录](SCIHUB_IDENTITY_OFFLINE_VALIDATION.json)。

两个 `ref/*.html` 保存页面实际各有一个去重后的显式 PDF 地址；原型第二个地址来自正则再次截取绝对 URL 内的 `/storage/...`，随后拼接入口主机。正式实现不把这种派生地址当作页面提供的真实候选。此前分析中“两个真实候选”的表述在此更正。

## 正式 worker 的两篇外网验证

重新读取 BD2026 当前 XML/文件和任务状态后，仅选取两篇缺失文献。使用正式 Python RPC 启动独立下载 worker；只对该验证批次关闭其他下载来源，未改全局配置。

- 批次：`d483fefc20e94167bc6d9c1afd74d17c`。
- PMID **23143223、23766348** 均成功，来源 **Sci-Hub**，传输 **playwright-chromium / browser-download**，身份结果均为 **DOI 匹配**。
- 本次约 **6.62 秒**，8 次显式入口请求（含 6 次挑战 GET/POST/重放）、2 次显式文件请求。不是全浏览器网络子请求总数。
- XML **148** 篇；有效 PDF **53 → 55**，项目缺失清单 **95 → 93**。原 53 份有效文件哈希不变。
- 全局下载配置不变，没有触发 Marker、索引或模型调用，Zotero 未访问或修改。

本次两篇成功不能外推稳定成功率。正式报告位于 `workspace/BD2026/logs/d483fefc20e94167bc6d9c1afd74d17c/download_report.json`；脱敏摘要见 [真实验证记录](SCIHUB_ENHANCEMENTS_LIVE_VALIDATION.json)。

## 使用与限制

继续使用开发版；下一次下载 worker 启动即加载新代码，不需要重新打包或重启前端窗口。已经运行的 Python worker 不会热替换，须让当前批次收尾后再启动新 worker。

待核验文件位于 `logs/<batch>/identity_pending/<PMID>/`，原件和 JSON 证据保留；不会进入正式 PDF 目录或自动全文索引。人工核验后可用已有“关联本地 PDF”功能纳入。旧项目 PDF 和其他来源的成功规则没有批量重判。

身份检查仍可能无法确认扫描件、损坏文本层、通用短标题或前置封面较长的文献；这些文件明确保留待核验。尚不支持图像验证码、人工验证入口、持久化登录或任意其他挑战协议。

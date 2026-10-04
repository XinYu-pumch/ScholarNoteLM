# 正式 Sci-Hub Chromium 传输验证

日期：2026-09-21。平台：macOS Apple Silicon；使用项目已有 Node、Playwright 及 Chromium 153.0.8010.12。没有安装新运行时、启动可见浏览器或重新打包应用。Windows/Linux 的进程控制分支尚未实机验证。

## 实现范围

- `services/downloader/scihub_browser.py`、`scihub_browser.mjs`：按批次延迟复用真实后台 Chromium，JSONL 控制及临时文件传递；每篇每轮独立 context、同篇共享页面/文件会话；全过程预算、取消、故障与退出清理。
- `scihub_retry.py`：替换默认访问客户端，补充实际传输/方法/自动子请求指标与安全错误分类；原有镜像、缓存、来源区分及 PDF 校验条件保留。
- `engine.py`：正式 worker 持有浏览器池；浏览器故障明确延期；Sci-Hub 发布时在原有原子发布流程中复查任务、当前 DOI、生命周期和目标文件变化。
- `badr_sources.py`：去掉 Sci-Hub curl 请求，旧兼容入口委托新正式实现；其他来源访问客户端不变。
- README、PDF 下载文档和相关测试同步更新。未修改前端/Rust，无需对应构建，不产生新的桌面安装包。

## 隔离验证

所有测试项目和 HTTP 服务在临时目录/本机回环运行，不调用用户模型、不扫描或修改 Zotero 库。

| 入口 | 验证内容 |
| --- | --- |
| `test_scihub_browser.py`：10 项 | 执行 JS 后才出现的链接；文章/文件 Cookie 共享和跨篇隔离；自动 iframe 不绕过文件调度；inline / attachment；原签名/可读页数、空白无 DOI PDF；验证码、403（包括错误 PDF MIME）、429、非 PDF；慢响应体和导航超时；取消及启动中取消；Node/Chromium 崩溃；worker 突然退出后的浏览器与临时配置清理；签名参数不入日志 |
| `test_scihub_retry.py`：22 项 | Bloom 分组、两轮轮换、队列/预算、并发限制、跨项目 OS 入口锁、暂停/继续与重试、镜像退避 |
| `test_source_cache.py`：9 项 | Sci-Net 标签、历史来源、哈希变化后的 DOI 身份校验、缓存隔离 |
| `scripts/test-scheduler-http.py` | 真实 Chromium 访问两个本地入口，38 篇、17 篇 Bloom 命中先完成，21 篇未命中随后处理；单入口峰值 1、不同入口可并行；原 httpx OA 慢流超时检查 |
| `scripts/test-scihub-browser-integration.py` | 真实 Rust `download.start` → Python 独立 worker → Chromium → 校验/发布/来源与报告；状态设置查询不启动浏览器；哈希一致缓存复用；下载中移出集合/用户替换 PDF 拒绝覆盖；暂停/取消清理、继续不重放已耗入口、显式重试；宿主退出暂停；不接续转换/索引 |

完整后端回归 **213 项全部通过**（61.276 秒，包含上面的浏览器专项与原有各模块测试）；Node 语法检查与 Python 编译检查通过。损坏 PDF 等负例会产生预期解析器诊断，不能把测试日志中的负例 traceback 单独理解为套件失败。

## 真实项目小样本

只选 BD2026 当前 XML 中缺失有效 PDF、Bloom 命中的前两篇，通过正式 `engine.rpc('start')` 创建真实下载批次并启动正式独立 worker。为隔离 Sci-Hub 效果，仅对这个批次关闭其他可选来源；全局下载配置原样保留。未清空项目、未重复下载已有文献、不触发 Marker/Embedding/模型调用。

批次：`8f05dd74bbb84b538d1d847573335674`，约 26.75 秒，16 次显式入口调用、1 次显式文件调用；浏览器自动子请求另行计数。

| PMID | 结果 |
| --- | --- |
| 23052559 | Sci-Hub 成功；`transport=playwright-chromium`、`transferMethod=browser-download`，902249 字节，13 页；通过原 PDF 校验及发布前生命周期复查 |
| 23143223 | 未取得有效 PDF；实际请求记录有验证码页、403、临时服务器错误 |

本次前后 XML 都为 148 篇；有效 PDF **52 → 53**，缺失 **96 → 95**。原有 52 份有效 PDF 的 SHA-256 全部未变，新文件和准确来源保留在项目内，两份项目报告已刷新。结果不代表稳定成功率，不与历史 10 篇实验直接合并计算。

机器记录：[SCIHUB_BROWSER_LIVE_VALIDATION.json](SCIHUB_BROWSER_LIVE_VALIDATION.json)。逐请求报告位于当前 BD2026 项目 `logs/8f05dd74bbb84b538d1d847573335674/`。未更改历史实验文件；其旧结果与额外 DOI 文本门槛的说明仍按历史报告理解。

## 开发版生效

没有重新打包。前端/Rust 未变，无需为此重启开发窗口；Python 下载 worker 下一次启动加载新实现，已在运行的 worker 不热替换。此次真实验证已结束，浏览器和 worker 已退出。新开下载任务即可使用 Chromium；旧桌面副本不随源码更新。

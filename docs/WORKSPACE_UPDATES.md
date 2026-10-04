# 工作区与文献流程更新（2026-09-20）

本次修改不自动重新下载、转换或生成用户项目，不改分块算法和写作模型。

## 页面与大纲

工作区导航按项目概览、检索工作台、文献库、综述工作台、文献问答、阅读与笔记排列。概览移除项目列表，使用当前项目 XML、有效 PDF、当前模型索引及真实综述目录的统计。

综述主题、要求、大纲默认只读。点击编辑才开放修改，保存后退出编辑；取消恢复保存稿。CSV 编辑先校验进入草稿，需保存才落盘。跨页面/项目导航有未保存修改保护。新建工作区选择文件来源时支持 UTF-8（含 BOM）CSV，复用后端树结构校验，校验失败不创建目录。原文件逐字保存为 imported.csv，outline.csv 是规范化当前大纲；review.json 记录来源、文件名、时间及哈希。恢复原始大纲按来源选择 imported.csv 或 generated.csv。

## 文献更新

library.start 启动 library_worker.py，依次完成本地同步、缺失全文获取、缺失/过期文本转换、当前模型索引更新。阶段状态持久化到 metadata/library-job.json 和 logs/library-*/result.json。离开页面不影响接续；当前 XML 改变时停止并要求重新执行。用户停止流程时同步停止子任务；完成状态在阶段进程退出后发布。

日常一键流程保留已有下载失败后的摘要替代；“获取 PDF → 下载”允许再次尝试缺失 PDF。单独 markdown.start 默认 indexAfter=false，只有历史明确请求的下载接续保留旧兼容路径。新一键流程不依赖 autoIndex 设置。

正常 vector.start 跳过最新文献，按 Embedding 输入哈希复用缓存。indexed_metadata 单独记录投影到 Chroma 的 metadata 签名，因此只改日期、作者等字段无需调用 Embedding。完整篇名、作者、期刊、日期及其精度、章节路径等写入 Chroma；复杂数据编码为 JSON 字符串以兼容本地 Chroma 1.3.7，SQLite 保留原结构。

index 模式：

- incremental：补齐缺失、更新过期和 metadata；移除当前文献已替换的 Chroma 记录。
- rebuild：重建当前模型的索引登记和记录，复用有效缓存；缺失缓存仍需请求 API。
- recompute：显式删除当前模型缓存后重算，需项目确认。

## 清空与失效

library.plan 返回项目范围内的文件数量；library.clear 需 confirm=项目 ID，通过独立后台任务停止并等待下载、转换、索引、综述任务及清理进程结束，再在项目操作锁、Chroma 锁及文件锁下删除。

- pdf：删除活动 PDF、摘要文件、打包文件、Markdown 全家族、转换记录和全部 vectors。冗余 PDF 默认保留，可明确勾选删除。
- markdown：删除原稿、清洗稿、图片、转换记录及全部 vectors；保留 PDF。
- index：删除整个 vectors（Chroma、缓存、块及快照），保留 PDF/Markdown。

所有范围保留 XML、检索式、笔记、综述及综述证据快照。index-generation.json 使准备计划失效，但不删除既有正文。index-cleared.json 阻止状态轮询自动创建索引数据库；再次明确建立索引时解除。pdf-cleared.json 阻止清空后自动恢复冗余 PDF，明确下载、检查本地文件或一键更新时解除。

清空前预检查目录中符号链接；任何相关任务未退出时不会删除文件。新启动操作被流程所有权拦截。一键下载阶段暂停后可以继续该批次。

## 验证

- 106 项 Python 测试：综述 39、文件状态 11、向量 13、Markdown/同步 18、下载 13、新增工作区/清理 12。
- Rust research-cli 8 项测试；TypeScript 与 Vite 构建。
- scripts/test-library-pipeline.py：真实 Rust RPC、独立协调/下载/Marker/Chroma 进程，本地模拟 Embedding。验证重复更新零新增调用、metadata 更新零新增调用、完整 Unicode 篇名、重建复用/强制重算、单独转换、CSV 原样导入、清理等待活跃任务且不被轮询复活。Marker 使用准备好的原稿，不运行模型推理；下载关闭 OA，使用无 DOI 条目，不请求外网。
- scripts/test-vectors-integration.py：真实 Chroma、失效过滤、缓存复用、删除、失败后继续及维度检查。
- scripts/test-review-writing-integration.py：两阶段写作、失败重试、外部文件变化、取消与导出回归。
- scripts/test-workspace-update-ui.mjs：独立临时项目及预览服务，真实导入/保存接口；下载/转换/索引/清理按钮只检查请求，不执行真实任务。验证只读/编辑/取消/导航保护、CSV 文件选择及错误、各按钮范围、metadata 和窄窗口布局。

运行 UI 测试前先构建前端与 research-cli：

```sh
./scripts/npm-local.sh run research:build
./scripts/npm-local.sh run build
PLAYWRIGHT_BROWSERS_PATH="$PWD/runtimes/playwright" TMPDIR="$PWD/tmp" \
  runtimes/node/bin/node scripts/test-workspace-update-ui.mjs
runtimes/downloader/bin/python scripts/test-library-pipeline.py
```

UI 测试默认使用 4174 端口，可通过 UI_TEST_PORT 修改。截图在 tmp/workspace-ui-screenshots/，数据在独立临时目录中，完成后清理。当前只在 macOS 验证，未新增 Windows 实机验证。Vite 仍有既有 bundle 大小提示。

## 追加：项目根目录缺失 PDF 清单

下载批次正常结束（包括部分条目失败/延期），或点击“获取 PDF → 检查本地文件”完成后，更新项目根目录的 `literature_without_pdf.txt`。一键更新的本地同步阶段也会刷新该清单。文件只包含当前 XML 内缺少有效 PDF 的 PMID，每行一个，按数值排序；全部齐全时原子覆盖为空文件。检查包含手动添加、删除、损坏及冗余恢复的 PDF，不依据历史下载成功/失败标签。没有 XML 或 XML 无效时不覆盖旧清单。

日志目录中的同名文件继续记录对应下载批次，保持原有行为。新增 `test_missing_pdf_report.py` 的 5 项测试，连同下载、Markdown/同步、工作区维护共 48 项测试通过；包括真实下载批次函数的本地模拟来源测试，不访问外网。

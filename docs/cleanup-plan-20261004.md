# 冗余功能、代码与文件清理规划（2026-10-04）

只做规划，未改动代码。依据来自三路只读调研：前端引用图、后端引用和数据核对，以及磁盘盘点。关键结论都经过 grep 抽查。行号为调研时的近似位置。

## 0. 前置条件（必须先做）

1. **建立版本控制。** 项目目前不是 git 仓库，现在靠 `backups/<日期>/` 手工复制文件来防误改。删代码前先 `git init` 并做一次基线提交，`.gitignore` 已经现成。之后不再需要按日期复制源码备份。
2. **记录测试基线。** downloader 共 516 个测试，其中 `test_pipeline.test_timeout_proceeds_to_scihub_and_slow_rescue_is_opt_in` 在清理前就已经失败，需要单独处理或先标注，以免和清理引入的回归混在一起。另有 Rust 27 个测试、约 50 个集成 / UI 脚本。
3. 每个阶段单独提交，阶段结束时运行 `npm run build`、downloader 全量测试、`cargo test`，以及与本阶段相关的 UI 脚本。

## 1. 第一阶段：删除死代码（零行为变化，低风险）

判定标准：生产代码中零引用，只有测试或已失效的 mock 引用的也算在内。

### 前端（`apps/desktop/src/`）

| 项目 | 位置 / 规模 | 连带清理 |
| --- | --- | --- |
| 旧演示版综述页 `Review`、`OutlineModal`、`Chat` 再导出 | `Workspace.tsx:10–38`，约 7.4 KB；`App.tsx` 只导入了 `Reader` | `ui.tsx` 中的 `EvidenceCard`、`downloadText`；后端 `storage.markdown` RPC（`engine.py` 约 1115 行，唯一调用方就是它） |
| `MarkdownPanel`、`VectorPanel` | `Markdown.tsx:12–21`、`Vector.tsx:40–46` | `markdown.css`；`vector.report` RPC（唯一调用方是 VectorPanel） |
| 打不开的"发现新的文献"弹窗 `SearchModal` | `Library.tsx:82–90`（`setSearchOpen` 只会被设为 false） | 未使用的 `input` ref |
| `suggestions`、`demoAnswer` | `data.ts:41–49` | — |
| Vite 原型存储中间件 `/__prototype/*` | `vite.config.ts:8–43` | UI 测试脚本里残留的对应 route mock |
| 未使用的 import 和多余的 export | App.tsx 有 8 个图标未用，Vector / Workspace / Library 等也有；约 15 个只在本文件使用的 export | — |

### 后端（`services/downloader/`、Rust）

| 项目 | 位置 / 规模 | 注意 |
| --- | --- | --- |
| 旧 Europe PMC 补救链等 | `badr_sources.py` 第 13–591、648–668 行，约 600 / 668 行；生产代码只用到 `normalize_doi_for_scihub`、`SciHubBloomFilter` | 同步删除 `tests/test_downloads.py:90,112` 的两个 mock |
| 旧的一次性 PMID 写作提示词与修复路径 | `review_format.py` 约 230 / 290 行；`review_writing.py` 中的 `writing_prompt`、`prompt_messages` | 保留 `FORMAT`（参与单元签名）、`materials`、`public_part`、`_sections_to_markdown_content`；同步调整 `test_review_format.py` |
| 零引用的小函数 | `qa_service.section_label`、`NON_EVIDENCE`；`conversion_config.engine`、`digest` | — |
| 不会再触发的分支 | `engine.backfill_sources`（6 个项目的一次性标记都已设置）；`artifact_state` 中的 `'enhanced'` 判断；`engine.py:1076` 删除 `downloaded_literature-*.zip`；`vector_chunks.py:249` 每次同步都建空目录 `vectors/chunks/redundant/`（与 10-04 修复的问题同类） | — |
| 没有任何调用方的 RPC | `download.reconcile`、Rust 的 `probe`（及只供它使用的 `mesh_check`）、`filters.save` 错误桩、LLM 的 `profile.activate`、`review.retrieval.*`、`review.version.*` 拒绝桩 | `review.version.*` 有一个测试，需同步删除 |
| 前端缓存失效规则过时 | `research-api.ts:41–46` 列出了已不存在的 `xml.import`、`corpus.*`、`profile.activate` | **漏掉了 `qa.resume`、`qa.regenerate`、`chat.archive_many`，可能导致缓存不刷新的 bug**，修正时一并核实 |

### 死 CSS（约 3,400 行，单独提交）

主要分布：`styles.css` 约 1,400 行（旧演示聊天、旧概览、旧综述），`workbench.css` 约 770 行，`literature-workflow.css` 约 370 行，`review.css` 约 300 行（已删除的版本栏和召回 / 重排设置）。这些数字是按类名 grep 得到的估算，动态拼接的类名（`page-*`、`status-*`）已按"在用"处理。删除后需要跑截图和视觉对比脚本复核。

## 2. 第二阶段：兼容代码（数据已迁移完，可直接删除）

逐项核对过 `workspace/` 中的实际数据，确认已经没有依赖这些代码的数据：

| 兼容代码 | 磁盘数据现状 | 处理 |
| --- | --- | --- |
| 综述 schema-1 的 `versions/` 迁移（`review_service.py:135–157`、多余的 `vid` 参数、`review_worker --version`） | 10 个 `review.json` 全部是 schema 2；只剩 `gut/review/test1/versions/v0002`，已迁移 | 删代码；把 v0002 目录归档到 backups |
| `review-unit-shared-pool-v1` 读取（`review_bundle.py:9, 198–209`） | 只在 `logs/` 中出现，正式片段里没有 | 删除，保留 v2 |
| 旧目录布局迁移（`storage.py:96–190`） | `migrated=true`，`data/projects` 不存在 | 精简，但保留全新安装的初始化路径 |
| `notes/notes.json`、`reviews/drafts.json` 的写入（`storage.py:211`） | 6 个项目的 `reviews/` 都只有一个 71 字节的空草稿，`summaries/` 全部为空 | 删写入逻辑和这三个空目录（`notes` 见第三阶段第 2 项） |
| 单配置 Embedding 格式和 `config/retrieval.json` 的兼容分支 | 已是多配置格式，`retrieval.json` 不存在 | 删分支；**保留配置 ID `legacy`**，它就是当前启用的配置 |
| LLM 配置的旧字段（`research.rs:1383–1393, 2315–2321`；`sendTemperature`） | 现存 3 个配置都不含这些字段 | 删除。但 `sendTemperature` 参与问答和写作的缓存签名，直接删会让所有已准备的写作材料变成"过期"，需要在签名里保留一个固定值 |
| 旧对话迁移成聊天线程（`research.rs:112`） | gut 已完成迁移 | 删除 |
| 问答单任务指针 `active.json`（`qa_service.py:176–178, 277–281`） | 每次提问仍然会写 | 停止写入，保留读取（旧运行记录要用） |
| `markdown/redundant`、`abstracts/redundant` 的清理逻辑（`corpus_files.py`） | 各项目已对账完毕，只剩空目录 | 全项目再对账一次后删除 |

## 3. 第三阶段：需要你做产品决定的事项

1. **新安装会注入演示项目。** `storage.ts:12–13` 在没有状态文件时会用 `seedState` 在磁盘上注册两个演示项目（12 篇 `DEMO-*` 文献）。`App.tsx` 已经有"还没有研究项目"的空白引导页。**建议删除演示数据**，连同 Reader 和 Library 里的 DEMO 分支、"示例文献"标记。
2. **"阅读与笔记"页的去留。** 这个页面已经能显示真实摘要、PDF 状态和笔记，但还残留演示分支；"继续阅读"只是取前 6 篇，并没有真正的阅读记录；Cmd+K 搜索的是前端保存的文献副本。笔记和星标只存在原型状态 `data/prototype/state.json` 里。
   - 保留：去掉演示分支，把笔记和星标迁到项目文件中。
   - 删除：需要先导出已有笔记。
3. **`Project` 类型里的原型字段。** `messages`、`tasks` 从不被读取，可以直接删；`sections` 随第一阶段的旧综述页一起删；`papers` 是后端文献集合的前端副本，取决于第 2 项的决定。
4. **Chroma 向量库（磁盘收益最大）。**
   - 综述和问答检索都直接从 `chunks.sqlite3` 的向量缓存做余弦排序（`review_retrieval.APIRecall`），并不查询 Chroma。
   - Chroma 在查询时唯一的使用者，是"文本块"调试面板的 `vector.search`。
   - 它却占用约 1.5 GB（gut 447 MB、PrimaryMN 317 MB、HLH 202 MB 等），还附带专门的写入锁、清理 worker（`services/vectors/cleanup.py`）和"已发布"登记状态。README 也提到过"Chroma 已发布数为 0、但综述正常生成"带来的困惑。
   - 方案 A：保留现状。
   - 方案 B：调试检索改用 `APIRecall`，移除 Chroma 写入、锁、清理 worker 和磁盘数据。
   - 方案 B 是架构改动，需要先确认索引阶段的"就绪"判断不依赖 Chroma。**收益高，风险中等。**
5. **问答"文献概览"模式与旧 agent 循环。** 主题问答已全部走 `qa_mini_review`；`qa_service.py` 约 712–915 行的旧循环只服务于概览模式，`toolsPerRound`、`maxSteps`、RCS 相关配置也只对它生效。RCS 在界面里无法开启，README 却仍写着"可选 RCS"。可以选择保留概览模式并更新 README，或者连同模式一起删除。
6. **旧 BADR 格式综述片段。** 仍有 82 个片段文件在用：HLH/review/HLH 28 个、HUSandgene/review/aHUSandgene 23 个、gut/review/test2 31 个。只有这 3 个工作区重新生成或转换格式之后，`review_format`、`review_content`、`review_manuscripts` 里的兼容读取才能删除。
7. **Markdown 清洗的旧配置键（`badrCleanup` 等）。** 它们已经不起作用，但参与了清洗签名的计算。直接删除会让全部 Markdown 被判为过期。正确做法是换成一个固定常量，并保证计算出的签名与现在完全一致。
8. **只被测试使用的后端接口。** `xml.import` 被约 12 个脚本和 2 个 Rust 测试用来导入测试数据，`download.import`、`download.clear`、`review.import`、`chat.archive`、`qa.status`、`qa.delete` 也只被脚本或测试使用。建议保留并标注为测试专用，或者把它们收进测试工具里。不要直接删除。
9. **`vectors/chunks/*.jsonl` 导出副本。** 每个项目 40–175 MB，内容与 `chunks.sqlite3` 重复，而 `vector.export` 已经能按需导出。可以改成用到时才生成。

## 4. 第四阶段：重复实现的合并（选做，中等风险）

- **流式 LLM 客户端有三份**：`review_service.py:335–383` 和 `review_llm.chat` 是两份 Python，Rust 里还有 `llm_stream`。Python 的两份应合并成一份。
- **模型 JSON 输出解析有两套**（`review_llm.object_json`、`qa_protocol`），严格程度不同，需要先统一规则。
- **小工具函数重复**：`normalize_pmcid` 有 2 份、`atomic()` 有 2 份、`read(path,default)` 有 4 份。
- **前端两套对话侧栏逻辑**：`SearchChat` 和 `LiteratureQA` 重复实现了线程列表、选择、删除后切换，可以抽成一个 `useConversationThreads` hook；`LiteratureQA` 侧栏底部还多一组重命名 / 删除按钮，和行菜单重复。
- **CSS 交叉覆盖**：121 个类名在多个 CSS 文件中都有样式，应在死 CSS 删除之后再合并。

## 5. 文件与磁盘（不涉及代码）

| 项目 | 大小 | 性质 | 建议 |
| --- | ---: | --- | --- |
| `workspace/*/qa/runs/*/*.prompt.json` | gut 单项目 776 MB（9-27 已删除的"补读全文"流程，单个文件 10–13 MB）；新版约 4–6 MB / 次 | 调试落盘 | 旧运行只保留 `evidence.json` 和结果，提示词打包归档；新运行改为压缩保存或只在失败时保留（需要代码改动） |
| Chroma 数据 | 约 1.5 GB | 取决于第三阶段第 4 项 | 决定之后再处理 |
| `cache/tauri-target` | 2.0 GB | 编译缓存，可重建 | 需要空间时再删，代价是下次全量编译 |
| `backups/history-20261002.tar.gz` | 1.2 GB | 历史归档 | 建议移到项目目录之外长期保存 |
| `backups/` 下按日期的源码副本（gui-polish 等 4 个目录） | 约 1 MB | 有 git 之后就多余了 | git 基线提交后删除 |
| `dist/macos/ScholarNoteLM.app` 和 `启动 ScholarNoteLM.command` | 81 MB | 9-29 的旧包，README 已说明不会随源码更新 | 删除，或在启动脚本里提示版本过期；`dist/ui` 是构建产物 |
| `gut/packages/current-literature.zip` | 209 MB | 用户自己的"打包"导出（功能仍然有效），可重新生成 | 你决定是否保留 |
| `logs/`（应用根目录） | 34 MB | 开发和测试日志（storage-cleanup、mn-workflow 等） | 归档到 backups |
| `docs/` | 41 MB | 24 个测试结果 JSON、24 个日期目录、14 MB 截图 | 历史验证材料移到 `docs/archive/`，索引只保留现行文档 |
| `ref/` 两个 Sci-Hub 页面快照 | 7.5 MB | 没有任何引用 | 确认不再需要后删除 |
| `scripts/smoke-test.mjs`、`visual-check.mjs` | — | 测的是早期原型（README 也标注了可能不适用） | 删除 |
| PrimaryMN 专用的一次性脚本（`audit-primarymn-vectors`、`benchmark-embedding-*`、`watch-embedding-primarymn`、`report-embedding-throughput`） | — | 一次性分析工具 | 移到 `scripts/archive/` |
| 空目录：`experiments/`（只有 README）、`packages/`、各项目的 `summaries/`、`vectors/chunks/redundant/`、`abstracts/redundant/` | — | — | 随第一、二阶段一起清理 |
| `未命名文件夹/pubmed检索提示词.txt` | — | 你的个人笔记 | 你决定放到哪里 |
| `.DS_Store` | 42 个 | 系统文件 | 已在 `.gitignore` 中，可直接删除 |
| `installers/marker/*.whl` | 12 MB | `setup-marker-local.py` 仍在使用 | 保留 |
| `tmp/claude-run/` | 2.8 MB | 本次运行的辅助脚本 | 可以删除 |

## 6. 建议执行顺序与预估收益

1. **第 0 步**：git 基线提交，标注已有的测试失败。
2. **第一阶段**：约 900 行 Python、约 15 KB TSX、约 3,400 行 CSS，不改变任何行为。同时修正缓存失效规则中可能存在的 bug。
3. **第二阶段**：约 300–400 行兼容代码，加上 4 类空目录。
4. **第五节的文件整理**：不涉及代码，可与第一、二阶段并行。仅问答旧提示词归档就能腾出约 0.8 GB。
5. **第三阶段**：每一项决定之后单独实施，其中 Chroma 一项预计可再腾出约 1.5 GB 并简化索引流程。
6. **第四阶段**：在前面各阶段稳定之后再做。

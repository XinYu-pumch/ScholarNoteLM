# 文档索引

以下说明以当前源码为准。根 README 保留产品约定与入口，专题文档维护各自功能细节；历史规划、实跑数字和旧协议不作为现行规范。被合并或删除的旧文档仍可从 Git 历史查阅。

## 接手与维护

| 文档 | 内容 |
| --- | --- |
| [根 README](../README.md) | 当前功能、产品决定、已知边界、架构入口 |
| [AGENTS.md](../AGENTS.md) | 开发约束与验证要求；CLAUDE.md 引用同一规范 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | 启动、运行时、RPC、隔离测试 |
| [LOCAL_MAINTENANCE.md](LOCAL_MAINTENANCE.md) | 缓存清理与不可误删的依赖、数据 |
| [PROJECT_STORAGE.md](PROJECT_STORAGE.md) | 项目布局、迁移、删除、紧凑存储 |
| [ARTIFACT_LIFECYCLE.md](ARTIFACT_LIFECYCLE.md) | 归档恢复、内容指纹与更新判定 |

## 功能与协议

| 文档 | 内容 |
| --- | --- |
| [SEARCH_WORKBENCH.md](SEARCH_WORKBENCH.md) | PubMed 数量边界、Zotero 导入、JCR、MeSH、检索助手 |
| [PDF_DOWNLOADS.md](PDF_DOWNLOADS.md) | 下载来源、队列、身份校验、预算与报告 |
| [MARKDOWN.md](MARKDOWN.md) | Marker、清洗、全文转换 |
| [VECTORIZATION.md](VECTORIZATION.md) | 分块、Embedding 配置、配额、索引与召回 |
| [positional-evidence-resources.md](positional-evidence-resources.md) | 图表位置关联与资源快照 |
| [READING.md](READING.md) | PDF / 摘要阅读、笔记与单篇全文聊天 |
| [LITERATURE_QA.md](LITERATURE_QA.md) | 问答流程、上下文、历史证据、重试和评估问题集 |
| [REVIEW_OUTLINES.md](REVIEW_OUTLINES.md) | 大纲、两阶段撰写、续写与稿件导出 |
| [REVIEW_PROTOCOL.md](REVIEW_PROTOCOL.md) | 共享材料、正文块、引用与图表编号的当前协议 |
| [可选 LLM 供应商](../services/llm_providers/README.md) | opencode_go 接口、会话、思考参数与移除方式 |
| [UI_DESIGN.md](UI_DESIGN.md) | 视觉 token、布局、组件及交互契约 |
| [design-system/acceptance.md](design-system/acceptance.md) | 页面、状态、窗口、键盘与原生验收矩阵 |

测试截图、结果 JSON 和本机项目报告不是产品规范。编辑本目录不授权修改 `workspace/` 中的研究材料。不要按旧文档恢复已删除功能，具体名单见根 README 第 1 节。

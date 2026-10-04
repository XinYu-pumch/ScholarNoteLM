# 本地文档索引

磁盘维护说明更新于 2026-10-02；其他文档按各自日期阅读。阅读功能文档时以当前源码和已确认需求为准；历史规划、旧实验结果不代表仍有相应设置或模型。

## 当前操作与实现

| 主题 | 文档 |
| --- | --- |
| 总览、启动、架构、数据位置 | [根 README](../README.md) |
| 开发版与热更新 | [DEVELOPMENT.md](DEVELOPMENT.md) |
| 本地环境、缓存、删除边界 | [LOCAL_MAINTENANCE.md](LOCAL_MAINTENANCE.md) |
| 检索工作台与对话 | [SEARCH_WORKBENCH.md](SEARCH_WORKBENCH.md) |
| PDF 下载 | [PDF_DOWNLOADS.md](PDF_DOWNLOADS.md) |
| Marker 与内置参考文献清洗 | [MARKDOWN.md](MARKDOWN.md) |
| 正文分块、Embedding 与限速 | [VECTORIZATION.md](VECTORIZATION.md) |
| 位置关联图表 | [positional-evidence-resources.md](positional-evidence-resources.md) |
| 文献问答 | [LITERATURE_QA.md](LITERATURE_QA.md) |
| 历史上下文、证据与并行对话 | [QA_CONTEXT.md](QA_CONTEXT.md) |
| 人工问答评估问题 | [GUT_QA_EVALUATION.md](GUT_QA_EVALUATION.md) |
| 综述大纲与撰写 | [REVIEW_OUTLINES.md](REVIEW_OUTLINES.md) |
| 共享材料池与资源协议 | [review-shared-pool.md](review-shared-pool.md)、[review-resource-blocks.md](review-resource-blocks.md) |
| 数据生命周期与项目存储 | [ARTIFACT_LIFECYCLE.md](ARTIFACT_LIFECYCLE.md)、[PROJECT_STORAGE.md](PROJECT_STORAGE.md) |
| 当前界面原则 | [UI_DESIGN.md](UI_DESIGN.md) |

## 本次改动与验证

- [功能精简与 402 项回归验证](APP_SIMPLIFICATION_20260928.md)。
- [最新磁盘清理报告](../logs/storage-cleanup-20261002/REPORT.md)：包含可重建缓存、历史去重归档、数据校验与后续维护。
- [历次验证记录](VERIFICATION.md)：按日期解释，不据旧结果恢复已移除功能。

## 历史记录

[PROJECT_PLAN.md](../PROJECT_PLAN.md)、[QA_AGENT_20260922.md](QA_AGENT_20260922.md)、[WORKSPACE_POLISH_20260921.md](WORKSPACE_POLISH_20260921.md)、[markdown-body-first-cleaning.md](markdown-body-first-cleaning.md) 保存早期设计或实现。当时的重排、清洗开关、整篇补读或旧 UI 操作已被后续版本取代。

2026-10-02 前的旧备份、实验和临时分析资料已汇入 `backups/history-20261002.tar.gz`，内容已校验；旧路径需先按 [恢复说明](LOCAL_MAINTENANCE.md) 解压到独立目录。当前模型目录只保留 Marker；旧文档中的已删除模型路径不能当作重新安装清单。

旧问答测试 `scripts/test-qa-integration.py` 已归档至 `backups/legacy-qa-test-20261002.tar.gz`；当前流程使用 `scripts/test-qa-mini-review-integration.py`。历史文档中的旧命令只作记录。

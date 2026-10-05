# 文档索引

2026-10-05 整理：历史规划、按日期的变更记录、验证截图和测试结果 JSON 已从工作区删除，仍可在 git 历史中找回（基线提交 `9205e6b`）。本目录只保留现行规范；文档与源码冲突时以源码为准。

## 从这里开始

| 文档 | 内容 |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | 给开发 agent 的硬性约束、常用命令与提交前验证（`CLAUDE.md` 引用同一文件） |
| [根 README](../README.md) | 接手入口：当前状态、产品约定、运行方式、架构、数据约定、综述协议、测试 |
| [开发版](DEVELOPMENT.md) | 启动、热更新与构建 |
| [本地维护](LOCAL_MAINTENANCE.md) | 运行时、缓存与可删除范围 |

## 功能规范

| 主题 | 文档 |
| --- | --- |
| 检索工作台、检索助手、MeSH | [SEARCH_WORKBENCH.md](SEARCH_WORKBENCH.md) |
| PDF 下载 | [PDF_DOWNLOADS.md](PDF_DOWNLOADS.md) |
| Marker 转换与参考文献清洗 | [MARKDOWN.md](MARKDOWN.md) |
| 正文分块、Embedding、索引与限速 | [VECTORIZATION.md](VECTORIZATION.md) |
| 位置关联图表 | [positional-evidence-resources.md](positional-evidence-resources.md) |
| 文献问答 | [LITERATURE_QA.md](LITERATURE_QA.md) |
| 问答上下文、历史证据与并行对话 | [QA_CONTEXT.md](QA_CONTEXT.md) |
| 综述大纲与撰写 | [REVIEW_OUTLINES.md](REVIEW_OUTLINES.md) |
| 综述共享材料包与图表引用协议 | [review-shared-pool.md](review-shared-pool.md)、[review-resource-blocks.md](review-resource-blocks.md) |
| 文件生命周期与“最新”判定 | [ARTIFACT_LIFECYCLE.md](ARTIFACT_LIFECYCLE.md) |
| 系统资源与项目存储 | [PROJECT_STORAGE.md](PROJECT_STORAGE.md) |
| 界面设计规范 | [UI_DESIGN.md](UI_DESIGN.md) |

## 评估与待办

| 文档 | 内容 |
| --- | --- |
| [全流程复盘报告](pipeline-run-20261004/REPORT.md) | 一次完整实跑暴露的问题与改进建议，按优先级排列 |
| [清理规划](cleanup-plan-20261004.md) | 已执行的清理（第 7 节）与尚未决定的事项（第 3、4 节） |
| [gut 问答评估](GUT_QA_EVALUATION.md) | 人工评估文献问答的问题集与预期行为 |

## 注意

- 测试脚本会把截图和结果 JSON 写入 `docs/`。这些是运行产物，不要提交，也不要当作规范。
- 不要依据已删除的历史文档恢复旧功能，例如重排、BM25 / MedCPT、PaddleOCR、清洗策略开关、单篇精读、Chroma、演示项目。

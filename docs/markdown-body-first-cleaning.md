# Markdown 正文优先清洗（历史方案）

> 历史方案，已停止使用。2026-09-28 固定内置“仅清洗参考文献”，本页策略的实现代码和设置选项已删除。以下只保留当时的算法与验证说明；当前行为见 [Markdown](MARKDOWN.md)。

设置 → Markdown 转换 → Marker → Markdown 段落清洗，启用后选择：

- **保守清洗**（`conservative-v2`）：已有策略，行为和默认选择保持不变。
- **正文优先清洗**（`body-first-v1`）：结构参考文献处理＋现有非参考文献规则＋有边界的元数据与页眉页脚识别。

保存当前项目设置后，在“全文 Markdown”点击“重新清洗”，从 `markdown/raw` 重建清洗稿，无需重新转换 PDF。保存设置本身不执行清洗或向量化。重新清洗后，按需重新构建向量索引。关闭清洗时原文按原字符保留；切回保守清洗也从原稿重做。

PaddleOCR 的额外 App 清洗仍使用保守策略，与其官方版面过滤分开。

## 新策略的范围

| 规则 | 依据 |
|---|---|
| B01 参考文献 | Markdown 结构、编号序列、邻接关系与书目信息特征；沿用已对照的结构算法 |
| B02 本文引用格式 | 明确的 Citation / How to cite 标签＋紧邻的完整书目条目；补齐原 9 处回退 |
| B03 元数据 | 编辑/审稿人、通讯、作者贡献、资助、利益声明等标签，以及有长度和邻接边界的内容检查 |
| B04 页眉页脚 | 孤立下载水印（含日期结束检查）、稿件状态、重复期刊名和与标题相关的重复页眉 |
| B05 首页信息 | 在可识别的摘要/正文起点之前，识别标题、作者和单位；缺乏起点证据时不推测删除 |
| B06 投稿统计表 | 所有行都是字数/图表数等行政统计时才删除；混合表格和科学表格保留 |
| C02–C10 | 原有非参考文献清洗规则原样叠加 |

不调用 LLM。新增元数据检测没有添加正则表达式，但保留的现有规则（包括完整书目验证）仍使用其原有正则。这些是确定性的启发式规则，不是语义理解或全量版面重建。参考文献碎片、没有充分结构证据的元数据和复杂混合段落仍可能残留。

不全删短段、列表、表格，不从 References 一刀切至文末。正文与杂项混合且识别不确定时保留。MD 的展示、TXT 序列化和表格 RAG 分块不在此策略内。

## 接入与追踪

- 实现：`services/downloader/markdown_body_cleaning.py`；参考文献模块：`markdown_references.py`。运行时不依赖 experiments。
- 配置：项目的 `metadata/conversion-settings.json` 保存 `cleaningMode`。现有全局设置/项目选择不自动修改。
- 清洗签名包含策略及版本，切换后已有结果变为待更新；旧保守策略签名不变。
- 所有规则在同一原稿上计算字符区间并取并集，输出有序、不重叠的删除记录。报告含原文、规则、依据及行号/字符位置，可追溯；保留部分不重新排版。
- 依赖 `markdown-it-py==4.0.0`，已加入 downloader requirements；Marker 运行环境已有该依赖。
- 任何参考文献或元数据判定语义的变更必须更新正文策略版本，保证状态和向量索引失效判断准确。

## 验证（2026-09-25）

HUSandgene 57 篇＋HLH 50 篇，共 107 篇，从原始 MD 运行。实验产物位于 `experiments/body-first-v1-implementation`，实际项目原稿、清洗稿和索引未批量改写。

- 原 9 处本文引用格式回退全部修复。
- 26 篇定向参考文献标注：删除覆盖率维持 99.37%（按非空白字符）。
- 原 8 篇正文观察范围共 19,649 个非空白字符，未删除；另加入 HLH/35965424 的无 Abstract 标题正文案例，未删除。
- 原 8 篇杂项观察集：标题/作者行与编辑/审稿人标注内容全部移除；单位/通讯删除 1,556 / 2,369 字符，页眉水印等删除 522 / 631，致谢/声明等删除 1,175 / 1,600。混合表中的行政内容仍保留，以保护其中的病例摘要。
- 上述是助手定向标注，非随机抽样、非独立金标准，不能解读为全库正文保留率或泛化准确率。
- 扩展审阅发现并修复了“缺少 Abstract 标题导致首页范围延伸到流行病学正文”的问题，加入实际语料和单元回归。
- 清洗及生命周期测试 25 项、转换引擎兼容测试 9 项通过；两个设置浏览器测试通过；TypeScript/Vite 构建通过。

复现：

```sh
runtimes/downloader/bin/python scripts/test-body-first-corpus.py
runtimes/downloader/bin/python -m unittest discover -s services/downloader/tests -p 'test_markdown*cleaning*.py'
runtimes/downloader/bin/python -m unittest discover -s services/downloader/tests -p 'test_conversion_engines.py'
PLAYWRIGHT_BROWSERS_PATH="$PWD/runtimes/playwright" runtimes/node/bin/node scripts/test-markdown-cleaning-settings.mjs
```

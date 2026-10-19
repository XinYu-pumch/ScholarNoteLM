# 冗余文件与本地全文 Markdown

文献库提供“XML → 获取 PDF → 转换全文 → 检索索引”的顺序流程；任务中心保留转换详情。设置 → Markdown 转换配置计算设备与文字提取 worker。日常使用开发版启动入口。

## 自动选择计算设备

默认 `auto`：Mac 检测 MPS，Windows 检测可选 CUDA 环境，无法加速则使用 CPU。每次 App 启动后台检查一次；每个转换任务再次检查。检查在独立 Python 进程中执行小型张量运算，超时或依赖无法导入也不会让主界面崩溃。Mac 原有 MPS 模型加载、精度与 `PYTORCH_ENABLE_MPS_FALLBACK` 设置保持；没有改动 Mac 安装锁文件。

Windows CUDA 使用持久推理子进程，同一任务复用模型。采用 FP16 和保守批量，未加入 TensorRT、额外 FlashAttention、torch.compile 或多 GPU 并行。自动模式下显存不足会在新进程中把批量从 2 降至 1，仍失败则在新的 CPU 进程重试当前文件一次；其他 CUDA 执行故障/推理进程异常退出直接尝试 CPU 一次。普通 PDF/模型文件错误不触发设备回退，CPU 失败也不无限重试。手动选定 GPU 时保留错误供排查，不自动改为 CPU。

任务取消会关闭其推理进程；Windows 推理进程监视所属 worker，worker 被强制结束时也退出并释放显存。任务中心显示实际设备，转换报告记录设备检查和重试原因。正在重试的文件仍写入暂存目录，通过既有文献身份、文件版本和人工编辑检查后才发布。

实际设备和精度属于执行信息，不加入现有转换身份或清洗签名；同一 `auto` 配置从 CPU 换成 CUDA 不会让整个文献库失效。用户手动改变设备选项仍沿用原有签名处理。短 PDF 可能因模型加载和进程启动开销而没有提速；性能需要按实际文献评估。

计算设备（auto / CPU / MPS / CUDA）和文字提取并发仅影响执行，不参与已发布 Markdown 的内容身份。同版本重装或换设备后，只要 PDF、原稿、转换引擎、清洗规则及生命周期仍匹配，已有 Markdown 继续有效。旧设备签名仅在转换记录可精确核验时接受，不改写已保存签名或猜测恢复材料。

## 当前 XML 决定有效文献

`pubmed/current.xml` 是唯一的集合依据，按 PMID 匹配文件。

- 检索式归档、停用、筛选变化或执行新检索后，集合重新合并，移出集合的 PDF 自动移到 `pdf/redundant/`。
- 某篇仍被其他有效检索式命中时，文件保留在主目录。
- 重新纳入文献时优先恢复已有 PDF，再从 `archive/markdown/<PMID>/` 恢复通过完整内容与转换规则校验的 Markdown 备份；创建下载任务及工作进程开始下载前再检查一次。
- Markdown 原稿、清洗稿、图片、历史和转换记录先备份，再删除活动文件；摘要和向量数据仍清除。重新纳入后只有不兼容或缺失的 Markdown 需要重新转换，向量索引需重建。旧 XML 快照与下载历史保留。
- 缺失或损坏的当前 XML 不触发批量移动；有效的空 XML 则表示当前集合确实为空。
- PDF 同名冲突保留两个版本，多出的版本存放在目标目录的 `conflicts/`，不会静默覆盖；不合格的冗余 PDF 不直接当作下载成功。
- 文件移动记录保存在 `logs/corpus-files-*.json`。可点击“同步项目文件”手动重新核对。
- 显式清空 Markdown 同时清空活动向量；清空 PDF 还清空活动 Markdown。清空 PDF 时可选择是否包含冗余 PDF。被清空文献的旧 Markdown 备份不会自动恢复，具体规则见生命周期文档。

```text
项目/
  pubmed/current.xml
  pdf/PMID.pdf
  pdf/redundant/PMID.pdf
  abstracts/PMID.md
  markdown/PMID.md                 # 清洗后的全文
  markdown/raw/PMID.md             # Marker 原稿
  markdown/assets/PMID/           # 图片
  metadata/markdown/PMID.json      # PDF 指纹与清洗配置签名
  logs/markdown-任务ID/
    report.txt                    # 任务与逐篇结果
    report.json
    marker.log                    # 模型日志及错误
    PMID-cleaning.json             # 删除内容与匹配规则
```

## 文献库的顺序任务

- 点击“下载并转换”：检查当前 XML 与本地文件，下载缺失 PDF；下载批次结束后，由后台自动启动 Markdown 转换。切换页面不会丢失衔接。
- PDF 都已存在时，主按钮变为“转换为 Markdown”；已有 PDF 全部转换完成时显示 Markdown“最新 · 无需转换”；索引也完成后显示“最新 · 无需更新”。已有有效 Markdown 会复用。
- 部分 PDF 获取失败时，保留摘要并继续转换可用 PDF；完全没有 PDF 时，明确提示没有可转换全文。失败项不会无限自动重试。
- 下载暂停时暂不转换，可在流程卡或任务中心继续；下载取消时不启动转换。应用退出导致下载暂停或转换停止后，可手动继续。
- 下载批次保存自动转换标志和每轮衔接结果；重复读取状态不会重复创建转换任务。手动重试下载会开始新的衔接轮次。
- “文件与维护”（右上角省略号）提供仅转换已有 PDF、重新清洗、同步文件、打开文件夹、打包与调试清空。普通流程不需要使用这些工具。
- 列表分别显示 PDF、Markdown、索引的最新或待更新状态，并提供 PDF / Markdown 入口；支持“已转换”和“待准备”分类。

## 本地 Marker

沿用 BADR 的 Marker 1.6.0 与 Surya 0.13.1，单批次串行处理 PDF、复用模型。独立进程运行，界面继续响应；“完成当前篇后停止”在篇与篇之间停止。单篇解析失败会继续处理后续文献；模型本身加载失败则终止任务并报告原因。

模型在 `models/marker/`，Python 环境在 `runtimes/marker/`，适配源码在 `services/marker/`，字体在 `services/marker/vendor/static/fonts/`。转换禁止网络连接，不调用在线 LLM，也不在模型缺失时生成模拟结果。缓存与临时文件位于 app 内的 `cache/` 和 `tmp/`。

计算设备支持自动、CPU、MPS、CUDA。当前 Mac 已验证 MPS。沿用 BADR 的 `disable_ocr=True`，扫描 PDF 可能没有足够正文，此时报告失败；当前未实现 OCR 设置或扫描件自动补救。完成 Markdown 转换不等于完成向量索引或 RAG。

文字提取 worker 默认自动：少于 40 页使用 1 个，40 页及以上使用 4 个；可手动选择 1、2、4、8、16。pdftext 按页数限制实际进程数：`max(1, min(设置值, 页数 // 10))`。这仅并行化文字提取，不增加同时转换的论文数，整批仍只加载一套模型。自动阈值是性能折中，不是所有设备上的速度保证。

设置保存在应用内 `config/markdown.json`，在下一次创建转换任务时生效。逐篇转换日志记录页数、请求 worker 数与按页数上限计算的 worker 数。调整 worker 不改变清洗签名，不触发已有文献重跑。

相同 PDF 指纹和清洗规则会跳过；仅清洗规则变化时复用原稿，无需重新运行 Marker。转换期间若文献被移出集合，即使随后又恢复，也丢弃旧任务输出；若 PDF 被替换，拒绝发布旧文本。内容校验值相同的文件仅改时间或路径不会强制重转。详见 [文件生命周期与最新状态](ARTIFACT_LIFECYCLE.md)。

## 清洗

固定内置“仅清洗参考文献”（`references-v1`，实现版本 `references-only-v2`），不提供开关或策略选项。采用 Markdown 结构与局部书目信息识别，保留明确 Citation / How to cite 标签后的完整本文引用格式回退。不应用短段、标题、图注、元数据、页眉页脚或自定义删行规则。旧清洗策略实现已删除。

点击“重新清洗原稿”可从 `markdown/raw` 重建清洗稿，无需重跑 Marker；随后更新检索索引。逐篇删除记录仍保留。已有同版本的参考文献清洗签名不变。历史其他引擎产物保留原来源身份，后续转换使用 Marker；不会静默改写现有项目文件。

表格、图注和图片邻近原文保留并正常分块，完整图表另存，详见 [图表关联证据](positional-evidence-resources.md)。

## 运行时兼容与复现

历史环境从 BADR 导入，但日常运行不依赖 BADR。新用户改用 [干净安装入口](INSTALLATION.md)：从锁文件安装依赖，校验用户单独下载的 `models/`，安装器另外下载字体。保留 Marker 1.6.0、Surya 0.13.1、Transformers 4.49.0、tokenizers 0.21.0 及仓库内的严格本地加载器；不升级现有转换协议。`setup-marker-local.py` 仅为历史导入工具，不再作为新用户安装方案。

Mac Python 环境不能复制到 Windows 使用。Windows 需要独立安装对应平台的 PyTorch 等依赖；Windows 转换尚未实机验证。

## 验证

- `runtimes/downloader/bin/python -m unittest discover -s services/downloader/tests`：生命周期、内容指纹、兼容备份恢复、旧任务防写回。
- `scripts/test-markdown-corpus.py`：真实 Rust RPC、重叠检索式归档恢复、并发状态查询、独立重新清洗及调试清空；运行前确认隔离目录。
- `scripts/test-literature-workflow.py`：下载进程与实际 Marker 衔接、worker 配置和已有 Markdown 复用。会加载本地模型，不能当成轻量文档验证；按脚本说明准备隔离环境。

运行产物不是规范，不依赖已删除的测试 JSON、截图或某篇论文的历史耗时来判断当前功能。

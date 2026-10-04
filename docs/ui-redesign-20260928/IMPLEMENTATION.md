# ScholarNoteLM UI 改版实装记录

日期：2026-09-28。设计依据：[设计规范](DESIGN.md)，[实际截图画廊](implementation.html)。

## 已完成

- 全局主题：纸白与银灰工作面、石墨文字、少量墨蓝强调色；同时支持深色主题。色彩、字号、圆角、控件高度、间距与动画时长统一为语义变量。
- 导航与布局：紧凑顶部栏与 200 px 导航；中等宽度窗口使用图标导航，窄窗口使用导航抽屉。去除概览装饰横幅，突出项目指标、最近文献和工作入口。
- 文献库：四项准备状态压缩为状态带；完整下载、转换、索引和文件维护工具保留在“准备工具与维护”内。列表显示标题、简明元数据和真实处理状态，保留搜索、筛选、排序、勾选、收藏、阅读、PDF 和 Markdown 操作。
- 检索：统一策略表格、检索式等宽文字、助手对话和合并结果排版，保留全部执行、编辑、归档、历史、XML、MeSH 和 JCR 控件。
- 综述：工作区切换改为顶部选择器，仍经过原有未保存修改保护；配置区按需展开，大纲层级与编辑操作保留。正文使用目录／正文／证据分栏，窄窗口证据为可关闭抽屉；完成的批次详情可折叠，运行时展开。
- 问答：统一会话列表、问题、过程、回答和引用的视觉层级。来源抽屉和会话侧栏支持遮罩及 Escape 关闭；窄窗口压缩输入栏提示，保留发送、范围与模式选择。
- 阅读：正文与标题采用适合长文的字体和行距，长作者列表可展开，笔记保持独立面板。
- 设置与任务：降低嵌套容器数量，统一表单、按钮、保存区域、进度和语义状态；更新主题预览色。
- 动效：统一控件反馈、菜单、面板和对话框时长，支持系统减少动态效果偏好。

本次以保留现有功能为前提实施设计：大纲的移动、添加、删除等操作仍在原有编辑模式中直接使用，没有另建属性编辑流程。生成图只作为视觉方向参考，实际布局由真实字段、数据与原有操作决定。

## 功能保护与验证

- 33 个 TypeScript/TSX 文件的全部 **122 处 `rpc`／`invoke` 调用表达式与改版前一致**。见 [调用对照结果](contract-check.json)。
- 状态上下文、数据类型、存储、研究 API、下载 API、Markdown API、搜索会话管理、正文与引用渲染、证据资源模块逐字节一致。
- 未修改后端 Python 服务、Rust 业务代码、数据格式或模型请求协议。
- 现有单元测试 **61 项通过**：综述工作区 13 项、综述写作 21 项、文献问答 21 项、转换／Embedding 契约 6 项。使用隔离测试数据和模拟模型调用。
- TypeScript 检查、Vite 生产构建和 Tauri macOS 应用打包通过。Vite 保留单包超过 500 kB 的提示，本次没有为 UI 改版改变代码加载方式。
- 浏览器实际验证：项目概览、三种检索视图、文献库及维护工具、大纲编辑／取消与工作区切换、已有正文与证据、问答历史与来源、阅读与来源信息、任务中心、模型及 Embedding 设置。
- 尺寸验证：1280×720 常规窗口、1440×940 桌面默认窗口、900×650 桌面最小窗口；另检查更窄浏览器窗口的导航抽屉。检查浅色与深色主题、来源抽屉关闭和 Escape。
- 验证期间未触发真实模型生成、下载、转换或重建索引；未改写研究正文、笔记或配置凭据。因此不把生产模型调用成功列为本次验证结论。

## 使用与回退

- 已启动更新后的 macOS 应用，确认 `tauri://localhost` 正常载入真实项目与文献库：105 篇文献、89 篇 PDF、105 篇索引、3 个综述工作区。见 [桌面实图](implemented/native-library.png)。
- 项目内桌面应用：`dist/macos/ScholarNoteLM.app`，已更新为本次构建。
- 原有 `启动 ScholarNoteLM.command` 可直接打开新版。
- 构建产物：`cache/tauri-target/debug/bundle/macos/ScholarNoteLM.app`。
- 改版前源码、静态资源与桌面应用保存在 `backups/ui-redesign-20260928/`。回退 UI 时无需恢复或覆盖研究数据。

开发验证命令：

```sh
./scripts/npm-local.sh run desktop:build -- --debug --bundles app
runtimes/node/bin/node tmp/check-ui-contract.mjs
runtimes/downloader/bin/python -m unittest discover -s services/downloader/tests -p test_review.py
runtimes/downloader/bin/python -m unittest discover -s services/downloader/tests -p test_review_writing.py
runtimes/downloader/bin/python -m unittest discover -s services/downloader/tests -p test_qa.py
runtimes/downloader/bin/python -m unittest discover -s services/downloader/tests -p test_app_simplification.py
```

# 对话、设置与视觉层次更新（2026-09-21）

> 本文为对应日期的历史实现记录，不是现行操作手册。当前问答见 [文献问答](LITERATURE_QA.md)，设置与清洗见 [精简记录](APP_SIMPLIFICATION_20260928.md)，运行环境见 [本地维护](LOCAL_MAINTENANCE.md)。

## 本次行为

- 文献问答回答下方提供复制、重新生成和从此处分支。重新生成创建新分支，保留原问题之前的历史，使用原问题和原文献范围重新请求当前配置的模型；原回答及后续历史不覆盖。
- 文献问答与检索助手均提供新建、重命名、删除对话。删除隐藏当前对话，保留其他分支；问答保留被分支引用的运行/证据快照，检索助手沿用归档存储。
- 新消息、模型选择、综述模型状态和问答导出使用“配置名称/模型名称”。请求给供应商的 model 字段仍是实际模型 ID。没有配置来源的旧消息保留原始模型名。
- 数字输入有独立编辑草稿。允许暂时清空，失焦后恢复上次有效值；不会在删除时立即填 0。空温度仍表示服务默认值。
- macOS Cmd+, 打开设置；原有快捷键保留。
- 设置页模型新建与删除按钮同排同样式。PDF 下载删除长流程描述；开放获取说明个人邮箱无需注册 Unpaywall；增强补救只提示延长下载时间。Zotero、并发与请求参数、Sci-Hub 镜像、Bloom 索引归入默认收起的高级区，各自展开。
- Markdown 设置仅展示“保守清洗方案”；默认启用清洗。删除旧模式选择和额外删行控件，保存清空额外删行规则，不重清洗已有文件。显式保存过关闭清洗的用户选择仍保留。
- 配色以低饱和灰绿背景、浅色内容面、细边框/阴影和局部深色重点区分层次，覆盖侧栏、设置、聊天与综述。检查了深色模式及窄窗口。

## Embedding 配置与迁移

`config/embedding.json` 支持 `profiles` 和 `activeProfile`。每条配置独立保存名称、服务地址、模型、凭据与请求参数。旧平面配置读取时映射为 legacy/默认配置，首次保存迁移；只读不会重写。新建不会继承其他配置密钥，也不会切换当前活动配置（第一条配置除外）。

普通 `vector.settings` 响应只返回 hasKey，不返回密钥。输入框保存后用掩码占位，只有点击眼睛时通过 `vector.profile.key` 取回所选配置明文。隐藏未编辑密钥时清除前端临时明文。密钥仍存于本机配置，不宣称应用层加密；新写入文件在非 Windows 上设为 0600。

`vector.models` 从所选地址获取列表，支持已保存密钥和未保存表单；`vector.test` 仅发送测试文本，不创建索引。验证记录按服务端点、模型、版本和密钥的指纹分别保存；修改凭据需重新验证，切换回已验证配置不要求重复测试。

“召回与重排”选择已保存且验证的配置，同时用于文献向量化及查询召回，避免混用向量空间。配置名称/ID 不加入向量缓存身份，重命名不会触发重算；不同模型使用对应缓存，切换本身不删除已有缓存。活动配置有替代配置时，需先切换再删除。

## 验证

使用 tmp 隔离工作目录与本机模拟模型服务；未改用户项目、真实密钥、既有研究问题或下载数据。

- 前端生产构建、Rust CLI 构建与 10 项 Rust 测试通过。前端仍有原有 bundle 体积提示。
- 20 项问答、5 项 Embedding 多配置、13 项向量、6 项既有 Embedding/限速、6 项召回设置、48 项综述/传输单元测试通过。
- `scripts/test-qa-integration.py`：真实 Rust RPC + 独立问答 worker 的多轮检索、异常工具容错、证据与取消流程通过。
- `scripts/test-review-writing-integration.py`：真实 worker 的已验证 API 召回、提示词准备、并发生成、失败项重试、取消及 Markdown/HTML/Word 导出通过。
- `scripts/test-assistant-flow.py`：真实 SSE 推理/正文、配置/模型标签、分支、取消与截断保存通过。
- `scripts/test-qa-ui.mjs`：两类对话管理、问答复制/分支/重新生成、原文引用、Embedding 新建/获取列表/验证/保存/显隐密钥、召回配置切换、数字清空/替换/保存、快捷键、设置收起项、深浅色和窄窗口通过；无 React 页面错误。既有批量 XML 串行与 2 秒间隔仍通过。

主要截图：

- `screenshots/settings-embedding-profiles.png`
- `screenshots/settings-embedding-narrow.png`
- `screenshots/settings-downloads-layered.png`
- `screenshots/settings-retrieval-profiles.png`
- `screenshots/qa-reading.png`
- `screenshots/search-chat-colors.png`
- `screenshots/review-writing-layered.png`

修改前文件位于 `backups/workspace-polish-20260921/`。继续使用开发版，未重新打包桌面安装包。

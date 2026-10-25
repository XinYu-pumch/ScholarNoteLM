# 可选 LLM 供应商

默认 OpenAI 兼容调用不依赖任何可选模块。普通配置可按模型显式选择下述思考预设。`registry.json` 只登记启用的供应商目录名；每个目录包含 `manifest.json` 和 `adapter.py`。目前登记 `deepseek` 和 `opencode_go`，两者互不依赖。

## 边界

- `manifest.json`：供应商标识、配置分组名称、固定 Base URL、官方模型到协议的映射、协议必需参数和核对来源。设置页从后端读取它，以中间供应商列表和右侧详情展示，不在 React 中硬编码供应商名。
- `adapter.py`：专属请求头、消息/图片转换、流式响应转换；不改变全局 HTTP 客户端、环境变量、代理或 TLS。
- `services/downloader/llm_provider.py`：通用注册入口、稳定会话上下文、兼容的配置签名。未设置 `provider` 或 `provider=openai` 的旧配置不读取可选模块。
- `review_llm.py`：共用网络与取消机制。默认请求体和请求头保持原逻辑；只有明确选用可选供应商才执行适配。
- Rust 的 `llm_providers.rs`：读取注册信息，并通过私有 stdin/stdout 管道调用 `llm_provider_worker.py`。供应商协议只实现一份；不另开 HTTP 代理服务。密钥不进入命令行或进程日志，取消时终止子进程。

普通模型不按配置名称、模型名称或域名猜测供应商。一个叫 `opencode_go` 的旧普通配置仍是普通配置；请在独立分组中填写专用配置。Go 只允许保存一份配置，名称固定为 `opencode_go`，后端在写事务中拒绝第二份。普通配置可与独立供应商同名，原有 ID、密钥和工作流绑定不变。旧版本如已保存多份 Go 配置，界面仅保留选择和删除入口用于清理，不再允许新增；不会自动删除旧配置。

## DeepSeek 官方

`deepseek/` 模块独立提供 `https://api.deepseek.com/v1`，目前登记 `deepseek-flash` 与 `deepseek-v4-pro`，各支持 low / high / max。默认开启思考；选择“服务端默认”时不发送 `reasoning_effort`，官方当前默认 high。显式选择时发送 `thinking.type=enabled` 和 `reasoning_effort`；思考模式忽略温度，模块不发送该参数。具体规则见 [官方思考模式文档](https://api-docs.deepseek.com/guides/thinking_mode)。

不发送 Go 的会话请求头，也不依赖 Go 适配器；移除任一模块不会改变另一模块及普通 OpenAI 调用。DeepSeek 入口保留一份配置，名称固定；普通 OpenAI 格式的已有 DeepSeek 配置不自动迁移。

## OpenCode Go

地址与各模型协议以 [Go 官方 Endpoints](https://opencode.ai/v2/docs/console/go/#endpoints) 为准，映射核对日期在 manifest 中。模型列表为在线目录与已知官方映射的交集；遇到未登记的新模型明确拒绝，不猜协议、不尝试切到其他计费端点。

新增 `gemini-4-argon` 使用官方 Google `/inference/go/google/v1beta/models/` 端点，原 Contributor 配置及其他既有模型端点保持原值，避免无关研究产物失效。在线目录未返回的已保存模型仍保留，并在获取列表时提示；可用性以服务端实际返回为准。

当前支持 Chat Completions、Responses、Anthropic Messages、Google `streamGenerateContent`。只发送本应用的 User-Agent 和稳定的 `x-opencode-session`，不伪装其他客户端。所有外部连接仍使用系统代理解析。

Messages 协议强制要求 `max_tokens`，因此专用模块使用 models.dev 的 `opencode-go` 条目所公布的模型输出上限（来源与值在 manifest）；这仅是该原生协议的必填参数。其他协议和普通 OpenAI 配置不增加输出 token 限额。收到截断、过滤、工具调用或不完整结束时，不将其作为完整正文发布。当前研究工作流不提供模型函数调用工具。

会话身份不包含密钥，且不代替历史消息：

| 工作流 | 会话范围 |
| --- | --- |
| 检索助手 | 项目 + 对话；分支/独立对话使用不同身份 |
| 阅读聊天 | 项目 + 阅读对话，重试复用 |
| 文献问答 | 项目 + 问答对话；规划、评估、回答、格式修复和后续提问共用 |
| 大纲 | 项目 + 工作区 + 来源快照 + 主题/要求的摘要；同输入重试复用 |
| 综述写作 | 项目 + 工作区 + 写作轮次 + 写作单元；并发章节分开，格式修复/重试复用 |
| 连接测试 | 每次测试独立身份，内部连接重试复用 |

会话上下文不进入模型缓存签名。只有可选供应商配置额外计入 `provider` 身份；普通配置原有签名键和值保持兼容。

## 逐模型思考强度

Go 配置的 `reasoningByModel` 按模型 ID 保存选择。每行独立选择“服务端默认”或该模型的已登记档位；默认不发送思考强度参数，不将原厂默认值冒充 Go 的实际默认值。测试连接和各研究工作流使用同一选择。普通配置忽略此字段；自定义思考预设使用独立的 `thinkingByModel`。

Go 的 Gemini 请求始终发送 `generationConfig.thinkingConfig.includeThoughts: true`，包括强度为“服务端默认”时，以接收流式思考摘要。摘要通过已有推理字段传递，不混入大纲 CSV 或回答正文；所选强度和温度保持不变。此行为仅在 Go 的 `adapter.py` 中实现，不修改共用客户端、超时或缓存签名。摘要不保证固定发送间隔，服务端连续无数据仍可能触发已有超时。协议说明见 [Gemini 思考摘要](https://ai.google.dev/gemini-api/docs/generate-content/thinking#thought-summaries)。

所有 Go 模型在各自 `reasoning.output` 中登记输出策略：GPT 与 Muse 的 Responses 请求发送 `reasoning.summary=auto`；Claude Haiku 5.5 发送 `thinking.display=summarized`（未指定模式时显式保持原厂默认 adaptive，disabled 时不发送 display）；Grok 按官方协议自动接收摘要；Chat 与其他 Messages 模型接收服务端提供的推理字段，不添加未经支持的输出开关。显式 none / disabled 保持原意；开启输出不等于强制模型每次都产生可读思考。设置弹窗说明该模型的策略，连接测试正确区分摘要与服务端推理文本。输出策略只在 Go 模块中实现，不改变普通配置、强度选择或缓存签名。

Responses 同时解析摘要增量、done 事件和完整 JSON / completed 响应中的 summary 数组；按输出项和摘要分段去重，补齐仅在结束时返回的摘要，不显示 encrypted_content 或签名。共享客户端结束时刷新最终字符统计，避免短响应的思考计数遗漏。

官方输出参数来源：[OpenAI summaries](https://developers.openai.com/api/docs/guides/reasoning#reasoning-summaries)、[Meta summaries](https://dev.meta.ai/docs/reasoning#reasoning-summaries)、[Claude display](https://platform.claude.com/docs/en/build-with-claude/thinking#controlling-thinking-display)、[Grok summaries](https://docs.x.ai/developers/model-capabilities/text/reasoning)。

档位以 Go 官网链接的 models.dev 中 `opencode-go` 的 `reasoning_options` 为依据，参数拼写结合 OpenCode 的原生协议实现核对；来源链接固定在 manifest 的 `reasoningSources`。Go 的 `/models` 只返回模型身份，不能据此推断档位。按 2026-10-25 的公开目录登记强度、开关和预算选项（保留历史模型 ID，实际可用性仍由 Go 决定）：

| 模型 | 档位 |
| --- | --- |
| DeepSeek V4.1 Flash、GLM 5.3 / 5.3 Flash | low / high / max |
| DeepSeek V4 Pro、GLM 5.2 | high / max |
| Gemini 4 Argon / Contributor、Step 5 Preview / Free | low / medium / high |
| Kimi K3 | max |
| Kimi K3.1 Pro | low / high / max |
| Hy4 Preview | none / high |
| Hy3 | none / low / high |
| Space Bunny、Cat Jam Free、Beam Free、MiniMax M3.1 Flash / Free | low / medium / high / xhigh / max |
| Grok 4.6 / 4.7 | low / medium / high / xhigh |
| GPT 5.6 Luna / 6 Luna | none / low / medium / high / xhigh / max |
| Muse Spark 1.2 / 1.3 Contributor | minimal / low / medium / high / xhigh |
| Claude Haiku 5.5 | low / medium / high / xhigh / max，或 enabled / disabled |
| Qwen 3.8 Max / Flash | low / medium / xhigh，或 enabled / disabled / budget |
| Qwen 3.7 Plus | enabled / disabled / budget |
| MiniMax M3、LongCat 2.0 / 2.5 Preview Free | enabled / disabled |

MiMo V2.5/V2.6 系列、Kimi K2.7 Code、MiniMax M2.7、Iceman Contributor Free 在 Go 目录中没有可调参数，界面明确说明保持服务端行为；这不代表它们不思考。不能将 MiMo 原厂开关直接当作 Go 已支持的参数。

开关与强度共用单选控件，避免同时发送冲突指令。LongCat 使用 `thinking.type=enabled/disabled`；MiniMax M3 / Claude 使用 `adaptive/disabled`。Qwen 的 `budget` 模式单独填写正整数 `reasoningBudgetByModel[model]`，请求写入 `thinking.budget_tokens`，不再发送 `output_config.effort`。Max / 3.7 Plus 公开预算上限为 262144；Flash 未公布上限时不自行增设上限。预算和最终正文输出上限独立；不套用 Claude 的 budget < max_tokens 规则。Qwen 官方建议新接口优先使用 effort，预算保留给 Go 仍公开支持的模型。

请求体补丁只来自模块内审核过的 manifest：Chat 使用 `reasoning_effort`，Responses 使用 `reasoning.effort`，Gemini 使用 `generationConfig.thinkingConfig.thinkingLevel`，Messages 使用 `output_config.effort` 及模型相应的 `thinking` 模式。GLM Flash 的 Go 上游拒绝 `thinking` 字段，只发送 `reasoning_effort`。非法档位在保存和发送前明确报错，不静默降档。

选择非默认档位时，只把**当前调用模型**的档位计入综述和问答缓存签名；预算模式仅增加当前模型的实际预算，未启用的预算不入签名；改其他模型不会使其失效。默认状态保持旧 Go 签名，普通模型签名完全不变。

## 更新、停用与删除

更新 Go 的模型或端点只改 `opencode_go/manifest.json`；协议/请求头策略改 `opencode_go/adapter.py`。变更协议前，按官方文档检查原生字段和输出上限并运行测试。

停用：从 `registry.json` 的 `providers` 数组移除 `opencode_go`。删除：再删除整个 `opencode_go/` 目录。不必修改 React、Rust、研究工作流、普通请求客户端或其他配置。

旧 Go 配置与生成内容保留。配置分组显示“已停用”，可以删除旧配置；调用旧配置会明确报错，不静默转到普通接口。若全局默认仍是 Go，用户需要选择其他默认模型。恢复模块并重新注册后可继续使用旧配置。已发出的请求不做热卸载；更换文件前先停止相关任务。

## 验证

```sh
runtimes/downloader/bin/python -m unittest discover -s services/downloader/tests -p test_llm_provider.py
./scripts/npm-local.sh run research:build
runtimes/downloader/bin/python scripts/test-llm-provider-integration.py
PLAYWRIGHT_BROWSERS_PATH="$PWD/runtimes/playwright" runtimes/node/bin/node scripts/test-provider-settings-ui.mjs
TEST_LLM_PROVIDER=opencode_go runtimes/downloader/bin/python scripts/test-review-integration.py
TEST_LLM_PROVIDER=opencode_go runtimes/downloader/bin/python scripts/test-review-writing-integration.py
TEST_LLM_PROVIDER=opencode_go runtimes/downloader/bin/python scripts/test-qa-mini-review-integration.py
TEST_LLM_PROVIDER=opencode_go runtimes/downloader/bin/python scripts/test-reader-integration.py
```

集成测试在 `tmp/` 复制代码，只将副本 manifest 的 Base URL 改成本机模拟服务；覆盖四种协议、普通模型隔离、私有进程取消和模块物理删除。UI 测试启动独立端口和隔离根目录，验证供应商列表、Embedding 内置预设、组合保存操作、固定地址、保存、未保存保护、窄窗口与停用后的管理入口。真实服务探测不能替代这些回归测试。

四个研究工作流脚本默认仍验证普通模型；设置 `TEST_LLM_PROVIDER=opencode_go` 后改用隔离副本中的 Go 适配器和模拟模型 ID，覆盖大纲、写作、问答、阅读的真实 worker，检查专属请求头、会话范围、重试与取消，并确认 Embedding 请求不携带 Go 请求头。

## 自定义模型思考预设

每个普通供应商的模型可单独选择 `Gemini 4 · OpenAI Compatible`、`Gemini 4 · Native` 、`DeepSeek · OpenAI Compatible` 或下表中的新增预设，也可保留“服务端默认”（不发送额外参数）。选中预设时初始化档位：Gemini 为 medium，DeepSeek 为 high；随后可独立修改并保存。Gemini 支持 low / medium / high，DeepSeek 可选 low / high / max，具体模型以官方支持范围为准。预设不凭模型名字自动启用，旧配置不迁移。

配置存储为 `thinkingByModel[model] = {preset, level, output?, budget?}`。目录和官方来源在 `services/downloader/thinking_presets.json`，请求与响应处理在 `llm_thinking.py` 和 `llm_native.py`，不依赖 Go 或 DeepSeek 专用模块。Rust 的检索助手与 Python 的大纲、正文、问答、阅读和连接测试共用此实现。未选择预设的普通请求保持原路径。只有当前调用模型的有效预设、档位及显式非默认输出方式进入签名，其他模型改动不影响已有材料。

- Gemini OpenAI Compatible：旧配置或输出选择“预设默认”时仍发送 `reasoning_effort`。显式选择请求／不请求摘要时，发送 `extra_body.google.thinking_config`，其中含 `thinking_level` 和 `include_thoughts`；不同时发送 `reasoning_effort`，避免重叠。这里的 extra_body 是 Google REST 请求本身的字段，不是 Python SDK 的展开语法。第三方中转站须支持这一扩展。
- Gemini Native：将配置地址的尾部 `/v1` 转为 `/v1beta`（保留主机及中转前缀），也接受 `/v1beta` 或 `/v1beta/openai`；调用 `/models/{model}:streamGenerateContent?alt=sse`。转换文本、内嵌图片和系统消息；发送 `generationConfig.thinkingConfig.thinkingLevel` 及 `includeThoughts`（默认 true，可显式关闭）。返回摘要单独解析，不混入正文。不携带 Go 请求头。模型目录仍走配置地址的 `/models`，建议 4router 保留其 `/v1` Base URL。
- DeepSeek OpenAI Compatible：发送 `thinking.type=enabled` 与 `reasoning_effort`；思考模式不发送无效的 temperature。面向当前 DeepSeek V4 系列，其他模型是否接受由服务端决定。

4router 的 Gemini 原生预设与 openmirothinker 的可选模块使用相同的摘要参数。当前隔离实测中 medium 未返回摘要，high 返回了 `thought=true` 文本；需要摘要时可选择 high + 请求思考摘要，但这不保证服务端每次都返回。`thoughtSignature` 不是可显示的思考文本；应用不会通过提示词让模型把思考写入正文，也不会静默升档。

Chat、Responses、Gemini 不增加输出 token 限制。Claude Messages 的必填 `max_tokens` 使用该预设模型公开的 128000 上限；不改变全局网络或用户研究数据。非法预设/档位拒绝保存或调用；原生响应过滤、截断、工具调用明确失败，不静默切换协议。新版构建会包含预设目录。官方资料：Google [OpenAI兼容](https://ai.google.dev/gemini-api/docs/openai#thinking)、[原生思考](https://ai.google.dev/gemini-api/docs/generate-content/thinking)，[DeepSeek思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)。

### OpenAI Chat Completions 预设目录与去重

所有下列预设保留用户填写的地址，不凭模型名称切换供应商，也不添加 Go 请求头。Gemini Native、Claude Messages、Grok Responses 会按用户明确选择切换协议，保留主机和中转路径前缀。已有预设 ID、默认档位和请求行为保持兼容；新增专用预设按下表初始化。

| 预设 | 请求字段 | 适用范围 |
| --- | --- | --- |
| Generic · Reasoning Effort | `reasoning_effort` | 相同字段合并一份，支持值取并集，实际可选子集见下文 |
| Generic · Thinking Toggle | `thinking.type=enabled/disabled` | 可切换模式的 MiMo V2.6、Kimi K2.6、GLM 4.x；不是强度档位 |
| Qwen 3.8 · OpenAI Compatible | `enable_thinking` + `reasoning_effort` | low / medium / xhigh；或 enabled / disabled；或独立 budget（0–262144），不与 effort 同发 |
| GLM 5.2 / 5.3 · OpenAI Compatible | `thinking.type=enabled` + `reasoning_effort` | 5.3 / Flash 为 low / high / max；5.2 为 high / max，原厂默认 max |

通用 effort 不是“所有模型支持所有档位”：Kimi K3 / K3.1 为 low/high/max；Grok 4.6/4.7 为 low/medium/high/xhigh；Meta **Muse** 为 minimal/low/medium/high/xhigh，max 仅用于文档指定的 Muse Wonder 1.0 / Spark 1.3，Contributor 不适用；旧 Llama 不因来自 Meta 就支持思考参数。OpenAI 按模型版本区分，GPT-6 Astra 不支持 none，GPT-6.1 Sol 不支持 none/minimal。通用选项提供并集，用户须根据中转站实际模型选择；服务端拒绝的档位不会被应用静默更改。

通用 effort 省略 temperature，以兼容 OpenAI 推理模型；通用开关同样省略，由原厂决定各模式采样值。Qwen/GLM 保留原温度。GLM 与 DeepSeek 的思考字段形式虽然一致，温度规则和初始档位不同，所以不强行合并。Gemini 原有预设保留，以保持已保存配置和签名不变。

官方来源（2026-10-25 核对；后续以厂商最新文档为准）：

- [OpenAI reasoning](https://developers.openai.com/api/docs/guides/reasoning)、[temperature 限制](https://developers.openai.com/api/docs/guides/deployment-checklist)
- [Grok reasoning](https://docs.x.ai/developers/model-capabilities/text/reasoning)
- [Meta Muse reasoning](https://dev.meta.ai/docs/reasoning)
- [Kimi Chat](https://platform.moonshot.ai/docs/api/chat)
- [MiMo Chat](https://mimo.mi.com/docs/en-US/api/chat/openai-api)
- [Qwen Chat](https://help.aliyun.com/en/model-studio/qwen-api-via-openai-chat-completions)、[Messages](https://help.aliyun.com/en/model-studio/anthropic-api-messages)
- [GLM Chat](https://docs.z.ai/api-reference/llm/chat-completion)
- [Go 模型范围](https://opencode.ai/v2/docs/console/go/)、[models.dev 参数目录](https://models.dev/api.json)、[LongCat Chat 开关](https://longcat.chat/platform/docs/api/chat.html)

测试以隔离模拟服务核对保存、实际请求字段、流式响应和模块隔离。HTTP 成功不能单独证明中转站执行了思考参数，未实测的模型不宣称已完成线上验证。

### 官方厂商专用预设

这些专用预设限制可选档位并注明输出语义。它们和通用预设复用相同的 Chat 参数，但不会自动迁移既有配置；Claude 与 Grok Responses 有单独协议适配。Go 文件可独立删除。

| 预设 | 初始档位 / 可选项 | 实际参数与输出 |
| --- | --- | --- |
| Claude Opus 5.5 · Messages | medium；low / medium / high / xhigh / max | `/messages`；`thinking.type=adaptive`、`output_config.effort`、`thinking.display=summarized`；返回摘要，思考始终开启 |
| Grok 4.6 / 4.7 · Chat Completions | high；low / medium / high / xhigh | `reasoning_effort`；接收网关实际返回的思考字段，不能保证有摘要 |
| Grok 4.6 / 4.7 · Responses | high；同上 | `/responses`、`reasoning.effort`；接收 reasoning_text 和 reasoning_summary_text 事件，官方 4.7 文档无需 summary 开关 |
| Kimi K3 · OpenAI Compatible | max；low / high / max | `reasoning_effort`；当前 K3 系列官方 API 已提供三档，旧部署可能仅 max；不发送 K2 的 thinking 开关 |
| MiMo V2.6 · OpenAI Compatible | enabled；enabled / disabled | `thinking.type`；官方 Chat 只有模式开关，没有强度档位；返回 reasoning_content |
| MiniMax M3.1 Flash · OpenAI Compatible | max；low / medium / high / xhigh / max | `reasoning_effort`、`reasoning_split=true`；不能关闭思考，分离 reasoning_content 与正文 |

Qwen 的 `budget` 模式单独发送 `enable_thinking=true` 与 `thinking_budget`，可选 0–262144；0 不等同于关闭思考。low/medium/xhigh 与预算互斥，服务端未设置时默认预算 131072、档位 xhigh。预算只在启用 budget 时进入当前模型签名，切回档位后不发送也不计入签名。

Claude 的摘要与正文、Grok Responses 的思考与正文均独立解析；过滤、工具调用、输出截断或缺少完成状态会失败。最终完整响应与流式 delta 去重；加密 reasoning/signature 不作为文字显示。没有从其他提供商复制会话请求头。

专用预设依据：[Claude effort](https://platform.claude.com/docs/en/build-with-claude/effort)、[Claude thinking](https://platform.claude.com/docs/en/build-with-claude/thinking)、[Claude 上限](https://platform.claude.com/docs/en/models/overview)、[MiniMax OpenAI](https://platform.minimax.io/docs/api-reference/text-openai-api)、[Kimi effort](https://platform.kimi.ai/docs/guide/use-thinking-effort)，其余见前述各厂商链接。预设描述官方请求格式，不保证中转站支持或透传；须用连接测试检查。

### 思考输出与连接诊断

每个模型的“思考”按钮打开弹窗，集中编辑预设、强度／开关／预算、输出方式。主列表保留图片支持、默认模型与测试按钮，长说明移进弹窗。应用只更新设置草稿，仍需“保存配置”；取消和离开沿用未保存保护。

- 新选择 Gemini 预设时，输出初始化为“请求思考摘要”。已有配置没有 `output` 字段时不迁移：Chat 保留原 `reasoning_effort` 请求，Native 保留原请求摘要行为。`output=default` 与缺少字段具有相同签名。
- `output=summary/off` 在 Gemini 与 Claude Messages 预设中有效。Claude 使用 `thinking.display=summarized/omitted`，初次选择默认请求摘要；Gemini：Chat 使用 Google 扩展字段，Native 使用 `generationConfig.thinkingConfig.includeThoughts`。不请求摘要不等于停止思考；若服务端仍返回思考内容，App 仍单独接收，不拼入正文。
- DeepSeek、Qwen、GLM、MiMo、Kimi 的推理文本通常自动放在 `reasoning_content`；这些预设不伪造摘要开关。通用 effort 中，OpenAI 和外部 Meta Chat Completions 的内部推理不公开；Grok 按模型及协议区分。Responses 的 summary 不能照搬到 Chat。
- 不将 `reasoning_content` 的存在等同于完整内部思维链；原生 Gemini 的摘要和服务端推理文本采用不同提示文字。

连接测试走与实际研究相同的 adapter 和 stream client，采用合成问题，不读取项目材料。正常请求仅一次（沿用原有连接失败重试）；报告发送的思考字段、实际思考字符数，以及服务端确实报告的 reasoning token。缺少用量显示“未报告”，不记为零；不为了采集用量额外向所有中转站发送 `stream_options`。用量观察发生在协议转换前，能读取末尾 `choices:[]` 的 usage 和原生 Gemini usageMetadata。测试结果中的请求参数不包含密钥、消息、完整请求头或原始上游错误正文。

“深入验证参数”仅面向显式配置了思考参数的普通模型：先发送正常请求，成功后复制请求，只将一个实际存在的强度／模式字段替换为非法值，再发送一次对照请求。检查的具体字段会展示；这不声称验证了其余所有字段。默认没有显式参数时不发送第二次请求，图片测试也不作负例探测。

- 错误值返回完整正文：显示“可能忽略、移除或替换参数”，不能认定参数生效。
- HTTP 400/422 且安全解析出的错误明确指出被测参数：显示“该参数被校验”，仍不保证合法档位的实际推理强度。
- 认证、限流、超时、其他错误，或未指出被测字段的 400：显示“无法判断”。正常请求失败时不继续探测。

错误值从不存入配置或研究签名；不静默降档或切换协议。测试状态绑定当前草稿，修改连接、模型或思考设置后清除结果；迟到的旧响应不会覆盖新状态。详细诊断通过结果弹窗查看，列表反馈区域保留高度。

官方输出依据：[Google Chat 扩展](https://ai.google.dev/gemini-api/docs/openai#thinking)、[Google 原生摘要](https://ai.google.dev/gemini-api/docs/generate-content/thinking#thought-summaries)、[OpenAI reasoning / summaries](https://developers.openai.com/api/docs/guides/reasoning)、[Meta reasoning](https://dev.meta.ai/docs/reasoning)，其余厂商来源见上表。Go Gemini 的原生摘要策略保留在 Go adapter，本次没有把其请求头、端点或其他专属逻辑带入普通预设。

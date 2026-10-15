# 可选 LLM 供应商

默认 OpenAI 兼容调用不依赖任何可选模块。`registry.json` 只登记启用的供应商目录名；每个目录包含 `manifest.json` 和 `adapter.py`。目前登记 `opencode_go`。

## 边界

- `manifest.json`：供应商标识、配置分组名称、固定 Base URL、官方模型到协议的映射、协议必需参数和核对来源。设置页从后端读取它，默认折叠，不在 React 中硬编码供应商名。
- `adapter.py`：专属请求头、消息/图片转换、流式响应转换；不改变全局 HTTP 客户端、环境变量、代理或 TLS。
- `services/downloader/llm_provider.py`：通用注册入口、稳定会话上下文、兼容的配置签名。未设置 `provider` 或 `provider=openai` 的旧配置不读取可选模块。
- `review_llm.py`：共用网络与取消机制。默认请求体和请求头保持原逻辑；只有明确选用可选供应商才执行适配。
- Rust 的 `llm_providers.rs`：读取注册信息，并通过私有 stdin/stdout 管道调用 `llm_provider_worker.py`。供应商协议只实现一份；不另开 HTTP 代理服务。密钥不进入命令行或进程日志，取消时终止子进程。

普通模型不按配置名称、模型名称或域名猜测供应商。一个叫 `opencode_go` 的旧普通配置仍是普通配置；请在独立分组中填写专用配置。Go 只允许保存一份配置，名称固定为 `opencode_go`，后端在写事务中拒绝第二份。普通配置可与独立供应商同名，原有 ID、密钥和工作流绑定不变。旧版本如已保存多份 Go 配置，界面仅保留选择和删除入口用于清理，不再允许新增；不会自动删除旧配置。

## OpenCode Go

地址与各模型协议以 [Go 官方 Endpoints](https://opencode.ai/v2/docs/console/go/#endpoints) 为准，映射核对日期在 manifest 中。模型列表为在线目录与已知官方映射的交集；遇到未登记的新模型明确拒绝，不猜协议、不尝试切到其他计费端点。

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

Go 配置的 `reasoningByModel` 按模型 ID 保存选择。每行独立选择“服务端默认”或该模型的已登记档位；默认不发送思考强度参数，不将原厂默认值冒充 Go 的实际默认值。测试连接和各研究工作流使用同一选择。普通配置忽略此字段。

Go 的 Gemini 请求始终发送 `generationConfig.thinkingConfig.includeThoughts: true`，包括强度为“服务端默认”时，以接收流式思考摘要。摘要通过已有推理字段传递，不混入大纲 CSV 或回答正文；所选强度和温度保持不变。此行为仅在 Go 的 `adapter.py` 中实现，不修改共用客户端、超时或缓存签名。摘要不保证固定发送间隔，服务端连续无数据仍可能触发已有超时。协议说明见 [Gemini 思考摘要](https://ai.google.dev/gemini-api/docs/generate-content/thinking#thought-summaries)。

档位以 Go 官网链接的 models.dev 中 `opencode-go` 的 `reasoning_options` 为依据，参数拼写结合 OpenCode 的原生协议实现核对；来源链接固定在 manifest 的 `reasoningSources`。Go 的 `/models` 只返回模型身份，不能据此推断档位。当前登记 21 个模型的离散强度选项：

| 模型 | 档位 |
| --- | --- |
| DeepSeek V4.1 Flash、GLM 5.3 / 5.3 Flash | low / high / max |
| DeepSeek V4 Pro、GLM 5.2 | high / max |
| Gemini 4 Argon Contributor、Step 5 Preview Free | low / medium / high |
| Kimi K3 | max |
| Hy4 Preview | none / high |
| Hy3 | none / low / high |
| Space Bunny、Cat Jam Free | low / medium / high / xhigh / max |
| Grok 4.6 / 4.7 | low / medium / high / xhigh |
| GPT 5.6 Luna / 6 Luna | none / low / medium / high / xhigh / max |
| Muse Spark 1.2 / 1.3 Contributor | minimal / low / medium / high / xhigh |
| Claude Haiku 5.5 | low / medium / high / xhigh / max |
| Qwen 3.8 Max / Flash | low / medium / xhigh |

其余 11 个模型当前没有登记离散强度档位，保持服务端默认；其中部分原生 API 只提供思考开关或 token 预算，不能套用其他模型的 low / medium / high。本次不将预算开关伪装成强度档位。

请求体补丁只来自模块内审核过的 manifest：Chat 使用 `reasoning_effort`，Responses 使用 `reasoning.effort`，Gemini 使用 `generationConfig.thinkingConfig.thinkingLevel`，Messages 使用 `output_config.effort` 及模型相应的 `thinking` 模式。GLM Flash 的 Go 上游拒绝 `thinking` 字段，只发送 `reasoning_effort`。非法档位在保存和发送前明确报错，不静默降档。

选择非默认档位时，只把**当前调用模型**的档位计入综述和问答缓存签名；改其他模型不会使其失效。默认状态保持旧 Go 签名，普通模型签名完全不变。

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

集成测试在 `tmp/` 复制代码，只将副本 manifest 的 Base URL 改成本机模拟服务；覆盖四种协议、普通模型隔离、私有进程取消和模块物理删除。UI 测试启动独立端口和隔离根目录，验证默认折叠、固定地址、保存、未保存保护、窄窗口与停用后的管理入口。真实服务探测不能替代这些回归测试。

四个研究工作流脚本默认仍验证普通模型；设置 `TEST_LLM_PROVIDER=opencode_go` 后改用隔离副本中的 Go 适配器和模拟模型 ID，覆盖大纲、写作、问答、阅读的真实 worker，检查专属请求头、会话范围、重试与取消，并确认 Embedding 请求不携带 Go 请求头。

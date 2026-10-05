# ScholarNoteLM 开发须知

本地优先的生物医学文献研究桌面应用：PubMed 检索 → PDF / 摘要 → Marker 转 Markdown → 分块与 Embedding → 综述撰写与文献问答。前端 React + TypeScript，桌面壳 Tauri 2，Rust 负责检索与配置，Python（`services/downloader/`）负责下载、转换、向量、综述和问答。

**开始任何工作前先读 [README.md](README.md)**，尤其是第 1 节的产品约定和已知问题；专题文档见 [docs/README.md](docs/README.md)。文档与源码冲突时以源码为准。

## 硬性约束

1. **不泄露密钥**：`config/embedding.json` 和 `data/research/research.sqlite3` 中有明文 API Key。不要打印、记录或提交它们；提交前用 `git status` 确认没有加入 `config/`、`data/`、`workspace/`。
2. **不动用户数据**：`workspace/` 是用户的真实研究项目（PDF、综述、问答记录）。未经明确要求，不要修改或删除其中的文件，也不要对它调用真实模型或批量下载。测试使用 `tmp/` 下的隔离根目录（环境变量 `SCHOLARNOTELM_ROOT`）。
3. **UI 测试脚本先看再跑**：`scripts/*.mjs` 中有的会自建 `tmp/` 隔离根目录，有的直接连接 1420 端口的开发服务器，会读写该服务器当前根目录的数据。连接开发服务器的脚本，应先让开发服务器以隔离的 `SCHOLARNOTELM_ROOT` 启动。部分脚本依赖已删除的原型状态或本机项目快照，已经过时。
4. **使用项目内运行时**：`./scripts/npm-local.sh`、`./scripts/cargo-local.sh`、`runtimes/downloader/bin/python`。不要用系统 Python 或全局 npm。
5. **不恢复已删除功能**：重排、BM25 / MedCPT、PaddleOCR、清洗策略开关、单篇精读、Chroma、演示项目都是有意删除的，理由见 README。
6. **缓存签名要稳定**：分块、Embedding 输入、提示词协议的改动必须同步更新对应签名；反过来，不要随意改动签名的键列表（例如 `sendTemperature` 已停用但仍保留在签名里），否则已完成的综述和问答会全部被判为过期。
7. **视觉改动只改样式**：遵循 [docs/UI_DESIGN.md](docs/UI_DESIGN.md)，颜色、字号、圆角、阴影、时长只用 `apps/desktop/src/tokens.css` 中的 token，通用组件样式放在 `design.css`。不改变交互。不要给包含 `position: fixed` 子元素的容器加 `backdrop-filter` 或常驻 `transform`。

## 常用命令

```sh
./scripts/npm-local.sh run desktop        # 开发版（Tauri，前端热更新）
./scripts/npm-local.sh run dev            # 浏览器调试 http://127.0.0.1:1420
./scripts/npm-local.sh run research:build # 修改 research.rs 后重建 Vite 桥接用的 research-cli
```

## 提交前验证

按改动范围选择，至少包括：

```sh
runtimes/downloader/bin/python -m unittest discover -s services/downloader/tests   # Python 全量（约 500 项）
./scripts/cargo-local.sh test --manifest-path apps/desktop/src-tauri/Cargo.toml --bin research-cli
./scripts/npm-local.sh run build                                                  # tsc + Vite 构建
```

修改 `apps/desktop/src-tauri/src/main.rs`，或者移动、删除根目录文件之后，要实际运行一次 `./scripts/npm-local.sh run desktop`，确认桌面窗口能打开。桌面 app 启动时以 `services/downloader/engine.py` 判断根目录；浏览器开发模式和 `research-cli` 都不经过这项检查。

涉及综述、问答、向量或完整流程时，再运行对应的集成脚本（使用本机模拟服务和隔离目录）：`scripts/test-review-writing-integration.py`、`test-qa-mini-review-integration.py`、`test-vectors-integration.py`、`test-library-pipeline.py`。

## 协作约定

- `main` 是主分支。新工作在新分支上进行，验证通过后再合并。
- 变更理由写在提交信息里，不在 `docs/` 新增按日期的变更记录。功能行为改变时，同步更新 README 和对应专题文档。
- 测试脚本会把截图和结果 JSON 写进 `docs/`，这些是运行产物，已被 `.gitignore` 排除，不要提交。

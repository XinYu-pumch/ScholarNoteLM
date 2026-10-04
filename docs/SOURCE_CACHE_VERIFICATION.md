# 0.5.4 验证记录

2026-09-20，macOS。

- Python 下载测试：51 项通过，含旧调度、跨进程入口锁、缓存清空保留、非 Bloom 命中缓存、身份不符回退、Sci-Net iframe、文件并发 2、手动补救、签名地址不缓存。
- 38 篇真实本地 HTTP 调度回归通过：每镜像入口峰值 1，不同镜像并行，Bloom 命中组补救先完成。
- TypeScript 检查及 Vite 生产构建通过。
- Chromium 隔离项目下载 UI / RPC 回归通过。
- 正式 Python 引擎联网复测原 20 篇：14 成功，6 未取得，40.061 秒；全部 14 个下载文件重新核对正文 DOI 与 SHA-256。此轮采用与对照实验相同的 ru/su 两个入口，S3 / Unpaywall 在隔离测试中跳过，不是整个真实项目下载时长。记录见 `SOURCE_CACHE_LIVE_TEST.json`。
- gut 来源缓存迁移前已备份下载数据库；加入实验验证过的 14 个文件地址并回填旧记录，未将实验 PDF 复制到文献库。记录见 `SOURCE_CACHE_SEED.json`。
- Tauri 开发模式启动成功。通过界面观察验证 App.tsx 保存后版本标识自动更新，无手动刷新；日志确认 Rust / Tauri 配置变更后自动编译重启。
- 本轮没有重新打包 `dist/macos/ScholarNoteLM.app`。运行入口为 `开发启动 ScholarNoteLM.command`，详见 `DEVELOPMENT.md`。

下载预算沿用原应用的分开统计方式：每轮 HTTP 累计 75 秒，锁等待另限 30 秒；入口单次最多 12 秒、文件最多 30 秒。不把实验整批 180 秒上限套到任意规模的项目上。

# 支持诊断与脱敏导出 / Support diagnostics and redacted export

设置 → 开发者诊断中的“安全支持报告”用于把一次故障（例如“有画面但控制断开”“前台恢复无声”“录像停了”）压缩成一份用户主动导出的、可读的结构化快照。它不是日志打包器，也不上传任何内容。

## 1. 如何生成 / How to use it

1. 打开 **设置 → 开发者诊断**，勾选“显示当前窗口的场景同步诊断”。
2. 复现问题；面板上的同步计数会实时显示当前窗口的连接尝试、失败、有效/拒绝消息和原因码。
3. 点击 **生成支持报告**：报告只保存在当前页面，不会自动复制、下载或上传。
4. 用 **复制支持报告** 或 **下载支持报告** 交给维护者；分享前请先自行复核内容。

Support diagnostics are opt-in, page-local and user-exported. Nothing is uploaded, and disabled diagnostics run no extra polling timer.

## 2. 报告包含什么 / What the report contains

| 字段 | 内容 |
| --- | --- |
| `format` / `scope` / `clock` | 固定 schema 标识、`current-page-observations` 范围、UNIX UTC 毫秒时间基准 |
| `identity` | 仅实际注入的版本：WebUI 构建版本、桌面桥接报告的应用版本、客户端类型；源码 revision、后端、APK、WebView、Electron 版本没有注入时为 `unavailable`，不根据 User-Agent 猜测 |
| `nativeRead` | 本次只读原生状态读取的结果（`observed` / `unavailable` / `timeout`，最多等待 1.5 秒） |
| `coverage` | 每个数据源的实际覆盖范围与已知缺口，例如 `media: whep-connections-only`、`recorder: last-archive-view-query`、`services: unavailable`、`frameClock: page-observed-not-source-capture` |
| `limits` | 本次生效的条数与字节上限 |
| 观测数组 | 场景同步连接、媒体（WHEP）状态、直接混音、问题码、导出任务状态、生命周期事件，均为固定枚举值、时间戳与计数 |

只保留显式白名单标量：状态/原因码必须在固定枚举内，计数有上界，时间戳必须是安全的毫秒整数。**不包含** URL、摄像机地址或名称、账号、凭据/Token/Secret、文件路径、任意上游错误字符串、原始媒体、日志正文或场景内容。

Only explicitly allow-listed enums, timestamps and bounded counters are retained. Arbitrary strings, identifiers, endpoints and payloads cannot reach the report.

## 3. 有界性 / Bounds

- 条数上限：控制连接 16、媒体 24、问题 24、事件 64；采样值 256。
- 序列化后 UTF-8 字节上限 48 KiB；超出时报告生成失败并显示错误，**不会**截断成误导性的部分报告。
- 报告生成使用页码代次归属：生成期间离开页面或重新生成，旧结果不会覆盖新结果。
- 未观察或超过 30 秒的缓存观测会标明为陈旧；报告是页面观测快照，不是实时健康检查。

## 4. 可验证性 / Evidence

`web/tests/local-runtime/support-diagnostics.spec.ts` 在 Chromium 中覆盖：用户主动生成/复制/下载与移动端与剪贴板回退；一次快照可区分“有画面但控制断开”“前台无声”“录像/导出停止”；自动敏感哨兵扫描与最大条数夹具强制白名单与字节上限；原生身份只在请求时读取且较新的推送会取代迟到的 IPC 结果；原生超时/拒绝/卸载保持有界且迟到结果不能伪造状态；缓存观测显式变旧且会话重置会清除上一账号的观测。

~~~powershell
# 在 web/ 目录执行（端口 4185，独立输出目录）
node node_modules/@playwright/test/cli.js test -c playwright.support.config.ts --project=chromium --reporter=line
~~~

## 5. 边界 / Limits

- 浏览器夹具不等于真实摄像机、真实服务日志或已安装产品验收；本报告**不**读取后端服务日志、媒体文件或额外服务接口。
- 服务重启原因与次数、后端/APK/WebView 版本在未注入时明确为 `unavailable`，不算“已覆盖”。
- 报告不替代 [问题中心](v4-readiness.md)的逐项错误说明，也不替代服务端审计；权限、网络、超时、磁盘等失败仍需各自的产品级验收。

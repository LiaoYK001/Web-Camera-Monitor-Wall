# Post-security-update continuity / 安全更新后的连续性

Status: implemented on `dev`; verified by `web/tests/pwa-security-update.spec.ts` against the
production-built service worker. Not a real-device or installed-product qualification.

状态：已在 `dev` 实现；由 `web/tests/pwa-security-update.spec.ts` 针对生产构建的 Service Worker 验证。
不代表真机或已安装产品验收。

## What a forced security replacement does / 强制安全替换会做什么

When the server is upgraded, a stale shell must not keep an older authentication gate alive.
`web/src/sw.ts` therefore replaces itself immediately: the new worker writes a durable record
(`webobs-security-update-v1` in Cache Storage, `/__webobs-security-update__`) during `install`,
calls `skipWaiting()`, claims the clients and navigates every open window in `activate`. Drafts are
never allowed to delay that replacement.

服务器升级后，旧应用壳不得继续持有过期的认证入口。因此 `web/src/sw.ts` 立即自我替换：新 Worker 在
`install` 阶段写入持久记录（Cache Storage 中的 `webobs-security-update-v1`，路径
`/__webobs-security-update__`），调用 `skipWaiting()`，在 `activate` 中接管客户端并重新导航所有已打开窗口。
草稿不会、也不允许延迟该替换。

`activate` keeps the record on purpose. It is the only medium the worker and the reloaded document
share across a forced navigation, and it contains nothing but the replacement timestamp. A first
install (no active worker) never writes it.

`activate` 有意保留该记录：它是 Worker 与被强制导航后的文档之间唯一共享的介质，且内容只有替换时间戳。
首次安装（没有活动 Worker）不会写入记录。

## What the reloaded shell tells the user / 重新载入后的界面会说明什么

A persistent `role="status"` notice named `安全更新恢复提示` (see `web/src/pwaContinuity.tsx`) is
rendered by the outermost shell owner, so it also covers the authentication gate. It states:

- **lost / 丢失**：旧页面中输入但未提交的内容（Studio 场景名称、画布与来源改动等）随页面一起丢失，**无法恢复**；
- **survived / 保留**：已保存的加密本机配置与离线同步队列仍在本机；恢复期间不会自动上传，需在“同步与配对”中
  显式点击“立即同步”；
- **server tasks / 服务器任务**：导出、备份等服务器端任务必须到“导出任务”等任务列表核对实际状态。

The notice links to the device-sync/settings area and stays until an explicit user action
(acknowledgement, or a completed explicit sync) clears the record. It survives reloads and is never
dismissed by a timer. Unsaved draft text and credentials are never written to
`localStorage`/`sessionStorage`/IndexedDB to "remember" what was lost.

提示提供跳转到设备同步/设置的入口，并且只有用户显式操作（确认提示，或完成一次显式同步）才会清除记录；
刷新页面不会让它消失，更不会有定时器自动关闭。为“记住”丢失内容而把草稿文本或凭据写入
`localStorage`/`sessionStorage`/IndexedDB 的做法在本项目中始终被禁止。

## What the shell refuses to do automatically / 界面不会自动执行的操作

- **No automatic sync after an update / 更新后不自动同步**：while the record exists, `useDeviceSync`
  does not start its mount/timer upload, so the durable encrypted queue stays on the device until the
  user explicitly syncs. Normal (non-update) mounts keep their immediate sync.
  记录存在期间，`useDeviceSync` 不启动挂载/定时上传，加密队列保留在本机直到用户显式同步；无更新时的
  正常挂载仍会立即同步。
- **Raw HTTP counts are not a product contract / 原始 HTTP 次数不是产品契约**：the contract fixture destroys the
  socket without a response, and Chromium may resend that identical request on its own (measured: 5 raw POSTs,
  1 distinct requestId, 1 accepted job; the count varies with connection pooling and reproduces with no service
  worker at all). The suite therefore asserts request identity, a single accepted job and zero submissions from
  the update path — never a raw POST count the page cannot control. A raw count of 1 is not achievable from
  client JavaScript and must not be re-introduced as an assertion.
  夹具在无响应时销毁套接字，Chromium 自己可能重发同一请求（实测 5 次原始 POST、1 个请求标识、1 个被受理任务；
  次数随连接池状态变化，且在没有 Service Worker 时同样复现）。因此用例断言请求标识、被受理任务数量与更新路径
  零提交，而不是页面无法控制的原始 POST 次数；不要把它改回“次数必须为 1”。
- **No blind retry of an unknown export / 未知结果不盲目重试**：a pending evidence export whose response
  was lost is reconciled read-only from the job list. After an update the `恢复同一次提交` control is
  replaced by a read-only refresh, because re-posting could duplicate an accepted export. Jobs that
  genuinely failed keep their normal `重新导出` control.
  响应丢失的导出任务只通过读取任务列表做只读核对；安全更新后不再提供 `恢复同一次提交`，避免重复导出。
  真正失败的任务仍保留正常的 `重新导出`。
- **No credentials or private routes in the cache / 缓存不含凭据与私有路由**：`/api/**`,
  `/recordings/**`, `/metrics` and cross-origin media stay network-only; the transient password field is
  never persisted.

## Untested boundaries / 未验收边界

- Verified only with the Windows Chrome build used by the Playwright gate, over the
  `http://127.0.0.1` development origin. No HTTPS certificate, installed PWA, Android WebView, iOS or
  real-device qualification was performed.
- Storage eviction, private-browsing storage limits and a user who never acknowledges the notice
  (automatic syncing stays suspended for that document) are outside this verification.
- Multi-window consistency relies on `BroadcastChannel` plus a re-read on focus/visibility; a browser
  without `BroadcastChannel` updates each window on its next visibility change.
- Server-side export/backup jobs are only *reported*: their real progress and retention are server
  responsibilities and are not exercised here.
- 未完成真实摄像机、媒体链路、HTTPS 证书、已安装 PWA、Android/iOS 等真机验收；浏览器存储被清理、
  隐私模式配额以及长期不确认提示的情形不在本次验证范围内。

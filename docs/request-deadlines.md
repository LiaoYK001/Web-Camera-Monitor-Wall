# Request deadlines / 请求时限

`web/src/requestTimeout.ts` bounds the caller's wait for login discovery, account synchronization, Studio reads and archive queries/actions. It aborts the transport and independently rejects the wait at the existing operation-specific deadline. A transport that substitutes `AbortError` still reports `TimeoutError`; a transport that ignores cancellation cannot keep the UI waiting. The helper uses `AbortController`, timers and a promise race without requiring the newer static `AbortSignal.any` or `AbortSignal.timeout` APIs.

`web/src/requestTimeout.ts` 为登录探测、账号同步、Studio 读取及归档查询/操作提供等待时限。到达各操作已有的时限后，中止传输并独立结束等待：传输将原因替换为 `AbortError` 时仍报告 `TimeoutError`；传输忽略取消时也不会令界面持续等待。实现使用 `AbortController`、计时器和 Promise 竞争，不要求较新的静态 `AbortSignal.any` 或 `AbortSignal.timeout` API。

Owner cancellation preserves its original reason, including an explicit `null`. An already cancelled owner never starts an operation. Completion removes the timer and owner listener; later cancellation does not abort a completed request. Late transport fulfillment/rejection remains handled and cannot replace an already delivered cancellation result. The underlying operation must pass the supplied signal to its transport and must not apply UI state internally after ownership changes; the helper bounds its returned promise, not arbitrary side effects inside that operation.

所属页面或任务取消时保留原始原因，包括显式 `null`；已经取消时不启动操作。请求完成会移除计时器与所属对象的监听，后续取消不再中止已完成请求。传输晚到的成功或失败保持被处理，不能替换已交付的取消结果。操作应将提供的 signal 传给传输，并避免在所属对象变化后自行应用界面状态；辅助函数限制返回 Promise 的等待，无法撤销操作内部任意副作用。

A client timeout does not prove that the server cancelled a mutation. Archive lock/delete/snapshot actions retain their unconfirmed-result handling; durable export jobs retain their explicit server cancellation and response-loss idempotency. Do not automatically repeat a mutation merely because the client deadline elapsed. See [timeline evidence](timeline-evidence.md) for recovery behavior.

客户端超时不能证明服务端取消了修改。归档锁定、删除和截图继续按“结果尚未确认”处理；持久化导出任务继续使用明确的服务端取消与响应丢失去重。不能仅因客户端等待超时就自动重做修改；恢复逻辑见[时间线与证据](timeline-evidence.md)。

`request-deadline.spec.ts` covers raw transport abort errors, ignored cancellation, in-flight and pre-existing owner cancellation, exact cancellation reasons, late rejection cleanup and normal success/error preservation. It disables both static AbortSignal helpers and uses a browser clock to check the deadline deterministically. Related login/offline/sync/archive regressions exercise the callers. Complete Linux synthetic H.264 monitoring and the installed MuMu WebView 110 client additionally check the normal product path. These checks do not qualify real weak networks, physical cameras or ARM devices.

`request-deadline.spec.ts` 覆盖传输原始取消报错、忽略取消、进行中与预先取消、原因保留、晚到失败处理及正常成功/错误不被改写。测试禁用两个静态 AbortSignal 辅助 API，以浏览器时钟确定性验证时限；相关登录、离线、同步及归档回归验证调用方。完整 Linux 合成 H.264 监控和已安装的 MuMu WebView 110 客户端另验证正常产品流程；这些检查不等同真实弱网、摄像机或 ARM 设备验收。

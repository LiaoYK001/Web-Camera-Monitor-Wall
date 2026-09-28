# v3.3 release notes / v3.3 发布说明

## 中文

- 账户与跨设备体验：以账户会话替代浏览器配对码；账户下的视频源、预设和监控工作区设置可以在登录设备间同步。
- 设备与视频源：支持批量导入、账号权限信息、改进的来源探测和音轨状态反馈，并补充 HTTP 摄像机网页入口接入 go2rtc 的操作说明。
- 监控墙：修复混音控制、实时布局与层级设置，完善独立投影窗口，并优化移动端设备操作。
- 局域网开发：改进开发入口、HTTPS 和远端视频连接，便于同一局域网内的其他客户端联调。
- 验证：公开源码审计、依赖锁校验、发布策略测试、PWA 类型检查、IWA 类型检查和生产构建已在集成候选上通过。稳定发布还必须为最终 `main` 提交生成有效的 Windows、WSL2 与 v3-M2 私有门禁收据，并通过对应远端 CI。
- 限制：RTSP 播放仍取决于网关/go2rtc 对摄像机网络和认证信息的可达性；HTTP 首页不会由服务器抓取，需手动提供媒体路径。真实摄像机兼容性必须使用目标设备确认。发布说明不包含真实地址或凭据。

## English

- Accounts across devices: replace browser pairing codes with account sessions; synchronize account video sources, presets, and monitor workspace settings across signed-in clients.
- Devices and sources: add bulk import, account permission details, improved source probing and audio-track feedback, plus instructions for connecting camera web pages through go2rtc.
- Monitor wall: fix mixer controls, live layout and layer settings, improve detached projector windows, and streamline mobile device workflows.
- LAN development: improve development entry points, HTTPS, and remote video connectivity for clients on the same LAN.
- Verification: the integration candidate passed the public source audit, dependency-lock check, release-policy tests, PWA typecheck, IWA typecheck, and production build. Stable publication still requires fresh Windows, WSL2, and v3-M2 private-gate receipts bound to the final `main` commit and the corresponding remote CI checks to pass.
- Limitations: RTSP playback still depends on the gateway/go2rtc being able to reach and authenticate to the camera. HTTP homepages are not fetched by the server; provide a media path manually. Compatibility must be confirmed with the target cameras. No real endpoints or credentials are included in these notes.

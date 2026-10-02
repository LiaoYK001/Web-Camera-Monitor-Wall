# v3.3 release notes / v3.3 发布说明

> **安全提示 / Security notice:** v3.3 升级后，仍由 v3.2 或更早 Service Worker 控制的旧 PWA 可能凭本机离线授权继续显示缓存工作区。请在共享设备上刷新或清除旧 PWA；完整修复计划随 v3.4 发布。详情见[安全公告](security-advisory-v3.3.md)。
> After upgrading to v3.3, an old PWA still controlled by a v3.2 or earlier service worker may show its cached workspace under a local offline grant. Refresh or clear old PWAs on shared devices; the full fix is planned for v3.4. See the [security advisory](security-advisory-v3.3.md).

## 中文

- 账户与跨设备体验：以账户会话替代浏览器配对码；账户下的视频源、预设和监控工作区设置可以在登录设备间同步。
- 设备与视频源：支持批量导入、账号权限信息、改进的来源探测和音轨状态反馈，并补充 HTTP 摄像机网页入口接入 go2rtc 的操作说明。
- 监控墙：修复混音控制、实时布局与层级设置，完善独立投影窗口，并优化移动端设备操作。
- 局域网开发：改进开发入口、HTTPS 和远端视频连接，便于同一局域网内的其他客户端联调。
- 验证：Windows `scripts/dev.ps1 -Check` 与 Ubuntu 24.04 WSL `bash scripts/dev.sh --check` 均通过；Docker Compose 镜像构建与容器健康检查通过；首次管理员注册、登录、摄像机条目创建/读取通过；容器内合成 RTSP 流以 H.264 640×360 回读通过。未使用真实摄像机，因此不声称真实设备首帧播放或录像链路通过。v3.3 按 [发布流程](release-flow.md) 发布；平台与容器验证由发布者人工执行并记录，不要求本机门禁收据。
- 限制：RTSP 播放仍取决于网关/go2rtc 对摄像机网络和认证信息的可达性；HTTP 首页不会由服务器抓取，需手动提供媒体路径。真实摄像机兼容性必须使用目标设备确认。发布说明不包含真实地址或凭据。

## English

- Accounts across devices: replace browser pairing codes with account sessions; synchronize account video sources, presets, and monitor workspace settings across signed-in clients.
- Devices and sources: add bulk import, account permission details, improved source probing and audio-track feedback, plus instructions for connecting camera web pages through go2rtc.
- Monitor wall: fix mixer controls, live layout and layer settings, improve detached projector windows, and streamline mobile device workflows.
- LAN development: improve development entry points, HTTPS, and remote video connectivity for clients on the same LAN.
- Verification: Windows `scripts/dev.ps1 -Check` and Ubuntu 24.04 WSL `bash scripts/dev.sh --check` passed. The Docker Compose image built and passed its health check; first-admin registration/login and camera-record creation/readback passed; a synthetic RTSP stream round-tripped as H.264 640×360 inside the container. No real camera was used, so real-device first-frame playback or recording is not claimed as verified. v3.3 follows the [release flow](release-flow.md); platform and container checks are recorded manually, with no local gate receipt requirement.
- Limitations: RTSP playback still depends on the gateway/go2rtc being able to reach and authenticate to the camera. HTTP homepages are not fetched by the server; provide a media path manually. Compatibility must be confirmed with the target cameras. No real endpoints or credentials are included in these notes.

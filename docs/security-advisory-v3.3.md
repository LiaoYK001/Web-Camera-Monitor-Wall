# Security advisory: stale offline PWA session / v3.3 旧版离线 PWA 安全提示

**Status:** Affected upgrade path; a fix is being prepared for v3.4. The fix is not released yet.
**状态：** v3.3 升级路径受影响；修复正在为 v3.4 准备，尚未发布。

## 中文

### 影响范围

将服务升级到 v3.3 后，如果浏览器或已安装的 PWA 仍由 v3.2（或更早版本）的 Service Worker 控制，旧页面可能继续使用本地离线授权显示缓存的工作区，而不重新要求账号密码。特别是认证服务暂时不可达时，旧版页面会把有效的本地离线授权当作继续进入界面的依据。拥有该浏览器配置文件或设备访问权的人因此可能看到该设备本地缓存的项目数据。

受影响的是旧客户端的本地离线界面和缓存数据。认证开启且服务器可达时，摄像机、账户和其他受保护 API 仍由服务端校验；这不等同于远程绕过服务器认证。

### v3.3 临时处理

- 在旧 PWA 中若出现“应用新版本”，点击并等待页面重新加载；然后确认出现 v3.3 账号登录界面或已登录账号信息。
- 在共享或不受信任的设备上，不要让旧版 PWA 处于离线授权状态。可使用无痕窗口打开当前服务进行登录验证。
- 若设备即将交给他人，关闭旧版 PWA，并从浏览器站点设置清除该站点数据。此操作会同时清除本机保存的配置档案和离线数据；先确认需要的数据已同步或备份。
- 持续保持服务器端认证开启；不要把无认证的本机开发配置暴露到局域网或互联网。

### 修复计划

v3.4 将在新 Service Worker 完成更新后自动激活并重新加载已打开的客户端，避免旧认证界面继续留在运行中的 PWA 中；认证服务不可验证时，登录界面保持关闭访问。该修复发布前，v3.3 用户仍应按上述方式刷新旧 PWA。

## English

### Impact

After upgrading the server to v3.3, a browser or installed PWA still controlled by a v3.2 (or earlier) service worker may keep showing its cached workspace under a valid local offline grant without asking for the account password again. This is relevant when the authentication service is temporarily unreachable. Anyone with access to that browser profile or device may see data cached locally by the old client.

The affected surface is the old client's local offline UI and cached data. When server authentication is enabled and reachable, camera, account, and other protected APIs continue to be checked by the server. This is not a remote bypass of server authentication.

### v3.3 workarounds

- If the old PWA offers **Apply update**, select it and wait for the page to reload. Confirm that the v3.3 account login or signed-in account is shown.
- Do not leave an old PWA in offline-authorized mode on a shared or untrusted device. A private browser window can be used to verify the current service.
- Before handing a device to someone else, close the old PWA and clear this site's data in browser settings. This also deletes local profiles and offline data; confirm that needed data is synced or backed up first.
- Keep server-side authentication enabled. Do not expose an unauthenticated local-development configuration to a LAN or the Internet.

### Planned fix

v3.4 will activate a new service worker automatically after an update is installed and reload open clients, preventing an old authentication UI from remaining in a running PWA. The application will remain closed when the authentication service cannot verify access. Until that fix is released, v3.3 users should refresh old PWAs using the workarounds above.

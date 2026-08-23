# ONVIF media operations / ONVIF 媒体运维

v1-M10 begins with an authenticated, read-only media synchronization path. It turns an ONVIF device endpoint into stable Camera Registry profiles without persisting a username, password, or credential-bearing URL.

v1-M10 首个设备运维闭环是带认证、只读的媒体同步路径。它把 ONVIF 设备端点转换为稳定的 Camera Registry Profile，同时不持久化用户名、密码或携带凭据的 URL。

## Implemented boundary / 已实现边界

- The client calls Device `GetServices`, prefers the Media2 service used by the Profile T path, and falls back to the legacy Media service for Profile S compatibility.
- It reads `GetProfiles`, `GetStreamUri`, and the primary profile's optional `GetSnapshotUri`. Video/audio codec, resolution, frame rate, main/sub role, PTZ/events/imaging service presence, and synchronization time are cached.
- `credentialsRef` resolves only inside `/run/secrets/webobs-camera-credentials`. SQLite and public API responses retain the reference, never the secret value.
- WS-Security UsernameToken PasswordDigest is included when a credential exists. HTTP Digest challenges are supported. HTTPS uses the system trust store with hostname validation; there is no silent insecure-TLS mode.
- SOAP responses are capped at 2 MiB. DTD/entity declarations and endpoint redirects are rejected. Device error bodies, usernames, passwords, nonces, and authorization headers are not returned by the API or logger.

- 客户端先调用设备 `GetServices`，优先使用 Profile T 路径采用的 Media2 服务，并以旧 Media 服务作为 Profile S 兼容回退。
- 客户端读取 `GetProfiles`、`GetStreamUri` 及主 Profile 可选的 `GetSnapshotUri`，缓存视频/音频编码、分辨率、帧率、主/子码流角色、PTZ/事件/成像服务存在性和同步时间。
- `credentialsRef` 只能在 `/run/secrets/webobs-camera-credentials` 内解析；SQLite 与公开 API 只保留引用，不保存 Secret 值。
- 配置凭据时请求携带 WS-Security UsernameToken PasswordDigest，并支持 HTTP Digest 挑战。HTTPS 使用系统信任库并校验主机名，不会静默降级为不安全 TLS。
- SOAP 响应上限为 2 MiB，拒绝 DTD/实体声明与端点重定向；API 和日志不返回设备错误正文、用户名、密码、nonce 或 Authorization header。

This is a client implementation target, not a claim that a camera is ONVIF-conformant. Only the ONVIF conformance process can establish product conformance. The project records `profileVersion: T` when the Media2 path succeeds and `S` when the compatibility path is used so operators can see the actual execution path.

这是客户端实现目标，不是对摄像机已通过 ONVIF 合规认证的声明。只有 ONVIF 合规流程能够确认产品合规。项目在 Media2 主路径成功时记录 `profileVersion: T`，使用兼容路径时记录 `S`，让运维人员能够看到实际执行链。

## Secret and WebUI workflow / Secret 与 WebUI 流程

Create a container secret outside Git:

在 Git 外创建容器 Secret：

```json
{
  "username": "operator",
  "password": "replace-with-a-device-password"
}
```

Mount it read-only as `/run/secrets/webobs-camera-credentials/front-door.json`. In **设备与码流**, enter the device address, run automatic detection, set `front-door` as the Secret reference, and select **读取 ONVIF Profile**. Review the reported Profile version and streams before saving. A saved ONVIF camera can later use **同步 ONVIF Profile** to refresh capability drift.

将其只读挂载为 `/run/secrets/webobs-camera-credentials/front-door.json`。在“设备与码流”中输入设备地址并执行自动检测，将 Secret 引用设为 `front-door`，再选择“读取 ONVIF Profile”。确认返回的 Profile 版本与码流后再保存；已保存的 ONVIF 摄像机可用“同步 ONVIF Profile”刷新能力变化。

## API / 接口

- `POST /api/v1/onvif/probe` with `{"address":"https://camera.example.invalid/onvif/device_service","credentialsRef":"front-door"}` performs a read-only probe.
- `POST /api/v1/cameras/{cameraId}/onvif/sync` refreshes a saved ONVIF camera and marks it online only after a complete successful transaction.

Both operations require the normal authenticated, same-origin mutation boundary. A failed probe does not create or partially update a camera.

两个操作都受常规认证和同源写操作边界保护。探测失败不会创建摄像机，也不会留下部分更新。

## Verification and remaining v1-M10 work / 验证与剩余 v1-M10 工作

`tests/test_camera_registry.py` provides deterministic HTTP Digest plus WS-Security fixtures for the Media2/Profile T path, the Media/Profile S fallback, authentication redaction, malformed XML, entity rejection, and response-size limits. Run it with:

`tests/test_camera_registry.py` 使用确定性夹具覆盖 HTTP Digest + WS-Security 的 Media2/Profile T 主路径、Media/Profile S 回退、认证失败脱敏、畸形 XML、实体拒绝和响应大小限制：

```bash
python3 tests/test_camera_registry.py
```

The v1-M10 implementation includes PTZ/presets, ephemeral PullPoint events, snapshots, guarded talk, bounded interface selection and clock-skew correction. A generated TLS fixture proves that an untrusted device certificate is rejected and a specifically trusted certificate succeeds; verification is never disabled. v1.2 uses deterministic ONVIF coverage plus a redacted real external media decode gate. Multi-vendor model/firmware testing continues separately and does not create a brand-wide conformance claim. No real address, credential, serial number or recording belongs in public reports.

v1-M10 实现包含 PTZ/预置位、临时 PullPoint 事件、快照、受控对讲、指定接口发现与时钟偏移校正；生成式 TLS 夹具证明不受信设备证书会被拒绝、显式信任后才成功，且从不关闭验证。v1.2 采用确定性 ONVIF 覆盖加脱敏真实外部媒体解码门禁；多厂商型号/固件测试独立持续进行，不形成品牌级合规声明。公开报告不得包含真实地址、凭据、序列号或录像。

The design follows the official [ONVIF Profile T](https://www.onvif.org/profiles/profile-t/) target and retains [Profile S](https://www.onvif.org/profiles/profile-s/) only as a compatibility path.

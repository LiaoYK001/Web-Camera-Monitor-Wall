# Camera compatibility qualification / 摄像机兼容性资格验证

## Release policy / 发布策略

Camera compatibility is evaluated in three evidence tiers. v1.2 requires tiers A and B; tier C is continuous compatibility work and does not block a security or bug-fix release.

摄像机兼容性按三层证据评估。v1.2 要求 A、B 两层通过；C 层属于持续兼容工作，不阻塞安全或缺陷修复版本。

- **Tier A — deterministic protocol contracts / A 层：确定性协议契约：** the pinned ONVIF emulator covers Profile T primary/Profile S fallback, Digest, WS-Security, TLS trust and rejection, clock skew, private tokens, PTZ, presets, snapshots, PullPoint events and guarded talk. A local Server Push MJPEG fixture covers multipart detection when `HEAD` is unsupported.
- **Tier B — redacted external media / B 层：脱敏外部媒体：** at least one real external camera transport must negotiate actual media metadata and decode at least five consecutive frames. The endpoint, credentials, serial number, frame data and raw logs remain outside Git.
- **Tier C — ongoing vendor matrix / C 层：持续厂商矩阵：** named model/firmware combinations are tested as hardware becomes available. Results may add compatibility notes or fixes, but no untested model is described as conformant or supported.

- **A 层——确定性协议契约：** 固定 ONVIF 模拟器覆盖 Profile T 主路径/Profile S 回退、Digest、WS-Security、TLS 信任与拒绝、时钟偏移、私有 Token、PTZ、预置位、快照、PullPoint 事件及受控对讲；本地 Server Push MJPEG 夹具覆盖设备不支持 `HEAD` 时的 multipart 检测。
- **B 层——脱敏外部媒体：** 至少一种真实外部摄像机传输必须协商出实际媒体参数，并连续解码至少五帧。端点、凭据、序列号、帧数据与原始日志均不得进入 Git。
- **C 层——持续厂商矩阵：** 获得硬件后按明确型号/固件持续测试；结果可形成兼容说明或修复，但不得把未测试型号描述为合规或受支持。

This policy deliberately distinguishes implementation tests from ONVIF conformance. ONVIF states that conformance belongs to a registered product and its specific firmware, not to a brand in general. The authoritative source is the [ONVIF conformant-products database](https://www.onvif.org/conformant-products/).

该策略有意区分“实现测试”和“ONVIF 合规”。ONVIF 明确说明合规性属于已登记的具体产品及其特定固件，不能由品牌整体代替；权威来源是 [ONVIF 合规产品数据库](https://www.onvif.org/conformant-products/)。

## Current protocol landscape / 当前协议生态

- ONVIF reports more than 33,000 profile-conformant products and says most current conformant devices/clients support both Profile S and Profile T. Profile S submissions end after March 31, 2027; Profile T is the preferred modern target. Motion JPEG is not part of Profile T, so a separate HTTP MJPEG adapter remains necessary. See the [ONVIF Profile S deprecation notice](https://www.onvif.org/pressrelease/onvif-to-end-support-for-profile-s/) and [Q&A](https://www.onvif.org/profiles/profile-s/profile-s-deprecation-qna/).
- Canon WV-HTTP defines `/-wvhttp-01-/video.cgi` JPEG video as `multipart/x-mixed-replace` Server Push. See Canon's [WebView HTTP protocol specification](https://downloads.canon.com/nw/nvs/misc-pages/nvs-webview-sdk-downloads/BIE-7082-001_WebView_HTTP_ProtocolSpec_E.pdf).
- Axis VAPIX exposes the equivalent `/axis-cgi/mjpg/video.cgi` multipart stream and recommends reading the returned image dimensions rather than assuming the requested resolution. See the [Axis video streaming API](https://developer.axis.com/vapix/network-video/video-streaming/).
- Current Bosch camera families provide examples of devices advertising Profile S/G/M/T, but every claim still depends on the exact model and firmware. See an official [Bosch camera data sheet](https://cdn.commerce.boschsecurity.com/public/documents/NBE_3703_AL_Data_sheet_enUS_120604925067.pdf).

## v1.2 external evidence / v1.2 外部证据

On 2026-08-24, a privately supplied Canon WV-HTTP endpoint returned `Server: VB/4.0` and `multipart/x-mixed-replace`, negotiated Motion JPEG at 320×240 and 25 FPS, and decoded five consecutive frames in the product image. The requested size was larger, demonstrating why the gate records negotiated values. The address and frame data are intentionally omitted.

2026-08-24，私下提供的 Canon WV-HTTP 端点返回 `Server: VB/4.0` 与 `multipart/x-mixed-replace`，实际协商为 320×240、25 FPS 的 Motion JPEG，并在产品镜像内连续解码五帧。请求尺寸更大，因此该结果也证明门禁必须记录实际协商值。此处有意省略地址及帧数据。

Repeat the redacted gate without placing the URL on the Docker command line:

复验时通过环境变量传入地址，不把 URL 放到 Docker 命令参数中：

```powershell
$env:WEBOBS_REAL_MJPEG_URL = Read-Host 'Private HTTP(S) MJPEG URL'
./tests/run-m10-real-mjpeg.ps1 -Image webobs:m0
Remove-Item Env:WEBOBS_REAL_MJPEG_URL
```

```bash
read -rsp 'Private HTTP(S) MJPEG URL: ' WEBOBS_REAL_MJPEG_URL
export WEBOBS_REAL_MJPEG_URL
./tests/run-m10-real-mjpeg.sh
unset WEBOBS_REAL_MJPEG_URL
```

Passing this gate means that the published adapter contract works for the observed endpoint. It is not Canon-wide certification, an ONVIF conformance claim, or evidence for PTZ/events/talk on that device.

通过该门禁只表示已观察端点符合已发布 Adapter 契约，不代表 Canon 全系列认证、ONVIF 合规声明，也不证明该设备的 PTZ、事件或对讲能力。

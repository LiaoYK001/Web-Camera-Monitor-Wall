# Scene document schema v5 / 场景文档 v5

Schema v5 extends the v4 Canvas Studio contract with stable Camera Registry references. Existing source kinds and all layout, audio, filter, grouping, transition, migration, and redaction rules remain unchanged.

场景 schema v5 在 v4 Canvas Studio 契约上增加稳定的 Camera Registry 引用。既有来源类型以及布局、音频、滤镜、分组、转场、迁移和脱敏规则保持不变。

## Camera source / 摄像机来源

```json
{
  "id": "source-front-door",
  "kind": "camera",
  "name": "Front Door",
  "cameraId": "front-door",
  "profileId": "sub",
  "hardwareDecode": "auto",
  "muted": true,
  "volume": 1.0,
  "syncOffsetMs": 0,
  "monitoring": "none",
  "audioTrack": 1,
  "filters": []
}
```

`cameraId` and `profileId` are 1–64 character stable identifiers. `hardwareDecode` is `auto`, `on`, or `off`; `on` expresses preference and never bypasses the runtime VA-API probe. A Camera source must not contain a raw URL. The loopback Camera Registry resolves the endpoint and a separately mounted `credentialsRef` only when an internal consumer needs it.

Scene 只保存稳定 ID，不保存地址、用户名、密码或 token。`hardwareDecode=on` 也不能绕过设备、driver、Decode entrypoint 与运行探测；硬件不可用时安全回落软件解码并在能力接口中说明原因。

## Registry relationship / Registry 关系

```text
Camera
  └─ Stream Profile
       └─ Protocol Adapter
            ├─ onvif / rtsp
            ├─ mjpeg / snapshot / hls / http-flv
            ├─ whep / srt / rtp
            └─ v4l2 (optional local device)
```

Camera Registry uses `/config/webobs/cameras.db` in SQLite WAL mode. A profile contains its adapter endpoint and non-secret media metadata. Credentials live under `/run/secrets/webobs-camera-credentials/<reference>.json`; API documents return only the reference, never the resolved URL.

HTTP Camera Stream and Browser Source are deliberately distinct. MJPEG/HLS/Snapshot adapters represent media input. A `browser` source renders a trusted webpage through CEF, is Composite-only, and keeps the stricter origin/private-network policy from v4.

## Migration / 迁移

The loader accepts v0–v4. On first migration it writes `<scene>.pre-v5.backup` with mode `0600`, adds safe defaults, validates the entire result, and atomically replaces the active file. Legacy RTSP sources remain valid so existing deployments do not lose connectivity; new WebUI flows prefer Camera Registry sources.

加载器接受 v0–v4；首次迁移会保存权限为 `0600` 的原始备份，再完整校验并原子替换。旧 RTSP 来源继续有效，新建来源默认引用 Registry。

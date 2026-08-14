# Scene document schema v3 / 场景文档 v3

Schema v3 is the current scene contract shared by persistence, REST/WebSocket, the Web editor, Direct playback, and the libobs runtime. It retains the v2 RTSP/browser source shapes and adds one unified audio-control model to every source.

场景 schema v3 是持久化、REST/WebSocket、Web 编辑器、Direct 播放和 libobs 运行时共用的当前契约。它保留 v2 的 RTSP/浏览器来源结构，并为每个来源加入统一音频控制模型。

## Audio fields / 音频字段

Every RTSP or browser source contains these fields in addition to its v2 kind-specific fields:

每个 RTSP 或浏览器来源除 v2 类型专属字段外，还包含以下字段：

```json
{
  "muted": true,
  "volume": 1.0,
  "syncOffsetMs": 0,
  "monitoring": "off",
  "audioTrack": 1
}
```

- `muted` is a boolean and `volume` is finite from 0 through 1.
- `syncOffsetMs` is an integer from -10000 through 10000 and is applied to libobs in nanoseconds.
- `monitoring` is `off`, `monitor-only`, or `monitor-and-output`.
- `audioTrack` is an integer from 1 through 6 and maps to exactly one libobs audio mixer bit.

- `muted` 为布尔值，`volume` 为 0 到 1 之间的有限数值。
- `syncOffsetMs` 为 -10000 到 10000 的整数，并以纳秒单位应用到 libobs。
- `monitoring` 只能是 `off`、`monitor-only` 或 `monitor-and-output`。
- `audioTrack` 为 1 到 6 的整数，并精确映射到一个 libobs 音频 mixer 位。

Direct WHEP now negotiates a receive-only audio transceiver. The Web player stays muted until a user explicitly enables sound, then applies each source's `muted` and `volume` values. This is the M5 foundation, not the complete audio exit gate: mixed Composite Opus, audible final recordings, multi-source drift/reconnect testing, and monitoring-device deployment remain pending.

Direct WHEP 现会协商 recvonly 音频 transceiver。Web 播放器在用户明确启用声音前保持静音，启用后应用每路来源的 `muted` 与 `volume`。这是 M5 底座而不是完整音频验收：Composite Opus 混音、有声最终录像、多来源漂移/重连测试及监听设备部署仍待完成。

## Migration / 迁移

The loader accepts schema v0, v1, and v2. Migration preserves the existing revision (or initializes revision zero for v0), assigns `syncOffsetMs: 0`, `monitoring: "off"`, and `audioTrack: 1` to every legacy source, validates the full v3 document, and atomically rewrites it with mode `0600`. Future versions are rejected without modifying the file.

加载器接受 schema v0、v1 和 v2。迁移会保留既有 revision（v0 初始化为 0），为每个旧来源设置 `syncOffsetMs: 0`、`monitoring: "off"` 和 `audioTrack: 1`，完整校验 v3 文档后以 `0600` 权限原子回写。未来版本会被拒绝且不会修改文件。

All v2 browser URL policy, redaction, limits, lifecycle, and cache rules remain unchanged; see [schema v2](scene-schema-v2.md) for those historical additions.

v2 的浏览器 URL 策略、脱敏、边界、生命周期和缓存规则均保持不变；这些历史新增项见 [schema v2](scene-schema-v2.md)。

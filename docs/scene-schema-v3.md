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

Direct WHEP negotiates receive-only audio. Every tile `<video>` remains muted permanently so audio is emitted exactly once through a shared 48 kHz Web Audio graph. A trusted user click creates/resumes that graph; each source then passes through a `DelayNode` and `GainNode` that apply `syncOffsetMs`, `muted`, and `volume`. Negative offsets are normalized against the most-negative active offset because a browser cannot play audio before it arrives; relative source alignment is preserved by delaying the other inputs. The graph is suspended again when sound is disabled and is rebuilt safely across WHEP reconnects.

Direct WHEP 会协商 recvonly 音频。所有画面 `<video>` 始终保持静音，声音只由一个共享的 48 kHz Web Audio 图输出一次。可信用户点击后才创建或恢复该图，每路来源经 `DelayNode` 与 `GainNode` 应用 `syncOffsetMs`、`muted` 和 `volume`。浏览器不能播放尚未到达的声音，因此负偏移会以当前最小偏移为基线，把其他输入相对延后，从而保持来源之间的相对对齐。关闭声音时该图会暂停，WHEP 重连后也会安全重建输入。

Composite mode applies all five fields directly to libobs sources. Mixer track 1 is the M5 program track: it is encoded as 96 kbps Opus for WHIP/WHEP and 128 kbps AAC, 48 kHz stereo for the finalized MP4. Sources assigned to tracks 2 through 6 are excluded from these M5 program outputs and are reserved for later multi-output work. `audioTrack` does not split the single browser-side Direct destination. `monitoring` configures the libobs source, but the headless product image does not promise a host monitoring device.

Composite 模式把五个字段全部应用到 libobs 来源。音轨 1 是 M5 节目轨：WHIP/WHEP 使用 96 kbps Opus，最终 MP4 使用 128 kbps AAC、48 kHz 双声道。分配到音轨 2 至 6 的来源不会进入这两个 M5 节目输出，留待后续多输出能力使用；`audioTrack` 不会拆分浏览器端唯一的 Direct 输出。`monitoring` 会配置 libobs 来源，但无头产品镜像不承诺存在主机监听设备。

## Migration / 迁移

The loader accepts schema v0, v1, and v2. Migration preserves the existing revision (or initializes revision zero for v0), assigns `syncOffsetMs: 0`, `monitoring: "off"`, and `audioTrack: 1` to every legacy source, validates the full v3 document, and atomically rewrites it with mode `0600`. Future versions are rejected without modifying the file.

加载器接受 schema v0、v1 和 v2。迁移会保留既有 revision（v0 初始化为 0），为每个旧来源设置 `syncOffsetMs: 0`、`monitoring: "off"` 和 `audioTrack: 1`，完整校验 v3 文档后以 `0600` 权限原子回写。未来版本会被拒绝且不会修改文件。

All v2 browser URL policy, redaction, limits, lifecycle, and cache rules remain unchanged; see [schema v2](scene-schema-v2.md) for those historical additions.

v2 的浏览器 URL 策略、脱敏、边界、生命周期和缓存规则均保持不变；这些历史新增项见 [schema v2](scene-schema-v2.md)。

# Scene document schema v1 / 场景文档 v1

M1 uses one versioned scene document as the source of truth for the Web UI, control API, persistence layer, and libobs runtime. No component maintains a second layout model.

M1 使用同一份带版本场景文档驱动 Web UI、控制 API、持久化层和 libobs 运行时，任何组件都不维护第二套布局模型。

## Shape / 结构

```json
{
  "schemaVersion": 1,
  "revision": 0,
  "id": "main",
  "name": "Main Wall",
  "canvas": {
    "width": 1920,
    "height": 1080,
    "backgroundColor": "#000000"
  },
  "sources": [
    {
      "id": "camera-front",
      "kind": "rtsp",
      "name": "Front Camera",
      "rtspUrl": "rtsp://camera.invalid/stream",
      "transport": "tcp",
      "muted": true,
      "volume": 1.0
    }
  ],
  "items": [
    {
      "id": "item-front",
      "sourceId": "camera-front",
      "x": 0,
      "y": 0,
      "width": 960,
      "height": 540,
      "scaleMode": "contain",
      "crop": { "top": 0, "right": 0, "bottom": 0, "left": 0 },
      "zIndex": 0,
      "visible": true
    }
  ]
}
```

`revision` is the future optimistic-concurrency token. Every accepted mutation will advance it exactly once. `zIndex` values are unique and contiguous from zero, so serialization and libobs ordering remain deterministic.

`revision` 是后续乐观并发控制令牌，每次成功变更只递增一次。`zIndex` 必须从零开始连续且唯一，从而保证序列化和 libobs 层级顺序确定。

## Validation limits / 校验边界

- JSON input is limited to 1 MiB and duplicate or unknown keys are rejected.
- A scene contains at most 64 sources and 256 items.
- IDs contain only ASCII letters, digits, `.`, `_`, and `-`, with a maximum of 64 bytes.
- Canvas dimensions are even values from 16 through 8192; item dimensions and crop values are bounded.
- The M1 background is black; item `scaleMode` is `contain`, `cover`, or `stretch`.
- Every item references an existing source, and source/item IDs are unique.
- M1 accepts only RTSP/RTSPS sources and `tcp` or `udp` transport.
- Volume is finite and between 0 and 1.

- JSON 输入最大 1 MiB，重复 key 和未知字段都会被拒绝。
- 单场景最多 64 个来源、256 个场景项。
- ID 只允许 ASCII 字母、数字、`.`、`_`、`-`，最长 64 字节。
- 画布尺寸必须是 16 到 8192 的偶数；场景项尺寸与裁切值均有边界。
- M1 背景固定为黑色；场景项 `scaleMode` 可选 `contain`、`cover` 或 `stretch`。
- 每个场景项必须引用已存在来源，来源 ID 与场景项 ID 各自唯一。
- M1 仅接受 RTSP/RTSPS 来源以及 `tcp`、`udp` 传输。
- 音量必须是 0 到 1 的有限数值。

## Credential boundary / 凭据边界

The persistence view contains the complete RTSP URL because libobs needs it to connect. It is local secret material and must never be committed, logged, or returned unchanged by an API. The public/API view applies the shared RTSP credential redactor before serialization. Validation and parse errors identify fields only and never echo input values.

持久化视图包含 libobs 建连所需的完整 RTSP URL，因此属于本地秘密材料，不得提交、写入日志或由 API 原样返回。公开/API 视图在序列化前使用统一 RTSP 凭据脱敏器；校验和解析错误只标识字段，不回显输入值。

## Persistence and migration / 持久化与迁移

The canonical file is stored in the private `/config/webobs` volume. A save writes a mode `0600` temporary file in the same directory, synchronizes it, atomically renames it over the prior document, and then synchronizes the mode `0700` directory. The loader rejects symlinks, non-regular files, files owned by another user, additional hard links, and content larger than 1 MiB. Errors never contain scene content.

规范场景文件位于私有 `/config/webobs` 卷。保存时先在同目录写入权限为 `0600` 的临时文件，完成同步后原子重命名覆盖旧文档，最后同步权限为 `0700` 的目录。加载器拒绝符号链接、非普通文件、其他用户拥有的文件、额外硬链接以及超过 1 MiB 的内容；错误消息不包含场景内容。

The only historical format accepted by M1 is the explicitly marked pre-release `schemaVersion: 0` document. It has the same fields as v1 except that `revision` is absent. A successful load validates the complete migrated document, initializes `revision` to zero, and immediately rewrites it as v1 through the same atomic path. Unversioned, malformed, and future-version documents are rejected without rewriting.

M1 仅接受明确标记的预发布 `schemaVersion: 0` 历史文档，其字段与 v1 相同，但不包含 `revision`。加载成功时会完整校验迁移结果，将 `revision` 初始化为零，并立即通过同一原子路径回写为 v1；无版本、损坏和未来版本文档会被拒绝且不改写。

API-driven live mutation and transactional persistence/runtime commit are subsequent M1 batches built on this storage contract.

API 驱动的实时变更以及持久化/运行时事务提交将在后续 M1 批次基于此存储契约实现。

## Runtime bootstrap / 运行时引导

`--scene-file` or `WEBOBS_SCENE_FILE` selects the canonical absolute JSON path. When it exists, `webobsd` loads it and ignores the bootstrap URL. When it is absent, `--rtsp-url` or `WEBOBS_RTSP_URL` creates a one-camera `contain` scene and atomically saves it. The libobs runtime creates every declared RTSP source, applies transforms, crop, ordering, visibility, mute, and volume, and starts recording once at least one visible source is ready. A timed-out secondary source remains a black tile rather than stopping the whole wall.

`--scene-file` 或 `WEBOBS_SCENE_FILE` 用于指定规范场景 JSON 的绝对路径。文件存在时，`webobsd` 加载它并忽略引导 URL；文件不存在时，使用 `--rtsp-url` 或 `WEBOBS_RTSP_URL` 创建单摄像头 `contain` 场景并原子保存。libobs 运行时会创建全部 RTSP 来源，应用变换、裁切、层级、可见性、静音和音量；至少一个可见来源就绪后开始录制，超时的次要来源保留黑色占位而不会停止整面监控墙。

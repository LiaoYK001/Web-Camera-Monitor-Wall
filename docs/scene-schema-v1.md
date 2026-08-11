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
- Every item references an existing source, and source/item IDs are unique.
- M1 accepts only RTSP/RTSPS sources and `tcp` or `udp` transport.
- Volume is finite and between 0 and 1.

- JSON 输入最大 1 MiB，重复 key 和未知字段都会被拒绝。
- 单场景最多 64 个来源、256 个场景项。
- ID 只允许 ASCII 字母、数字、`.`、`_`、`-`，最长 64 字节。
- 画布尺寸必须是 16 到 8192 的偶数；场景项尺寸与裁切值均有边界。
- 每个场景项必须引用已存在来源，来源 ID 与场景项 ID 各自唯一。
- M1 仅接受 RTSP/RTSPS 来源以及 `tcp`、`udp` 传输。
- 音量必须是 0 到 1 的有限数值。

## Credential boundary / 凭据边界

The persistence view contains the complete RTSP URL because libobs needs it to connect. It is local secret material and must never be committed, logged, or returned unchanged by an API. The public/API view applies the shared RTSP credential redactor before serialization. Validation and parse errors identify fields only and never echo input values.

持久化视图包含 libobs 建连所需的完整 RTSP URL，因此属于本地秘密材料，不得提交、写入日志或由 API 原样返回。公开/API 视图在序列化前使用统一 RTSP 凭据脱敏器；校验和解析错误只标识字段，不回显输入值。

Atomic persistence, migration, restrictive file permissions, and API mutation semantics are subsequent M1 batches built on this contract.

原子持久化、版本迁移、严格文件权限和 API 变更语义将在后续 M1 批次基于此契约实现。

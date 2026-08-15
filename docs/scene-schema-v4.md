# Scene document schema v4 / 场景文档 v4

Schema v4 is the current libobs, persistence, REST/WebSocket, Studio editor, and playback-capability contract. It retains all v3 audio fields and adds the bounded Canvas Studio model. The separate Studio collection document has `schemaVersion: 1` and owns ordered named scenes plus Program/Preview state.

场景 schema v4 是当前 libobs、持久化、REST/WebSocket、Studio 编辑器和播放能力分析共用的契约。它保留 v3 的全部音频字段，并加入有边界的画布工作台模型。独立的 Studio 集合使用 `schemaVersion: 1`，保存有序命名场景以及 Program/Preview 状态。

## Scene sources / 场景来源

Every source keeps the common `id`, `kind`, `name`, `muted`, `volume`, `syncOffsetMs`, `monitoring`, `audioTrack`, and ordered `filters` fields. Supported kinds are:

- `rtsp`: `rtspUrl`, `transport` (`tcp` or `udp`);
- `browser`: `url`, dimensions, FPS, CSS, and bounded lifecycle flags;
- `image` and `media`: `filePath` under `/assets/` or `/recordings/`; media also has `loop`;
- `text`: UTF-8 `text` and `#RRGGBB` `color`;
- `color`: `#RRGGBB` `color`;
- `nested`: a `sceneId` in the same Studio collection.

每个来源都保留公共字段，并支持 RTSP、受控网页、图片、媒体、文字、色块和嵌套场景。素材路径只能位于容器内只读 `/assets/` 或受控 `/recordings/`；嵌套只能引用同一集合中的场景。

Filters execute in array order. The supported subset is `crop-pad`, `opacity`, `color-correction`, `mask-blend`, `lut`, `scaling`, and `delay`, with at most 16 filters per source. LUT and mask values must be absolute `/assets/` or `/recordings/` paths. Scaling uses bounded `WIDTHxHEIGHT`; paths, shell fragments, and arbitrary plug-in identifiers are rejected.

滤镜严格按数组顺序执行，每路最多 16 个。LUT 与遮罩只能读取受控素材路径；缩放参数必须是有界 `WIDTHxHEIGHT`，任意宿主路径、命令片段和任意插件标识都会被拒绝。

## Items and canvas / 布局项与画布

Each item references one source and contains integer position/size, contiguous `zIndex`, visibility, lock state, `groupId`, crop, `contain|cover|stretch`, finite rotation, opacity from 0 through 1, and `normal|add|multiply|screen` blend mode. Groups are editor selection/transform units; source ownership remains explicit. The canvas remains even-sized from 16 through 8192 pixels with a `#RRGGBB` background.

每个布局项引用一路来源，并包含位置尺寸、连续层级、可见性、锁定、逻辑分组、裁切、缩放模式、旋转、透明度和混合模式。分组用于编辑器整组选择与变换，不改变来源所有权。

## Studio collection / Studio 集合

```json
{
  "schemaVersion": 1,
  "revision": 12,
  "programSceneId": "wall",
  "previewSceneId": "incident",
  "transition": {"kind": "fade", "durationMs": 350},
  "scenes": []
}
```

Collections contain 1–64 uniquely identified v4 scenes. Nested references are acyclic and at most two levels deep. `Cut` or `Fade` Take first prepares and verifies the complete Preview runtime, then swaps Program atomically; saving Preview never mutates the active Program. Taking the same scene ID is meaningful because its saved definition may have changed. Undo/redo is bounded and persisted results remain protected with mode `0600`.

集合包含 1–64 个唯一命名的 v4 场景。嵌套引用禁止成环且最多两层。保存 Preview 不会修改活动 Program；Take 会先完整准备并验证 Preview 运行图，再原子切换 Program。即使两个总线引用同一场景 ID，重新 Take 仍会应用其已保存的新定义。

## Direct/Hybrid capability / 播放能力降级

`GET /api/v1/studio/capabilities` evaluates every scene for Direct and Hybrid rendering. Non-RTSP sources, ordered filters, rotation, item opacity, and advanced blend modes explicitly report their reasons and select Composite or Hybrid fallback. The response contains scene/source IDs already present in public documents, but no RTSP/browser secret, internal MediaMTX path, or filesystem content.

能力接口逐场景分析 Direct 与 Hybrid。非 RTSP 来源、有序滤镜、旋转、布局项透明度和高级混合会明确说明原因并选择 Composite 或 Hybrid 回退；响应不会包含来源凭据、内部媒体路由或文件内容。

## Migration and secret handling / 迁移与秘密处理

The loader accepts v0–v3, preserves the exact pre-v4 bytes once as `<scene>.pre-v4.backup` with mode `0600`, adds safe defaults, validates the full v4 result, and atomically rewrites the active scene. Invalid or future schemas do not modify either file. Studio and scene public JSON redact RTSP userinfo and browser query/fragment secrets; masked values can only retain an unchanged existing secret.

加载器接受 v0–v3，并在首次迁移前以 `0600` 权限把原始字节完整保存为 `<scene>.pre-v4.backup`，随后补齐安全默认值、完整校验并原子回写。无效或未来版本不会修改文件。公开 JSON 会隐藏 RTSP userinfo 及浏览器查询/片段秘密；脱敏占位符只能保留同一既有来源的未变秘密。

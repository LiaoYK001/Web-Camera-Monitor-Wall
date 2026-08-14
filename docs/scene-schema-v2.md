# Scene document schema v2 / 场景文档 v2

Schema v2 is the single scene contract used by persistence, the REST/WebSocket API, the Web editor, and the libobs runtime. It adds an explicitly discriminated `browser` source while retaining `rtsp` sources and the v1 layout model.

场景 schema v2 是持久化、REST/WebSocket API、Web 编辑器和 libobs 运行时共用的唯一契约。它在保留 RTSP 来源及 v1 布局模型的同时，新增了显式区分的 `browser` 来源。

## Source shapes / 来源结构

An RTSP source keeps the v1 fields:

```json
{
  "id": "camera-front",
  "kind": "rtsp",
  "name": "Front Camera",
  "rtspUrl": "rtsp://camera.invalid/stream",
  "transport": "tcp",
  "muted": true,
  "volume": 1.0
}
```

A browser source uses an HTTP(S) page rendered by the pinned `obs-browser`/CEF runtime:

```json
{
  "id": "operations-dashboard",
  "kind": "browser",
  "name": "Operations Dashboard",
  "url": "https://dashboard.example/wall",
  "width": 1280,
  "height": 720,
  "fps": 30,
  "customCss": "body { overflow: hidden; }",
  "shutdownWhenHidden": true,
  "restartWhenActive": true,
  "muted": true,
  "volume": 1.0
}
```

Both kinds are referenced by unchanged scene items containing position, size, scale mode, crop, z-index, and visibility. A scene has at most 64 total sources, 8 browser sources, and 256 items. Browser width and height are 16–8192, FPS is 1–60, and custom CSS is limited to 32 KiB. Unknown or cross-kind fields are rejected.

两类来源都由未改变的场景项引用，场景项继续描述位置、尺寸、缩放模式、裁切、层级和可见性。单场景最多包含 64 个来源、其中最多 8 个浏览器源，以及 256 个场景项。浏览器宽高范围为 16–8192，帧率为 1–60，自定义 CSS 最大 32 KiB；未知字段或跨类型字段会被拒绝。

## Browser security boundary / 浏览器安全边界

Browser sources are denied by default. Every page origin must exactly match one entry in `WEBOBS_BROWSER_ALLOWED_ORIGINS`; entries are comma-separated origins without credentials, paths, queries, or fragments. Localhost, single-label names, private/link-local addresses, and DNS answers pointing to non-public addresses additionally require `WEBOBS_BROWSER_ALLOW_PRIVATE_NETWORKS=true`.

浏览器源默认拒绝。每个页面 Origin 必须精确命中 `WEBOBS_BROWSER_ALLOWED_ORIGINS` 中的一项；该变量是逗号分隔且不含凭据、路径、查询或片段的 Origin 列表。localhost、单标签主机名、私网/链路本地地址以及解析到非公网地址的 DNS 结果，还必须显式设置 `WEBOBS_BROWSER_ALLOW_PRIVATE_NETWORKS=true`。

The allowlist is an administrator trust boundary, not a page-content sandbox: an approved page can load its own subresources. Approve only pages controlled by trusted operators, and do not expose the unauthenticated control plane outside host loopback before M6.

允许列表是管理员信任边界，不是网页内容沙箱：获准页面仍可加载自身子资源。只批准可信运维方控制的页面；M6 之前不得把无认证控制面暴露到主机回环以外。

HTTP URL userinfo is rejected. Persistence retains query and fragment values when a dashboard needs them, but the public API replaces them with `?***` and `#***`. An unchanged placeholder restores only the same existing source's stored value; a new source or changed endpoint must submit the complete URL. Product logs apply the same query/fragment and userinfo filtering.

HTTP URL 中的 userinfo 会被拒绝。仪表盘确有需要时，持久化文件会保留查询和片段值，但公开 API 会将其替换为 `?***` 与 `#***`。未改变的占位符只会恢复同一既有来源的已存值；新增来源或改变端点必须提交完整 URL。产品日志也应用相同的查询、片段和 userinfo 过滤。

## Runtime lifecycle / 运行时生命周期

The product image pins CEF 6533 revision 6 by filename and SHA-256, applies a source-reviewed headless patch to OBS 32.1.2, limits CEF renderer processes to four, and treats `obs-browser` as a required module. Hidden sources can release their browser and restart on activation. A terminated renderer is reloaded automatically. The browser profile under `/config/obs/plugin_config/obs-browser` uses mode `0700` and is removed before startup and after every graceful exit; an ungraceful exit is cleaned on the next start.

产品镜像按文件名和 SHA-256 固定 CEF 6533 revision 6，对 OBS 32.1.2 应用经审阅的无头补丁，并把 CEF renderer 限制为 4 个进程，同时将 `obs-browser` 作为必需模块。隐藏来源可释放浏览器，并在再次激活时重启；renderer 异常终止后会自动重新加载。`/config/obs/plugin_config/obs-browser` 下的浏览器 profile 权限为 `0700`，每次启动前和正常退出后都会删除；非正常退出留下的内容会在下次启动时清理。

## Migration / 迁移

The loader accepts schema v1 and migrates it to v2 without changing its revision; all v1 sources remain `rtsp`. The pre-release schema v0 format first gains revision zero and is then migrated to v2. Successful migrations are immediately rewritten through the existing atomic, private scene-store path. Future versions are rejected without modifying the file.

加载器接受 schema v1，并在不改变 revision 的前提下迁移到 v2；所有 v1 来源仍为 `rtsp`。预发布 schema v0 会先补充 revision 0，再迁移到 v2。迁移成功后立即通过既有的私有原子存储路径回写；未来版本会被拒绝且不会修改文件。

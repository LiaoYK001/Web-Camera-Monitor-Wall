# Scene document schema v6 / 场景文档 v6

Schema v6 preserves the [v5 source and canvas model](scene-schema-v5.md) and adds optional per-source `audioInputs`. Core emits v6 and accepts v5. The input track indices are independent of the legacy OBS output mixer slot `audioTrack` (1–6); a save must not derive or reset that slot from input indices.

Schema v6 保留 v5 的来源和画布模型，增加可选的逐来源 `audioInputs`。Core 输出 v6 并兼容 v5；输入音轨索引与旧 OBS 输出 mixer 槽位 `audioTrack`（1–6）独立，保存时不能从输入索引推导或重置输出槽位。

```json
{
  "audioTrack": 6,
  "audioInputs": [
    { "track": 0, "gain": 0.4, "muted": false, "syncOffsetMs": -120 },
    { "track": 31, "gain": 0.8, "muted": true }
  ]
}
```

An explicit array holds at most eight unique integer `track` indices from 0 through 31. Every entry contains finite `gain` in 0–1 and boolean `muted`; optional integer `syncOffsetMs` is bounded to ±10,000 ms. Other entry fields, duplicate indices, booleans used as numbers, non-finite values and out-of-range values are rejected.

显式数组最多八个条目；`track` 是 0–31 的不重复整数，`gain` 为 0–1 的有限数，`muted` 为布尔值，可选整数 `syncOffsetMs` 为 ±10,000 毫秒。未知字段、重复索引、以布尔值代替数字、非有限数或越界值均被拒绝。

Omitting `audioInputs` preserves the existing legacy routing fallback. An explicit `audioInputs: []` selects no input audio. Preserve this distinction through profiles, offline snapshots, synchronization and local editing. These data contracts alone do not establish physical multi-track camera or output playback qualification.

省略 `audioInputs` 保留旧版路由回退；显式 `audioInputs: []` 表示不选择输入音频。配置、离线快照、同步与本地编辑都必须保留这一差异；数据契约验证本身不代表真实摄像机多音轨或输出播放已验收。

## Device synchronization / 设备同步

Queues hold at most 256 mutations and requests submit at most 64 each, stopping on a conflict or failure. All scene mutations stay together to preserve the nested graph's transaction boundary; if more than 64 scene mutations accumulate, the module retains them and asks the operator to reduce the simultaneous scene replacement/deletion. Incomplete or mismatched acknowledgements are rejected without clearing pending data.

队列最多 256 项，每次提交最多 64 项，遇到冲突或失败即停止。所有场景修改位于同一批次以保留嵌套图的事务边界；积累超过 64 项场景修改时保留本机内容，并提示减少同时替换或删除的场景。响应缺项或与本次请求不匹配时拒绝确认，保留待提交内容。

The v2 service accepts the safe shared-scene subset in both v5 and v6. Its batch envelope remains schema v1 and its existing browser/native grant contract versions remain unchanged. New synchronized scenes use v6; an existing v5 scene keeps v5 until explicit input selections are saved, and v6 is never downgraded. SQLite stores the actual scene version. Audio selections remain part of the `sources` conflict field, so simultaneous incompatible edits require an explicit choice. Camera/Profile authorization, nested graph bounds and the credential-free synchronization boundary still apply.

v2 服务接受 v5/v6 的安全共享场景子集；批次仍为 schema v1，浏览器与原生授权契约版本保持一致。新同步场景采用 v6；既有 v5 在保存显式音轨选择后升级，v6 不降级；SQLite 记录实际版本。音轨选择属于 `sources` 冲突字段，不兼容的并发修改必须明确选择；设备授权、嵌套图边界和无凭据同步边界继续生效。

The WebUI synchronization module encrypts pending changes, serializes queue writes across supporting browser windows, and coalesces simultaneous sync calls. Each network request has a 15-second timeout. Acknowledgements remove only matching submitted mutations; later saves and unsubmitted edits remain queued, and incoming snapshots do not overwrite pending local scenes. Failed requests retain the queue; conflict state survives a failed follow-up pull and reload. Choosing the server discards only conflicting documents, preserving unrelated queued edits. Choosing local explicitly rebases the remaining queue. Studio device-mode saving now writes the layout and queue atomically, restores them after refresh and exposes explicit conflict choices in Settings. This is separate from the core Program collection: use the deliberate Preview copy described in [offline workspaces](offline-workspace.md). The separate Qt product retains audio settings while editing geometry or saving its local scene; its audio UI and media pipeline are not expanded by this contract change.

WebUI 同步模块对待提交内容加密，在支持浏览器锁的窗口间串行修改队列，并合并同时发起的同步。每次网络请求超时为 15 秒；响应只确认匹配的已提交 mutation，之后的新保存与尚未提交的编辑继续排队，服务端快照不覆盖待提交本地场景。失败保留队列；后续拉取失败或刷新后也保留冲突。采用服务端只丢弃冲突文档，保留无关待提交编辑；保留本地明确重设队列基础版本。Studio 设备模式现已原子保存布局与队列，刷新后恢复，设置中明确选择冲突版本。设备文档独立于 core Program；按[离线工作区说明](offline-workspace.md)明确复制到 Preview。独立 Qt 产品在移动画布与本地保存时保留音频设置，本次不扩展其音频界面或媒体管线。

# Studio runtime identities / 场景运行标识

Scene definitions retain their original IDs. Explicit TAKE flattens the chosen
Scene for the frozen Program; saving/reordering Preview alone does not replace
Program or its account controls.

场景定义保留原始 ID。明确执行 TAKE 时才展开选定场景并冻结为 Program；仅保存或
调整 Preview 层级不会替换 Program，也不会迁移账号控制设置。

Runtime source and item IDs no longer depend on traversal counters. Unambiguous
short root IDs retain `scene.source` / `scene.item`. Long or dotted components use
`source-` / `item-` plus 224 bits of SHA-256 over the kind and length-framed immutable
ID components, within the existing 64-character contract. Layer, position, display
name and audio edits do not enter the digest. Literal dots cannot impersonate
namespace separators. Linux and Windows use the same algorithm and shared tests.

运行来源和画布项标识不再依赖遍历序号。无歧义的短根标识保持 `scene.source` /
`scene.item`；较长或含点的组件使用 `source-` / `item-` 加 SHA-256 的 224 位摘要，
输入为类型和带长度的不变 ID 组件，符合现有 64 字符限制。层级、位置、显示名称和
声音参数不参与摘要；组件内的点不会混淆命名空间。Linux / Windows 使用同一算法与测试。

Identical serialized sources still share one runtime source within a flattened
Scene. A prepass selects the smallest length-framed source namespace for each
group, independently of layer order. Changing configurations can intentionally split
or merge a group. Nested item identity also includes each parent item instance, so
placing one child Scene twice creates distinct canvas items without duplicate
source connections. Existing nested item IDs consequently change once on TAKE.
Expansion stops at the existing 256-item / 64-source limits; identifier collisions
reject TAKE instead of assigning an order-dependent fallback.

同一展开场景中完全相同的序列化来源仍只建立一个运行来源。预处理为每组选择最小
带长度的来源命名空间，与层级顺序无关；修改配置可以明确拆分或合并复用组。
嵌套画布项标识另包含父项实例，因此重复放置同一子场景产生独立画布项并共享来源
连接；原有嵌套项标识会在下次 TAKE 时变更一次。展开保持 256 项 / 64 来源边界；
标识冲突拒绝 TAKE，不使用取决于顺序的备用序号。

## Existing preferences / 已有偏好

Account records and saved Program snapshots remain intact during upgrade. The next
explicit TAKE generates stable identities. Previous `source-N` / `item-N` counters
and ambiguous dotted paths cannot reliably identify a camera across Scenes, so
their account preferences are retained without automatic reassignment. Review the
source volume, mute, local monitoring and display controls after that TAKE and save
the desired settings again. Existing unambiguous short root IDs keep their settings.
This does not migrate fixed-Scene projectors' original IDs into Program identities.

升级保留账号记录与冻结的 Program 快照。下次明确 TAKE 才生成稳定标识。旧
`source-N` / `item-N` 序号及有歧义的含点路径不能可靠对应跨场景摄像机，因此保留
记录而不自动转移设置。该次 TAKE 后，请核对来源音量、静音、本地监听和显示设置，
重新保存需要的值；无歧义的短根标识继续沿用已有设置。本改动不把固定场景投影的
原始 ID 迁移为 Program 标识。

## Verification / 验证

`core/tests/studio_identity_tests.hpp` runs in both unit binaries. It covers UUID
layer changes, Scene isolation, rename/audio edits, repeated nested instances,
deduplicated aliases and dotted components. `tests/studio_identity_runtime.cjs`
uses authenticated TAKE, account writes, actual production UI controls and normal
container restart with an isolated profile. Supply a complete image and optionally
`--core <fresh Linux webobsd>`; this overlay is not a complete image rebuild.
The Windows native service and entry gates reuse the actual API fixture, with
normal service restart and renderer checks respectively. Color sources exercise
control identity; they do not qualify physical camera/audio playback.

`tests/monitor_preference_recovery.cjs --core <fresh Linux webobsd> --uuid-scene`
also exercises real go2rtc RTSP import and MediaMTX H.264 Direct decoding through
a long namespaced source identity, along with the account recovery controls.

`tests/monitor_preference_recovery.cjs --core <新编译的 Linux webobsd> --uuid-scene`
另验证较长来源命名空间下的真实 go2rtc RTSP 导入、MediaMTX H.264 Direct 解码与
账号恢复控制；媒体由 FFmpeg 合成，不等于实体摄像机验收。

共享 C++ 用例覆盖 UUID 层级变更、场景隔离、改名/声音编辑、重复嵌套、复用别名与
含点组件。Linux 实际运行检查使用认证 TAKE、账号保存、生产页面控制与正常重启；
完整镜像可另挂载新编译 Core，但此方式不等于完整镜像重建。Windows 原生服务与
主入口门禁复用实际 API 用例，分别验证正常停启和渲染控制。色块来源验证标识逻辑，
不等于实体摄像机或声音播放验收。

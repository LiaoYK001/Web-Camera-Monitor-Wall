# 旧配置只读迁移预检 / Read-only legacy migration preflight

## 范围 / Scope

[legacy_import.py](../native-host/scripts/legacy_import.py) 仅接收操作者显式导出的一个 JSON 文件，生成一个新的、去除敏感内容的规划报告。它不扫描用户配置目录，不打开或升级数据库，不解密 DPAPI，不连接摄像机或网络，不修改 OBS graph、账号或原始文件，没有 `--apply` 模式。Electron 产品仍为默认入口。

The tool accepts one explicitly exported scene JSON (schema 5/6), or studio envelope (schema 1) containing those scenes. It never discovers profiles, opens account/camera databases, decrypts credentials, initializes media, connects to a camera, or applies a migration. A report is a plan, not an importable native configuration or a compatibility qualification.

## 保守规划契约 / Conservative planning contract

- 正向候选仅限经过字段、类型、范围与引用检查的普通 RTSP 场景；单文件上限 1 MiB，最多 64 个场景、每场景 64 个 source 和 256 个 item。未知顶层/RTSP 字段、重复 JSON key、重复 ID、无效引用、NaN/Infinity、非连续 zIndex 会被拒绝。对本来就不支持的 source 分支不做完整旧 schema 验证，而是保留 ID 映射并阻止后续应用，不能把它当成旧产品的完整校验器。
- 不按 URL 或名称合并相机。稳定的 scene/source/item ID 映射由固定 UUID namespace 和带类型、scene scope 的旧 ID 确定；相同 URL 的不同 source 保持不同 ID。改名、换 URL、调层序不会改变该对象映射。输出 legacy identity hash 是可关联的伪名，不是加密或完整匿名化保证。
- Program 与 Preview 分开映射；报告不会触发 TAKE。报告保留可解释的画布、布局、crop、可见性、层序及音量/延时/输出总线信息；不是把这些属性已经写入原生 OBS 的声明。
- 非 RTSP source、任意 filter（包括 disabled filter）、非黑背景、group/rotation/opacity/blend 等高级 item 会产生阻断项，不会静默丢弃。显式非空 `audioInputs` 即使只有一路，也需要已有网关混音语义，当前阻断；显式空列表保留为静音，缺省保留为 legacy 选择。`audioTrack` 是 OBS 输出总线，不是输入媒体流的 track 选择。
- 导出文档未包含硬解与连接超时的运行配置，因此必须明确给出 `--hardware-decode on|off` 和 `--connect-timeout-seconds 1..300` 才能得到候选；缺少时只输出 blocked 报告，不猜默认值。这只是记录迁移意图：当前原生 bootstrap 没有实现该超时设置，工具不会声称它已经生效。
- 报告仅重新构造白名单字段，不写出 URL、用户名、密码、相机/场景名称、原始 ID、输入路径或未知对象。账号、会话、内部 token、camera registry、私钥及媒体文件完全排除，不能用这份报告替代私密迁移包。

IDs are scoped by object type and legacy scene identity, not a URL hash. Unsupported features block the whole candidate; they are not silently dropped. Positive candidates still require an authorized adapter to reproduce every property and enforce graph-derived camera permissions before any reversible apply operation exists.

## 文件安全 / Filesystem safety

输入与报告均须为绝对路径。拒绝 `..`、symlink/reparse ancestor、非普通文件、多硬链接、过大文件和读取中发生的变化。POSIX 逐级持有目录 fd 并通过 `O_NOFOLLOW` 打开最终文件。Windows 逐级持有禁止写入/重命名共享的目录 handle；最终输入使用 `CreateFileW(FILE_FLAG_OPEN_REPARSE_POINT)`，在任何读取前根据 handle 检查普通磁盘文件、属性、链接数与大小，再交给 CRT。UNC、ADS 和尾随点/空格路径被拒绝。

报告必须位于导出文件所在目录树之外的现有目录，使用 exclusive-create，绝不覆盖已有文件。POSIX 新报告权限为 `0600`；Windows 继承输出目录 ACL，不声称由此设置了 owner-only ACL。路径/变更检查不能抵抗拥有同一用户权限或管理员权限的恶意进程，也不是磁盘快照或事务一致性证明；输出目录应由操作者选择为私密目录。写入失败可能留下不完整的新报告，此时需另选新报告路径重试，不会覆盖旧文件。

The Windows final-component guard is a no-follow open, not a follow-then-reject check. A deterministic replacement-race regression accompanies the static symlink/hardlink and ancestor-junction tests. These guards do not provide a security boundary against an administrator or a process with equivalent filesystem authority.

## 使用 / Usage

从旧产品显式导出 scene 或 studio JSON，再选择不同的私密报告目录。以下路径仅为示例，不读取实际用户目录：

```sh
python3 -B native-host/scripts/legacy_import.py \
  --input /private/export/scene.json \
  --report /private/reports/preflight-001.json \
  --hardware-decode on --connect-timeout-seconds 10
```

Windows 使用 Python 与相应绝对路径。退出码 `0` 表示规划候选，`4` 表示存在阻断项，`2` 表示输入/路径/参数拒绝。所有报告均为 `dryRun=true`、`applied=false`、`qualified=false`；不应根据 `candidate` 自动创建/替换场景或切换默认产品。stdout 只输出状态，错误诊断不回显私密输入或参数值。

## 验证与下一步 / Validation and next step

[测试](../native-host/tests/test_legacy_import.py) 使用临时合成文档，覆盖 schema 5/6 与 studio 1、同 URL 不同 ID、Program/Preview、音频语义、阻断、隐私投影、只读输入、exclusive report、链接/目录链接、最终分量替换竞态及 CLI 参数隐私。不读取真实用户配置。Linux/MSVC 工作流分别运行同一 Python 套件；实际 Windows 结果应以对应 CI run 为准，不以 Fedora 测试代替。

下一阶段先建立私密源数据持有者与完整映射/能力契约，再实现需确认的 copy-on-write 应用、独立目标配置、预先快照、逐字段验证与回滚；不得直接把安全报告当作包含凭据的原生 product 配置。账号数据库/会话不进行隐式搬迁或复用。

Next: design the private-data owner and fully authorized, reversible copy-on-write apply adapter. Keep credentials out of public receipts; preserve the original export and compatibility product until the native result is explicitly verified.

## 下一阶段候选：离线私密暂存 / Next candidate: offline private staging

以下是固定上游源码审查形成的**未实现、未验证方案**，不是现有 CLI 功能或已可导入的包格式。先做显式新目录中的离线转换/校验，不能先接入正在运行的宿主来测试“导入”。

- **私密输入所有者**：重新安全读取操作者明确选择的一个原始导出文件，在一次调用内持有不可变副本并记录私密指纹。公开报告不含 URL/名称，不能成为转换输入；不扫描 registry、账号或用户配置，不从 URL 猜相机所有权。
- **刻意缩小能力**：初始只考虑单 scene schema 5/6、黑画布、平面 RTSP、contain/零 crop/零 rotation/普通 blend/opacity=1，保留位置、尺寸、层序、共享 source、可见/锁定。非空或缺省 audioInputs、monitoring 非 off、studio envelope、filters、assets 及任何未支持字段应整单阻断；初始仅支持显式 audioInputs=[] 的有效静音，须同时禁止输出与监听，不把音量零当成静音语义。不能通过固定五分屏函数丢弃布局或偷偷选择场景。
- **身份与序列化**：scene/source 使用稳定 UUID；OBS scene item 使用独立的**正 int64 ID**，不是规划报告的 item UUID。零 ID 会触发上游重新分配。私密 manifest 保留对应关系，逐 scene 检查 item ID 唯一及碰撞，并保证 id_counter 不小于最大 item ID、严格小于 INT64_MAX，对后续自动分配预留余量并检查溢出；全部 source_uuid 必须唯一解析且 companion name 匹配，不依赖 OBS 的名称回退。重复名称规则必须显式，不按名称或 URL 合并。
- **画布不是 profile**：可研究 version=1、无顶层 resolution 的 absolute-coordinate collection，并通过 custom_size/cx/cy 表达独立 scene 尺寸；必须有固定版本真实 save/load fixture。它不设置宿主全局 BaseCX/BaseCY、输出尺寸或 FPS，这些应保留为“目标要求、未应用”，不猜导出中不存在的 profile 配置。硬解/transport/timeout 只序列化明确有界的设置意图，不声称硬解或网络行为已验收。
- **秘密与事务**：只写输入树/现有用户配置树之外显式选择的全新私密目录；POSIX 目录0700/文件0600，Windows 必须验证或建立限制性 owner DACL，继承 ACL 不足时在写入秘密前拒绝。先在内存构造并独立校验，exclusive 写入、flush/fsync、安全 reopen/readback/逐字段比对，所有成员及目录持久化并完成比对后，最后以 exclusive/原子方式发布 completion marker；读取端仍需重验完整 manifest 和成员。marker 不构成跨文件原子性、授权或免重验凭证。标记之前崩溃不算完成；清理/回滚仅针对这次明确拥有的新路径，不覆盖或清理既有文件。公开回执只含固定状态/阻断项，applied=false、qualified=false；路径、名称、URL、私密指纹及完整 manifest 不进入日志/公开输出。
- **分级证明**：独立解码器应比较输入与输出的全部支持字段，逐项篡改/删除输出必须失败；测试同 URL 不同 ID、同 source 多 item、隐藏/锁定/重排、引用/名称歧义、拒绝不支持特性，以及每个写入/同步/读回/崩溃阶段。真实 libobs 结构 roundtrip 只注册测试惰性 source，不加载 ffmpeg/camera；API double 或 serializer 自我 roundtrip 不能证明上游 JSON loader。真实 frontend 导入、媒体行为和经授权应用仍为独立门槛。
- **禁止隐式 live apply**：前端 collection loader 会选择/切换场景并修改配置；ffmpeg source 初始化还可能连接和记录完整 input。不得用当前宿主或真实媒体来做“纯离线验证”。生成的 legacy UUID/manifest 不是 registry 权限；真实应用仍需可信 owner binding、不可变账号身份/权限 epoch、全部受影响 camera scope、目标 revision 重验、独立 replacement、逐字段验证、旧 graph/profile/selection/audio 快照与回滚，且不隐式 TAKE。

Pinned source anchors (review only): [source serialization](../obs/obs-studio/libobs/obs.c#L2472-L2500), [item UUID/name resolution](../obs/obs-studio/libobs/obs-scene.c#L1120-L1141), [positive item identity allocation](../obs/obs-studio/libobs/obs-scene.c#L2289), [frontend collection loading](../obs/obs-studio/frontend/widgets/OBSBasic_SceneCollections.cpp#L1251-L1379), [source input diagnostics](../obs/obs-studio/plugins/obs-ffmpeg/obs-ffmpeg-source.c#L217-L237). These are design references, not executed migration evidence.

English: the next proposed increment is a narrow, explicitly selected **offline private staging** transaction, not application to an active OBS host. Re-read and privately own the original export; a sanitized report cannot restore secrets or confer camera ownership. Start with a single flat, contain-only RTSP scene and explicit silence; reject every unsupported feature for the whole operation. Keep stable scene/source UUIDs separate from positive integer OBS item IDs, check per-scene collisions and bounded id_counter headroom below INT64_MAX, reject name fallback ambiguity, and fixture-test the pinned absolute-coordinate serialization. A collection does not establish global output/profile/FPS. Require private filesystem ownership (including verified Windows DACL), exclusive writes, independent semantic comparison, guarded readback and an exclusive/atomically published completion marker only after member and directory durability; readers still validate the entire manifest and members. The marker is neither cross-file atomicity nor authorization nor a revalidation exemption; rollback touches only newly owned paths. No credentials, exact private fingerprints or paths enter public receipts. Inert-source libobs roundtrips and real filesystem fault/race tests must precede any structural-compatibility claim. Existing account/session lifecycle, trusted graph identity, atomic policy consistency, full-scope authorization and reversible live application remain unresolved; no frontend loader or ffmpeg source may be initialized as an allegedly offline validator.

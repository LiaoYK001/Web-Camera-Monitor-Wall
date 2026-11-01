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

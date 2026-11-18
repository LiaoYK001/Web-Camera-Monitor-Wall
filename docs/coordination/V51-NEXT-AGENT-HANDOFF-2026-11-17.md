# v5.1 Windows 完整交付：下一位 Agent 交接手册与任务书

日期：2026-11-17，Asia/Shanghai。远端最后核对约18:03，本地任务转交18:04；这是交接快照，开始时重新查询CI/PR。

**全文交给下一位开发 Agent 即可。本文替代此前v5.0开发交接；原始功能要求继续有效，下一正式交付目标改为v5.1。**

## 1. 直接执行指令

> 继续开发Windows x64 WebOBS Wall，尽可能完成到v5.1完整正式Release。用户需要一版保留原有功能、数据可迁移、更新可用、性能和体积受控的成品；本人Windows主要验证集中在v5.1，中间构建、联调、回归由你承担，不反复要求用户试开发包或确认是否继续。
>
> 从本文列明的最新工作树/PR继续，不从旧root源码或v4.5重做。先认领V51-002，跟进当前Windows运行，修复实际失败并收束PR65；接着完成多轨声音、合成录像/推流、远端/离线、完整迁移与生命周期等剩余任务。每完成一个真实产品闭环自行继续，不能以CI绿灯、独立原型、未接线模块或一个安装器结束目标。
>
> 复用固定OBS原生宿主及旧业务服务/受认证管理页；普通本地监看只有一套媒体所有者，保持直接RTSP路径。新入口必须确实可安装、打开、使用和恢复，不要求用户另备服务器、安装开发环境或重新手录全部设备。
>
> 保留v4.5及v5.0.0-rc.1的历史Tag/附件；日常只进dev，正式v5.1按审查后的版本化发布流程。最终从GitHub Release给用户完整安装包和简明验收说明，用户不喜欢Actions Artifacts下载。未实现功能继续开发，目标机未测项如实报告，不伪称≤OBS、逐路独显硬解或完整资格。Android/容器等暂停范围不恢复。

依据：用户2026-11-17明确要求“继续优化，争取在v5.1版本rel正式版修复所有这些缺点后发布，我后续使用v5.1在Windows电脑上主要验证”，随后要求交给其他Agent完成。本次只交接，不新增产品改动或发布。

## 2. 先认清当前代码位置

| 位置 | 本次实查状态 | 用途 |
| --- | --- | --- |
| `/home/czl/projects/monitor_wall_czl` | `codex/windows-native-monitor@24fd012`；多项既有未提交/未跟踪资料 | **唯一共享账本入口**。不是最新产品源码；保留原改动，勿切分支、reset/clean/stash或整体git add |
| `/home/czl/projects/monitor_wall_czl/.worktrees/v51` | **干净**；`codex/v51-hardening@2f676e93853c672dfa273320dbbb6db81adbe407`；已推同名origin分支 | **当前最新实际代码，接手这里** |
| `/home/czl/projects/monitor_wall_czl/.worktrees/v5-w2` | 旧证据分支`codex/v5-release-evidence@93870f2` | 历史rc.1证据，保留 |
| `/home/czl/projects/monitor_wall_v5` | 旧工作树`codex/v5-w1-program-take@013fabf` | 历史工作树，保留，不误认最新 |
| GitHub `dev` | 本次API查询`2258a37c744030a13d622e6ed2c2c7b8f6e5ccb0` | 尚未含PR65。先重新fetch/query，不能假定已合并 |

[PR #65](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/65) **OPEN**，head=`2f676e9`，base=`dev`，没有mergeCommit。完整v5.1未发布；最新Release列表仍是v5.0.0-rc.1、v4.5等历史版本。

主checkout的`docs/coordination/`、`scripts/agent-sync.py`及既有协作工具仍未整体提交。**在v51树找不到coordination/TASKS.md是预期，不是进度丢失。** 本机始终读/写root账本；跨机器须携带或正常同步现有账本/脚本/本文件，不能另建空账本丢弃历史，也不能把本机文件锁当分布式锁。

## 3. 当前Windows验证：第一件事先查这里

**有效完整运行：[44057825506](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44057825506)**

- workflow：`windows-obs-native-host.yaml`，独立原生Windows流程。
- source：`2f676e93853c672dfa273320dbbb6db81adbe407`。
- 内部验收版本：`5.1.0-rc.2`，`product_mode=true`、`complete=true`、`native_preview=false`、`pixel_test=false`；没有公开Release。
- 交接完成前再次确认：**Windows预检查、OBS/Qt编译及控制/业务服务构建SUCCESS，正在Exercise the actual integrated launcher and authenticated product window。** 尚无整轮安装/升级/恢复成功结论。此前18:03查询仍在业务构建，以上是本文件写完后复查的新状态。
- 当前head的常规公共CI：[44057792661](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44057792661)，**10项SUCCESS、1项desktop candidate按配置SKIPPED**。这不是完整NSIS/媒体资格。

历史运行不可混用：

| Run | 源码 | 准确结论 |
| --- | --- | --- |
| 44050932022 | c689e1b | 早期v5.1实际便携UI/媒体步骤success，新增真实工作区导入被覆盖；后因新增修复主动取消，整轮cancelled，不能发布其字节 |
| 44055841340 | 8e18590 | wrapper队列等待后主动取消，未当作资格 |
| 44057420866 | 8e18590 | Windows预检查失败：维护工具测试对UTF8中文origin文件用了默认编码读取；尚未构建安装器 |
| **44057825506** | **2f676e9** | 修正UTF8/规范路径夹具后的当前有效整轮；最后核对仍进行中 |

`2f676e9`相对`8e18590`只改2行测试读取/规范路径断言，运行时代码相同；仍以实际run记录的2f676e9作为本次构建身份。不要rerun旧SHA来期待读取新代码；有代码修改应在新源码发起新run并绑定身份。已有正常run还在工作时先读结果，勿无目的重建或取消。

## 4. 这轮已写好的代码，不要重复造轮子

按提交次序：

| Commit | 实际增量 |
| --- | --- |
| `cd33809` | v4.5真实OBS工作区路径迁移；整profile提交/失败恢复空目标；缓存EXE执行前/备份后size与SHA-512复检；版本数字比较与拒绝回退 |
| `c689e1b` | 支持精确5.1.0-rc.N构建；新增真实工作区导入、独立运行时版本/清单的升级夹具、真实更新器和升级后产品门禁；候选Tag显式SourceRevision |
| `003a583` | 固定/Program投影位置、大小、屏幕、全屏偏好按账号保存；缺屏幕时回到可见桌面；事件去抖保存 |
| `8e18590` | 独立维护解释器避免安装Python自占用；自定义/单引号路径、无更新停止、安装前实际版本复核、稳定通道规则；恢复确认/libsodium路径；维护工具清理 |
| `2f676e9` | Windows维护夹具明确UTF8读取并比较resolve后的规范路径 |

重要实现位置（均在v51树）：

- `native-host/scripts/migrate_legacy.py`：读取`native-profile/obs-studio/plugin_config/webobs-native-host/workspace-<userId>.json`，与config一起发布到新profile根；只读旧数据，不覆盖非空新档案。
- `native-host/scripts/native_updater.py`：`is_newer`、`runtime_version`、`verify_installer`、`prepare_maintenance/cleanup_maintenance`、`restore_backup`与`install`。
- `native-host/scripts/check-updates.cmd`：先准备安装目录之外的维护工具，退出原解释器后由复制后的脚本执行；实际安装目录和版本从原安装读取，不写死默认安装位置。
- `native-host/scripts/restore-backup.cmd`：调用明确确认/停机检查后的维护CLI，使用打包libsodium；已补原来缺失的恢复参数。
- `native-host/scripts/product_supervisor.py`：后续启动清理完成的维护工具。临时解释器字节要计入成本，不能隐藏；未完成工具不盲删。
- `native-host/src/product_window.cpp`、`projector_placement.hpp`：已有账号workspace保存投影位置，Qt逻辑坐标限制到当前screen；复用OBS投影，无新解码链。
- `native-host/tests/prepare_upgrade_runtime.py`：构造改变实际runtime version和重新计量清单的下一版本**同源码夹具**，不是独立发布版本。
- `native-host/tests/update_windows.py`：从**已安装的Python**准备外部维护工具，原解释器退出后下载/校验/备份/实际NSIS；加密备份恢复到另一个隔离目标，比SQLite内容语义，不比可能变化的数据库页头。
- `desktop/scripts/test-native-product-install.ps1`：实际NSIS首装、升级、升级后UI/媒体及保留/卸载；更新元数据和备份产生会改变run/backups，因此保留指纹有明确排除范围，不能称全目录逐字节不变。
- `native-host/tests/product_windows.py`：真实Qt工作区迁移→认证前空白→登录恢复、新投影移动/保存/关闭/重开断言。

本机已经执行：迁移3组（含提交故障重试）、loopback更新/损坏缓存/备份期间改写/确认与版本拒绝、维护解释器隔离/清理、加密备份3项、包校验6项、44构建契约；Qt几何测试实际链接执行、完整product_window语法检查通过。**本机安装调用的mock不等于Windows安装已通过。** 最新Windows已完成的步骤以第3节为准。

## 5. 接手与认领：本会话已释放开发任务

原开发Agent ID：`codex-v51-20261117`。按用户明确转交要求，**V51-002已释放为planned，无负责人**；FIX-001只关闭源码缺陷子任务，R4整体未关闭。R2-004也为planned，窗口偏好子能力不等于投影完整恢复完成。CI独立运行，不依赖本会话继续占锁。

使用自己的唯一客户端/会话ID，不复制前任ID：

```bash
cd /home/czl/projects/monitor_wall_czl
cat AGENTS.md docs/coordination/STATUS.md docs/coordination/HANDOFF.md
cat docs/coordination/TASKS.md docs/coordination/DECISIONS.md docs/coordination/PLAYBOOK.md
python3 scripts/agent-sync.py check
git status --short --branch
git worktree list

cd /home/czl/projects/monitor_wall_czl/.worktrees/v51
git status --short --branch
git fetch origin dev
gh pr view 65 --repo LiaoYK001/Web-Camera-Monitor-Wall --json state,headRefOid,statusCheckRollup
gh run view 44057825506 --repo LiaoYK001/Web-Camera-Monitor-Wall --json status,conclusion,headSha,jobs
python3 /home/czl/projects/monitor_wall_czl/scripts/agent-sync.py \
  --root /home/czl/projects/monitor_wall_czl claim V51-002 \
  --agent next-v51-REPLACE-WITH-UNIQUE-CLIENT-ID \
  --note '按最新交接接手Windows迁移更新门禁，已核对源码/PR/运行和修改范围'
```

后续仍先认领再修改；重叠模块串行归一个集成负责人，不能为了绕过冲突虚写范围。测试、失败、进展和交接使用同一脚本更新state，五份生成页不手改。用户已要求继续，不必再次问“是否开始/继续”。

## 6. 下一步执行顺序与结束条件

### A. 先收束V51-002和PR65

1. 读44057825506最新结果；失败就定位对应job/step最小日志和源码，修复实际问题，保留能捕获它的回归。不要删除断言、提高阈值或翻转qualification常量换绿。
2. 整轮通过后读取脱敏回执，核对便携、安装、恢复、升级后UI、维护更新、加密恢复、footprint等实际项。新增检查会改变数量，**不要机械沿用rc.1的52/52/9或预猜新的计数**。
3. 将源码SHA、run、版本、安装包字节/摘要、实际通过/失败/跳过与边界写入`docs/qualification/`、功能矩阵和历史执行记录。只有完整验收满足才关闭本任务。
4. 审查后双语合入dev；保留提交历史，勿将普通PR直接合main。main留给指定v5.1正式发布PR。不要因为这一小项绿就宣布完整产品完成。

### B. 把原生工作台补齐：R2-002/003/004

- **多轨声音优先**：非空`audioInputs`在`native-host/src/product_scene.cpp`仍明确拒绝。需要真实逐轨选择、gain/mute/offset、混音、电平、监听和输出语义，不可删掉拒绝条件假装支持。
- `audioInputs[].track`是输入音轨索引；旧`audioTrack`保留OBS输出总线语义，二者不能混用。空audioInputs仍表示不贡献声音。
- 固定OBS FFmpeg Media Source当前没有产品可用的多轨选择接口；默认best audio也不保证是显式输入轨0。旧core的`ensure_audio_mix_path`可供核对复用，但Direct-only下未自动接到新宿主。选择方案后必须实际接线、可观察、可取消，普通监看不强制视频转码或第二套libobs。
- Scene嵌套/编辑、裁剪/层级/锁定、冲突、业务来源和数据往返需对照真实UI/flatten结果验收。R2-001真实cut/fade TAKE已完成，**不要再从空Program原型重新做TAKE**。
- 投影位置偏好已实现，但**多个固定Scene媒体窗口的自动恢复尚未实现**；重新打开仍经授权，不是保存几何就恢复了场景。继续账户隔离、持久恢复、撤权、Program与固定Scene区分、多屏/DPI/断屏/睡眠恢复。

### C. 完整业务接回：R3-001至004

- 设备控制/PTZ/预置位/快照/对讲：复用既有camera服务和管理页；实际入口、松键/断开/撤权停止、任务收尾。可用虚拟设备做中间回归，真实设备证据留最终主要验证。
- **OBS合成录像/推流未接线**：由同一个原生宿主拥有真实Program输出；NVR原码流MP4录制不能替代合成录制。无输出任务不启编码器；错误、音轨、停止/退出保护和回放文件可验。
- NVR/归档/证据：现有服务已进包并有注册相机录制/鉴权MP4/时间线证据；继续计划/配额/多卷/掉盘、大文件seek/Range、导出hash和审计，不能都推给用户测。
- 事件/检测/网站源：已有事件去重/outbox和解析器版本自检；还需真实通知投递、重启恢复、检测provider与叠层最终像素、实际网站解析/relay/播放。自检与“支持网站列表”不是实播。
- **远端/离线/诊断仍有未接线项**：LAN/Caddy、Direct/Composite适配、现有Web/PWA/Android协议、离线冲突不覆盖Program、脱敏支持包和问题中心。兼容现有Android连接不意味着恢复APK发布。

### D. 完整数据、维护与生命周期：R4-001/002

- 真实旧4.x、v4.5和本候选数据映射、权限/Secret、Scene/Studio/声音、离线数据、录像路径/索引、备份密钥与幂等回退继续逐项核对；本轮只修了明确路径/事务缺陷，未证明所有schema/个人档案完整迁移。
- 优先复核`backup_config`目前的**config目录范围**与位于config外的`native-profile`工作区：产生一个.wobk和能恢复数据库，不足以证明整个原生工作区都被备份/恢复。
- 正常升级/恢复、截断/断网/磁盘不足/错误包/部分安装失败、版本/组件一致性、可解释的重试/回退，需要Agent/CI真实验证。拒绝错误字节不等于已经实现安装失败后的完整二进制回滚。
- 维护入口目前是快捷方式，**未提供应用内后台更新UI**；按既有产品需求补齐检查/取消/确认、正常停机/备份、任务保护和状态，不假定electron-updater继续负责。
- **托盘与后台任务消费者仍需完成**。关闭本地监看不能误停需要保留的录像/远程任务；最后消费者结束应释放资源，故意崩溃要收束自有进程，不能杀用户其他程序兜底。

### E. 性能、体积、长稳与v5.1正式发行：R5–R7

- 最终目标：同条件五路H.265的完整所属CPU/GPU成本尽量达到≤OBS；目标机此前确认i9-13900HX/RTX4090 Laptop，用户v4.5正向定性反馈不等于数值证明。渲染器NVIDIA标签不等于逐路NVDEC。
- Agent先完成至少两小时合成Windows长稳、故障/重连/资源增长和完整组件成本；不能将所有长稳都推给本人Windows。真实相机/音频/多屏/硬解、个人旧数据和OBS同机对照集中在v5.1主要验证，如实列未测项。
- 报告setup、安装logical/allocated、首启数据、核心/全量/离线组件、维护解释器/扩展目录成本及全部所属进程，不混比较159MB下载与795MB安装。允许可选组件，但必须同机可装可用、有完整离线途径，不能隐藏成本或删功能。
- 单一OBS宿主/源共享/默认不视频转码继续保持；按需求控制go2rtc、MediaMTX、FFmpeg、检测等消费和退出，不能靠少一路、降帧/画质/静音达标。
- 当前版本策略只支持5.0/5.1的rc候选；**正式5.1.0身份/构建/校验/发布模式还没有完整接线**。`publish-native-candidate.ps1`仍仅发布prerelease、非Latest，且需`-SourceRevision`；不要把它当正式发布器，或只放宽正则/翻常量/重命名dev包当稳定版。
- 最终正式Tag按项目规则`v5.1`、应用版本`5.1.0`，先核对占用；经审查指定版本dev→main，固定源码和二进制，若重建就重新验证，不冒称字节等同候选。
- 完整NSIS、稳定更新元数据SHA-512/size、manifest、依赖锁/SBOM/许可证与匹配第三方对应源码、双语说明、升级/回退和少量主要验收项；候选source-manifest的`reviewed=false`不能直接改true顶替复审。
- 用户要GitHub Release下载完整包，不反复试中间dev；最终正式公开按有效验收与发布规则完成，未测性能不得宣称合格。v4.5/rc.1旧附件不可覆盖，暂停平台不可误触发发布。

## 7. 已有验证入口与工具

在**v51代码树**运行适合改动的检查，下面不表示本交接重新跑过产品测试：

```bash
python3 -B native-host/tests/test_migrate_legacy.py
python3 -B native-host/tests/test_native_updater.py
python3 -B native-host/tests/test_complete_supervisor.py
python3 -B native-host/tests/test_complete_release_policy.py
python3 -B native-host/tests/test_update_manifest.py
python3 -B native-host/tests/test_upgrade_runtime.py
python3 -B native-host/tests/test_product_package.py
python3 -B native-host/tests/test_build_contract.py
python3 -B tests/test_encrypted_backup.py
```

本树固定OBS源码已初始化。上游不实现产品改动，补丁继续在`native-host/patches/`。OBS pin=`fb4d98bf88fae5fc85cb11fc57f7c5e309282194`，go2rtc pin=`b5948cfb25404cc5cb37b166ecaa2dca20b11d4b`。

本机Qt6.11.2头在`/tmp/webobs-qt-dev-headers`，几何测试可链接`/usr/lib64/libQt6Core.so.6`；这些临时路径先检查，不保证永久存在，也不等价于Windows Qt6.8.3/MSVC。root的`build/native-perf-obs`可供本地固定libobs测试引用，不能照抄其他树CMakeCache当本树构建成功。

当前有效run完成前先读结果；修改后确需新Windows整轮时，现有独立流程：

```bash
gh workflow run windows-obs-native-host.yaml \
  --repo LiaoYK001/Web-Camera-Monitor-Wall --ref codex/v51-hardening \
  -f version=5.1.0-rc.N -f product_mode=true -f complete=true \
  -f native_preview=false -f pixel_test=false \
  -f update_feed=https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/download/v5.1.0-rc.N/latest.yml
```

先把N换成实际未占用候选编号；此命令构建/测试，不公开Release或稳定feed。`windows-desktop.yaml`wrapper也可用，但之前其串行队列被取消收束作业占住；独立流程仍用相同内层门禁和独立托管Windows，不修改用户安装。

Web改动按AGENTS做typecheck/build和相关专用Playwright。新媒体/权限/后台流程优先真实服务、最后像素/音频和实际NSIS，不只新增模拟断言。通过后无新风险不反复全量重跑。

## 8. 阅读索引与交付标准

- [共享当前进度](STATUS.md)、[任务](TASKS.md)、[协作规则](PLAYBOOK.md)、[决定](DECISIONS.md)。新日志/owner只改canonical state，经脚本生成视图。
- [原始完整功能任务书](../windows-webobs-wall-release-plan-2026-11-11.md)：旧版本号预期被v5.1决定覆盖，完整功能要求继续。
- [当前代码功能矩阵](/home/czl/projects/monitor_wall_czl/.worktrees/v51/docs/windows-native-feature-parity.md)、[v5.1开发说明](/home/czl/projects/monitor_wall_czl/.worktrees/v51/docs/release-notes-v5.1.md)、[产品执行历史](/home/czl/projects/monitor_wall_czl/.worktrees/v51/docs/windows-obs-parity-execution.md)。root同名旧产品文档可能落后，勿混用。
- [rc.1独立核查](../qualification/v5-rc1-independent-review-2026-11-17.md)：说明原缺陷与“完整候选”表述问题；本轮修复状态看最新代码与CI，不以旧报告当未修或已修的唯一证据。

最终给用户：一个可安装的v5.1完整包、Release下载/摘要、原功能映射、旧数据升级与回退、实测体积/成本和简明主要验证清单。中间开发由Agent承担；既不能让用户替Agent发现缺少按钮/未安装模块，也不能把没有硬件证据当成停止独立开发的理由。

结束/再交接必须更新state、`agent-sync.py check`、相关树`git diff --check`，保留失败与跳过，不覆写他人修改。用户的目标是完整交付，**不是再拿到一份新的计划或换名的预览版**。

English: resume the clean v51 worktree and PR65, claim the released V51-002 with a fresh agent ID, and first inspect run44057825506 at2f676e9. Preserve source/receipt identity, complete the remaining audio/output/remote/data/lifecycle work, qualify an actual installed product and deliver v5.1 through the reviewed release flow. No full release, target-device parity or complete migration is currently qualified.

# 开发日志 / Development log

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 301 · 2026-11-21T08:39:07+08:00（UTC+08）

[总览](STATUS.md) · [路线图](ROADMAP.md) · [任务](TASKS.md) · [日志](DEVLOG.md) · [交接](HANDOFF.md) · [协作规则](PLAYBOOK.md)

既有产品开发历史继续保留在 [原始执行记录](../windows-obs-parity-execution.md)，不把本轮文档工作当作产品验证。

## #301 · 2026-11-21T08:39:07+08:00 · log

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：rc.83（run 44835178571，同 SHA 54df2e3 复现轮）completed=failure 但为最深一轮：entry-ui 全绿、installed-ui 首次通过（崩溃阶段两种形态同轮均未复现，第四披露项保持开放）、freshInstalledEntryQualified=true、complete-candidate 安装包工件已产出；nsis 推进到 backup_restore_windows.py:438 installed-entry-after-recovery 断言『the running installed product did not read the recovered pair』失败。归因为装置侧潜伏缺陷：配置专用阶段刚断言原生半区保持 kept-native（54df2e3 修复后 line 412/414-417 首次通过，即备份修复在真实安装态生效），无 journal 的普通启动不改动半区，而末段断言自 12d779d 引入起一直期望原生翻回 backup，与配置专用契约自相矛盾、此前从未执行。test-only 修复 bae0610（期望 config=backup 且 native=kept-native，双语注释引 run）；Linux 语义复现末段状态 config=backup/native=kept-native/无 journal；test_build_contract 63 项仅余既有 obs 子模块错误、test_encrypted_backup 14/14 OK。派发 rc.84（run 44845177402 @ bae0610）验证末段并推进 restore-pair/legacy-import/lan/updater/upgraded-ui 十回执目标。
- 证据：job log traceback backup_restore_windows.py:438；nsis receipt freshInstalledEntryQualified=true、failurePhase interrupted-restore-pair-recovery（checkpoint 滞后）；run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44835178571；rc.84 run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44845177402；修复提交 bae0610 已推送
- 源码：`1193a123007e2569216a791806db9a5dc2e07227`
## #300 · 2026-11-21T07:13:54+08:00 · log

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：rc.82（run 44831637710，同 SHA 54df2e3 复现轮）completed=failure：entry-ui 便携运行在 program-publish-disconnect 以 0xC0000005 前端退出崩溃（exitCode 3221226505、currentBootFailure=frontend-exited、句柄 gone、publishStopWaitMs 5820、relayStopMaxMs 5135、uiStallMaxMs 4826，与 rc.76 同形）——第四披露项第四次总命中，便携形态在 rc.79-81 三轮通过后再次命中；nsis/installed-ui/size-split 未产出，54df2e3 安装态生效验证再顺延。崩溃面已在两种形态四次命中（76/82 便携、80/81 安装态），无本机复现、不改代码、不掩盖，交 Codex 主线程。派发同 SHA rc.83（run 44835178571）再判一轮持续性；若再命中则停止同 SHA 轮次、链条暂停待主线程排查。
- 证据：gate exit=3 receipts=entry-ui,restore；entry-ui receipt frontend exitCode 3221226505；run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44831637710；rc.83 run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44835178571
- 源码：`d76167f5888468ce161710d318c8ab869eac8307`
## #299 · 2026-11-21T06:46:36+08:00 · log

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：rc.81 run 44821109893 @54df2e3（同 SHA 复现轮）：entry-ui 再次全绿（77 checks），installed-ui 再次在 program-publish-disconnect 复现 rc.76 前端 AV 崩溃（第三次总命中、安装态连续第二次：frontend exitCode 3221226505=0xC0000005、currentBootFailure=frontend-exited、句柄 gone、48 checks 越过全部录制/发布），自计量同形且 UI 停滞更重（publishStopWaitMs 8576、relayStopMaxMs 5135、uiStallMaxMs 16599）。nsis 级联失败于 installed-entry-ui-and-media、freshInstalledEntryQualified=false，restore-pair 仍未执行，54df2e3 安装态生效验证再顺延。崩溃面间歇性成立（rc.79 installed-ui 曾通过该阶段、rc.80/81 连续崩溃），交 Codex 主线程宿主侧排查；本会话未改代码、未掩盖。派发 rc.82 run 44831637710 @54df2e3（同 SHA 第三复现轮）。
- 证据：docs/qualification/v51-rc73-merge-materials.md; /tmp/tmp.rKkOw2TAwk/native-product-installed-ui.json; /tmp/tmp.rKkOw2TAwk/native-product-nsis.json
- 源码：`83638cebc33069759e0904ac62eb453962ab0cee`
## #298 · 2026-11-21T05:32:09+08:00 · log

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：rc.80 run 44814303103 @54df2e3：entry-ui 再次全绿（77 checks，含发布断连恢复），但 NSIS 安装态内嵌运行在 program-publish-disconnect 第二次复现 rc.76 前端 AV 崩溃（installed-ui passed=false、frontend exitCode 3221226505=0xC0000005、currentBootFailure=frontend-exited、句柄 gone、checkpoint 已写出、断言如实记账），自计量与 rc.76 同形（publishStopWaitMs 5838、relayStopMaxMs 5028、uiStallMaxMs 5009）。nsis 级联失败于 installed-entry-ui-and-media，restore-pair（备份修复安装态生效点）未执行，54df2e3 的真实安装态验证顺延。第四披露项升级为已两次复现（rc.76 entry-ui、rc.80 installed-ui）、间歇性成立、交主线程；本会话未改代码、未掩盖。派发 rc.81 run 44821109893 @54df2e3（同 SHA 复现轮：判定崩溃面持续性并推进 restore-pair/legacy-import/lan/updater/upgraded-ui）。
- 证据：docs/qualification/v51-rc73-merge-materials.md; /tmp/tmp.UmiWx1Q9C0/native-product-installed-ui.json; /tmp/tmp.UmiWx1Q9C0/native-product-nsis.json
- 源码：`8e8af32c4c16350483761b9526f98ffcb6287e0d`
## #297 · 2026-11-21T04:46:31+08:00 · log

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：rc.79 run 44800953316 @9460829：entry-ui/installed-ui/nsis/size-split/restore 首次全部产出（rc.78 重绘停滞未复现），首个失败点为 native-product-nsis interrupted-restore-pair-recovery——backup_restore_windows.py:412 配置档案恢复退出码非 0。Linux 确定性复现根因：restore() 把归档内 backup-manifest.json 落进配置根，下一次 create() 将其当用户文件打包，新清单按陈旧大小自指后被自身覆盖，verify_tree 永久失败——恢复后再打的备份不可再恢复。产品修复 54df2e3（stage_tree 排除根级清单、verify_tree 跳过历史自指条目使既有污染档案恢复可用），回归 14/14、supervisor/updater 脚本 PASS、复现序列 legacy restore exit=0。派发 rc.80 run 44814303103 @54df2e3。
- 证据：docs/qualification/v51-rc73-merge-materials.md; /tmp/tmp.qSBZMfpXSd/repro_legacy_restore.py; codex/v51-r4-legacy-import 54df2e3
- 源码：`da974fb9444936ac26571da9f64af2a596e2965f`
## #296 · 2026-11-21T03:18:24+08:00 · log

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：rc.78（run 44795726091 @ 9460829）在同一 native-program-take 失败但形态更持久：program-after-take 捕获窗内 main-preview 八个采样全部通道正确但计数器完全冻结（counters 全 [31,31,38,38,38]、distinctClientCount=1、distinctTileCounts 全 1、temporalProgress=false，'Frozen final pixels on slot 1'），SerialWatch 窗口 26.03 s；同期宿主渲染计数 9923→10702（~30fps）、六个输入 serial 全部 advance、fixture publisher 全存活无停滞路径、feed 解码探测 32-38 个不同帧——帧已到源、宿主在渲染，但窗口像素整窗不重绘。开渲染探针复测仍部分冻结（tiles 0,2,3 stale 而 1,4 更新），排除整体捕获失效与 fixture 故障；9460829 的首采样瞬态形态不匹配（正确地未触发重试）。归因：cut TAKE 后产品侧预览重绘停滞（真实用户可见），与 rc.76 AV 崩溃同属 TAKE retirement/rebind 宿主竞态疑似根因族；连续两轮（rc.77 瞬态、rc.78 持久）失败于该阶段。属复杂诊断/崩溃恢复面，交 Codex 主线程；本会话未改代码。已派发 rc.79（同 SHA 9460829、同输入）判定该重绘停滞面的复现性（rc.76 曾通过该阶段），不构成放行。
- 证据：gate 44795726091 exit=3 failureReceipts=[entry-ui native-program-take/pixels-program-after-take-captured]; analysis progressError 'Frozen final pixels on slot 1'; probeOnWindow opened=true staleTiles=[0,2,3] renderFramesPerSecond=30.4; feedDecodeProbe distinctFrames 32-38; serialsDuringCapture windowMs 26030 samples 93 publishes 14 全部 inputs advanced=true
- 源码：`4bc7b077fafa231e68fc677af784a1165f4a2203`
## #295 · 2026-11-21T02:45:41+08:00 · log

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：rc.77（run 44751520752，同 SHA 9c2b7af）未触及 rc.76 崩溃面：更早失败于 native-program-take——main-preview 第 0/8 采样捕获 CUT TAKE 后墙格子重绘中途变暗旧帧（Wrong channel 1 in tile 0: 62,30,30），1-7 采样通道正确、计数器推进、temporalProgress 真、fixture 全部存活无停滞路径；属 rc.47/48/50 记录的中途交换窗口竞态，非产品冻结。rc.76 前端 AV 崩溃复现性判定因此无结论（未到达该阶段），披露保持开放。test-only 修复 9460829：仅 Program 交换阶段、仅首采样失败、八采样齐备且进度已证实时，同身份重捕获整窗一次并要求每个角色完全通过（pixelSwapTransientRetry 披露）；捕获调用抽为 run_capture 复用。已派发 rc.78（run 44795726091 @ 9460829，输入同前）。
- 证据：gate 44751520752 exit=3 receipts=[entry-ui,restore] failureReceipts=[entry-ui native-program-take/pixels-program-after-take-captured]; 契约 63 项 62 通过（唯一错误为 obs 子模块未初始化）; test_pixels 31/2; 谓词语义复现容忍 rc.77 形态并拒绝冻结/无进度/后段失败/非 Program/预算耗尽/短窗口; 9460829 已推送
- 源码：`f47146ceb13d7ab14ad1ba65690bdbc25e67a585`
## #294 · 2026-11-20T22:14:41+08:00 · log

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：更正：rc.77 复现性轮实际 run 为 44751520752（@9c2b7af、同输入），上一条登记中预写的 44746006214 为占位、作废。Correction: the rc.77 reproducibility probe is run 44751520752 at 9c2b7af; the 44746006214 in the previous entry was a placeholder and is void.
- 证据：无新增验收证据
- 源码：`527616615b275cf7b8ef82b2a40b76b1ed139152`
## #293 · 2026-11-20T22:14:12+08:00 · log

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：rc.76 run 44746006213 completed=failure：9c2b7af 生效（attempt 1 healthy 100帧/3.3s、无重试），entry-ui 首次推进过 program-streaming 与全部录制/发布检查（48 checks），随后在 program-publish-disconnect 出现真实产品崩溃：私有 MediaMTX 中继被终止、publish-relay-exited 正确上报后，前端宿主以 0xC0000005（访问违例）异常退出（currentBootFailure=frontend-exited、frontend exitCode 3221226505、无 Shutting down 标记），窗口句柄 gone、恢复尝试 0 次成功，断言 "could not resume Program publishing after the relay loss" 记账于崩溃。rc.73–75 同路径同代码均通过，属间歇性竞态崩溃；uiThread 计量：publishStopWaitMs 5943、uiStallMaxMs 5752、relayStopMaxMs 5034（a75d0cf 计量首次捕获该崩溃面）。崩溃归因（中继被杀与 media source 异步重连/发布 teardown 的宿主侧竞态）属崩溃恢复算法与复杂诊断，交 Codex 主线程；无本机 Windows 复现、不做掩盖性测试修改。派发 rc.77 run（同 SHA 9c2b7af、同输入）测复现性：若通过则该面为间歇竞态并继续回执链，若同点失败则确定性崩溃升级。回执披露保持开放。EN: rc.76: the 9c2b7af retry worked and entry-ui advanced past program-streaming plus all recording/publish checks (48), then the frontend host crashed with 0xC0000005 after the private MediaMTX relay was killed in program-publish-disconnect (currentBootFailure=frontend-exited, no Shutting down marker, window handles gone, 0 successful recovery attempts). rc.73-75 passed the same path - an intermittent race crash. Attribution (relay kill vs async media-source reconnect/publish teardown inside the host) is crash-recovery/complex-diagnostics territory: handed to the Codex main thread; no local Windows repro, no masking test change. Dispatching rc.77 at the same SHA to probe reproducibility; disclosure stays open either way.
- 证据：run 44746006214 gate pending; receipt native-product-entry-ui.json: serviceExits frontend 3221226505, publishDisconnectError publish-relay-exited, lastUiFailure window-pid-mismatch gone, uiThread publishStopWaitMs 5943
- 源码：`527616615b275cf7b8ef82b2a40b76b1ed139152`
## #292 · 2026-11-20T21:38:29+08:00 · log

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：rc.75 run 44735378274 completed=failure：9b26035 记账修复生效、门禁首次越过 legacy-config-only-archive 并推进到安装入口的 program-streaming；Program 增益复过（controlRatios 1.0/1.001）。首个真实失败点为 Program 视频窗口断言（frames 26/ptsSpan 0.833s、首帧 4015ms、monotonic true），归因证据：同窗口宿主渲染 +421 帧、中继 streamConnected=true、包连接 140 packets/2 IDR@2.0s，且该启动 OBS 日志 6 次 WebOBS async video backlog（30 帧丢弃、间隙 2.689-3.000s）与 1 次 async timestamp jump——单消费窗口与输入侧解码停滞竞态，同 rc.62 记录的交付 vs 解码分裂，非产品逻辑缺陷；Windows 侧无法本机复现，做低风险有界重试修复 9c2b7af（共享 decodable_window 谓词、一次新连接重读、只对最后尝试记账、probeAttempts 披露、断言消息原样；持续饥饿仍两次失败），并同步更新既有关键帧窗口契约。Linux 语义复现（stalled→retry→healthy 接受、连续 stalled 拒绝、healthy 不重试）、契约 62 项 61 通过（唯一错误仍为 worktree 未初始化 OBS 子模块）、test_pixels 31 通过 2 跳过、py_compile/diff-check OK。派发 rc.76 run 44746006213 @9c2b7af（同输入），轮询中。运行器解码停滞本身保留为披露项（经启动标记），未宣告健康；rc.72 journal/fsync 窗口与硬终止明文暂存清扫两项继续开放交 Codex 主线程。EN: rc.75 passed the legacy-import phase (9b26035 effective) and failed the Program video-window assert: 26 frames over 0.833 s while the host rendered 421 frames, the relay reported a connected stream and the packet probe saw two IDRs 2 s apart - a single consumer window racing input-side async-backlog decode stalls, the documented rc.62 delivery-vs-decode split, not a product logic defect. Low-risk test-only fix 9c2b7af (shared decodable_window predicate, one fresh-connection retry, charge-last-attempt only, probeAttempts disclosure, verbatim message; sustained starvation still fails twice). rc.76 run 44746006213 dispatched at 9c2b7af. Runner decode starvation stays disclosed via boot markers; the rc.72 journal/fsync window and the hard-kill decrypt-staging sweep question remain open for the Codex main thread.
- 证据：run 44735378274 gate inspect-first-failure; receipt programStreamVideoProbe (frames 26, span 0.833, render +421); commit 9c2b7af (codex/v51-r4-legacy-import); contract 62 tests/61 pass; test_pixels OK; Linux retry-semantics repro
- 源码：`df8af7af3dda87ece4fa0ad61780c4fd4cd23607`
## #291 · 2026-11-20T20:25:33+08:00 · log

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：rc.74 run 44728029615 completed=failure：0bd1a29 竞态修复生效、Program 增益复过（controlRatios 0.976/0.938）；首个真实失败点 backup_restore_windows.py:390 拒绝暂存断言，归因为装置记账——成对档案拒绝在自身 .webobs-decrypt- TemporaryDirectory 内抛 BackupError、不可能泄漏，遗留明文暂存来自早前两次 TerminateProcess 硬终止，recover_interrupted 只删除 journal 记录暂存。Linux 真实模块复现三点确认；test-only 修复 9b26035（拒绝前快照、只对新建目录记账、回执披露 staleStagingFromKilledRestores）已推送；契约套件 61 项 60 通过（唯一错误为 worktree 未初始化 OBS 子模块）、tests/test_encrypted_backup.py 12 OK、py_compile 与 git diff --check OK。派发 rc.75 run 44735378274 @9b26035（同输入），低频轮询中。产品侧新问题交 Codex 主线程：硬终止后未跟踪明文解密暂存是否应清扫（崩溃恢复/私有数据边界）。rc.72 journal/fsync 窗口继续开放。EN: rc.74 failed at the refusal staging assert; the refusal raises BackupError inside its own decrypt TemporaryDirectory and cannot leak — leftovers belong to the two hard-killed restores and recover_interrupted removes only journal-recorded staging. Test-only fix 9b26035 pushed (pre-refusal snapshot, charge-new-only, receipt disclosure); rc.75 run 44735378274 dispatched at 9b26035. Product-side question held for the Codex main thread: sweeping untracked plaintext decrypt staging after a hard kill. The rc.72 journal/fsync window stays open.
- 证据：run 44728029615 gate inspect-first-failure; commit 9b26035 (codex/v51-r4-legacy-import); contract 61/60; tests/test_encrypted_backup.py 12 OK; Linux repro of kill-leftover vs refusal-no-leak
- 源码：`7e43a4cfbf89bc807686bb46822424301a97dc06`
## #290 · 2026-11-20T19:30:11+08:00 · update

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：等 rc.74 run 44728029615 结果（轮询 bpcl89xz2）。V51-007 的跨任务知会经 agent-sync log 被拒（该任务仍由 deepseek-v51-20261118-01 认领，log 需属主），知会内容已在本任务 revision 289 记录，交接释放时一并写入 HANDOFF，供协调人转达；不代改 V51-007 状态。
- 证据：无新增验收证据
- 源码：`24c3be6e6e4f3b5080b547b599d96a302650d063`
## #289 · 2026-11-20T19:30:02+08:00 · log

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：rc.73 run 44718717601 完成=failure：program 增益首次通过（controlRatios 440=1.004/880=0.998，880 降增益比值 0.191，逐段 peakHz 全部标称）；首个真实失败点回到成对恢复第二次启动，backup_restore_windows.py:319「the installed entry left the native-swap journal behind」。归因为装置侧竞态：第一次启动实例被终止后 native-status.json 遗留 phase=running+合法 bootId（supervisor 终止不删文件），wait_for 首个 100ms tick 接受旧启动状态，断言先于第二次启动的 recover_interrupted_restore() 收敛；第三次启动相位已有同形守卫（bootId != previous_boot），证明该模式正确。产品收敛代码覆盖被杀窗口（activated.exists()→回置两半→删 journal），非产品缺陷。test-only 修复 0bd1a29 已推送 #76 栈顶：启动前记录 previous_boot、谓词拒绝同 bootId、四类判定落证据，原断言逐字保留，新增静态契约。Linux 语义复现：旧谓词 tick1 接受旧 bootId，新谓词拒绝至本次启动发布且 journal 已收敛。套件 60 项通过（唯一错误为子模块缺口）。已派发 rc.74 run 44728029615 @ 0bd1a29（product_mode/complete/soak_minutes=0），轮询任务 bpcl89xz2。rc.72 的 os.replace/journal fsync 间隙声明继续保留，rc.73/74 通过不代表其安全。
- 证据：receipt /tmp/tmp.TXOGABfLyV/native-product-nsis.json failurePhase=interrupted-restore-pair-recovery；job 136228630230 日志 6928-6937 行 AssertionError；本机复现脚本输出确认旧谓词 tick1 接受、新谓词拒绝；gh workflow run 44728029615 @ 0bd1a2943dd2234e35194819aa80eadaa7ee7f0f
- 源码：`24c3be6e6e4f3b5080b547b599d96a302650d063`
## #288 · 2026-11-20T18:42:24+08:00 · update

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：rc.73 run 44718717601 @ 28c3388 进行中（当前步骤为整合启动器门禁），无更新 run、未重复派发。本机在 .worktrees/v51-legacy 复跑：build_contract 58/59（1 项子模块缺口）、pixels 31OK/2skip、lan 24OK、complete_supervisor PASS、native_updater PASS、camera_registry 58OK、py_compile/diff-check OK。六层 PR 检查全绿、层级 diff 各自独立。合并材料（换基顺序、#69/#73 处理、rc.72 journal 间隙保留声明）写入 docs/qualification/v51-rc73-merge-materials.md，待回执齐全后交 Codex 主线程。
- 证据：无新增验收证据
- 源码：`3a99fa420d1446b456aa3ed56db8743064e588e1`
## #287 · 2026-11-20T18:38:10+08:00 · claim

- Agent：`qwen38-next-v51-20261120-02`；任务：`V51-008`
- 记录：接手 V51-008 继续 rc.73 验收：栈顶 codex/v51-r4-legacy-import @ 28c338840d5e5687ef4231885a70c3386f2cfdc8，run 44718717601（5.1.0-rc.73，product_mode=true complete=true soak_minutes=0）in_progress，无更新 run，不重复派发。本轮先读 native-product-nsis 成对恢复回执（含 lastStateObservation），再核对 legacy-import/lan/updater/upgraded-ui。
- 证据：检查点：V51-008 | worktree .worktrees/v51-legacy | SHA 28c338840d5e5687ef4231885a70c3386f2cfdc8 | rc.73/run 44718717601 | 本轮只验证成对恢复及后续安装态回执是否齐全
- 源码：`3a99fa420d1446b456aa3ed56db8743064e588e1`
## #286 · 2026-11-20T18:36:56+08:00 · release

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：交接释放：rc.73 run 44718717601 @ 28c338840d5e5687ef4231885a70c3386f2cfdc8（栈顶 codex/v51-r4-legacy-import，product_mode=true complete=true soak_minutes=0）仍 in_progress，本会话已停止监控且不再派发。下一步：新会话用 scripts/v51-ci-gate.py 44718717601 --sha 28c338840d5e5687ef4231885a70c3386f2cfdc8 --version 5.1.0-rc.73 依次读 native-product-nsis 成对恢复（含 lastStateObservation）、legacy-import、lan、updater、upgraded-ui 回执；齐了把 #67→#70→#71→#74→#75→#76 差异与 retarget 合并顺序交 Codex 主线程复核，不自行合并或发布。已交 Codex 复核：os.replace 返回与 journal fsync 之间的微秒崩溃窗口会真正丢 nativeRollback 引用，属产品恢复算法边界，回执通过不等于整个窗口无风险。rc.72 修复 28c3388 已推送；Linux 语义回归 PASS；契约套件 58/59（1 项为 worktree 子模块缺口）。本会话按用户要求结束，未做合并、发布或派发。
- 证据：run 44718717601 in_progress；账本 revision 285 记录 rc.72 归因、28c3388 修复与 Linux 回归；本释放不提交不推送。
- 源码：`3a99fa420d1446b456aa3ed56db8743064e588e1`
## #285 · 2026-11-20T18:33:42+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：Fedora 独立回归完成：用 /tmp 一次性脚本对仓库 backup/encrypted_backup.py（与安装包同源）做 interrupt-native 语义实测——哨兵在 fsync journal 记录 nativeRollback 之后触发，prepared 窗口（双前像已记录、config/native 均不在位、两份 staged 在位）内 SIGKILL，recover_interrupted 返回 rolled-back，前像成对回位、parked 目录回位、staging 清零、journal 消失。该回归只证明修复后的窗口语义，不覆盖 os.replace 返回与 journal fsync 之间的真实微秒崩溃窗口；该窗口会真正丢 nativeRollback 引用，属产品恢复算法边界，按指示交 Codex 主线程复核，任何回执通过都不写成整个窗口无风险。已核对 PR 栈链 #67(dev←r3-output)→#70→#71→#74→#75→#76 与草稿 #69/#73；合并顺序与差异材料整理后交主线程复核，本线程不执行合并。
- 证据：Linux 语义回归 PASS（libsodium.so.26，脚本 /tmp/tmp.FhezGk2Fou/native_swap_window_sim.py，临时目录内 profile/backups 隔离）；gh pr list 确认栈基链与 head 28c3388。
- 源码：`3a99fa420d1446b456aa3ed56db8743064e588e1`
## #284 · 2026-11-20T18:23:38+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：rc.72（run 44711476489）通过 rc.71 修复的宿主状态等待，成对恢复停在 backup_restore_windows.py:281 journal 双前像断言，清理阶段 WinError 32 掩盖断言。归因为装置侧时序：interrupt-native 哨兵在 os.replace 返回前触发，杀进程落在物理交换与 nativeRollback fsync 之间，真正丢原生半区引用而非产品 recover_interrupted 承诺的 prepared 窗口；产品恢复顺序未改。修复 28c3388（test-only，已推送）：哨兵改跟记录 nativeRollback 的 _write_journal 之后、配置半区落盘之前，两个中断阶段 finally 终止子进程并关日志，静态契约新增；回归测试修复前后各一次验证通过。已确认无重复 dispatch，派发 rc.73 run 44718717601（soak_minutes=0）。
- 证据：run 44711476489 回执 native-product-nsis.json failurePhase=interrupted-restore-pair-recovery exceptionType=PS RuntimeException；job 136203981742 日志 6926-6940 行给出 AssertionError: journal does not record both previous halves 与 WinError 32；28c3388 后 BuildContractTests 两个契约测试 OK；runbook 提交见本轮。
- 源码：`3a99fa420d1446b456aa3ed56db8743064e588e1`
## #283 · 2026-11-20T17:36:38+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：rc.71（run 44609775780）失败点确认为 backup_restore_windows.py:204 的同一 tick 硬断言，非产品恢复顺序缺陷：product_supervisor.py 在 Popen obs64 后立即 status(running) 写 native-status.json，product_window.cpp 的 observe_state 需等 libobs 模块加载与 12s 内会话绑定后才写带 pid/bootId 的 product-state.json，两者本就异步。按用户 2026-11-20 指示把门禁改为在原 120s 启动预算内有界等待恰好一份可读且匹配本次 frontend PID 与 bootId 的状态文件，失败回执分类 state-file-count/state-file-unreadable/state-from-other-boot/state-published，保留双目录一致性、回滚保留与进程清理原断言；该文件属 V51-007 声明范围，改动依据用户本轮直接指示。
- 证据：a27a76633c16b063156db54584c8a01feb81f758（codex/v51-r4-legacy-import，已推送）：回归测试 test_the_first_installed_start_waits_for_this_boot_host_state 修复前失败、修复后通过；Fedora worktree 与 v51qt 容器复跑 OK（容器补拷 tests/onvif_device_emulator.py）。手册更新单独提交 8124cb1643736caafdde3452a859e96eb976ab04。
- 源码：`8124cb1643736caafdde3452a859e96eb976ab04`
## #282 · 2026-11-20T15:25:21+08:00 · update

- Agent：`codex-t3-direct-model-20261120`；任务：`T3-002`
- 记录：正式 T3 已加载 Qwen 3.8 Flash Next（本地），请求直接使用 qwen3.8-flash-next-gyro-gyro-m。已同步项目委派 ID 和优先使用真实模型名称、ID 的配置原则。
- 证据：T3 隔离仓库实测读写、git diff --check 与逐字节比对通过；Strata 四次 HTTP 200 请求均记录原始 Qwen ID；正式 T3 Provider 目录已注册同名自定义项；脱敏回执 ~/.local/share/t3-integrations/20261120-qwen-direct-id/verification.json。
- 源码：`a75d0cf3841e9c96a8ef48f53d843c47d512e6c9`
## #281 · 2026-11-20T15:24:44+08:00 · update

- Agent：`codex-t3-direct-model-20261120`；任务：`T3-002`
- 记录：隔离 T3 的 Claude Code 已使用 Strata 原始 Qwen ID 完成读写；请求记录与本机配置、AGENTS 路由均已更新。
- 证据：无新增验收证据
- 源码：`a75d0cf3841e9c96a8ef48f53d843c47d512e6c9`
## #280 · 2026-11-20T15:21:25+08:00 · claim

- Agent：`codex-t3-direct-model-20261120`；任务：`T3-002`
- 记录：认领路由设置与 AGENTS.md 的模型 ID 同步。
- 证据：无新增验收证据
- 源码：`a75d0cf3841e9c96a8ef48f53d843c47d512e6c9`
## #279 · 2026-11-20T15:21:25+08:00 · add

- Agent：`codex-t3-direct-model-20261120`；任务：`T3-002`
- 记录：用户要求后续按实际模型显示与请求，尽量避免模型 ID 映射。
- 证据：无新增验收证据
- 源码：`a75d0cf3841e9c96a8ef48f53d843c47d512e6c9`
## #278 · 2026-11-20T12:38:51+08:00 · update

- Agent：`codex-t3-orchestration-20261120`；任务：`T3-001`
- 记录：本机 T3 以 Codex 订阅作为 Wall Monitor 默认主线程，Claude Code 加 Strata Qwen 接常规任务，Pi 加同一 Qwen 作为备用，DSH DeepSeek Flash 接升级任务。路由及账本同步约定已写入 AGENTS.md。
- 证据：AGENTS.md 模型分工；T3 0.1.10 隔离 Git 测试仓库中，Codex 调用 orchestrator_capabilities 并串行委派 Claude Code、Pi 和 DSH，三个子任务完成读写、终端检查及逐字节校验；未改产品代码。脱敏本机证明为 ~/.local/share/t3-integrations/20261120-orchestration/verification.json。
- 源码：`a75d0cf3841e9c96a8ef48f53d843c47d512e6c9`
## #277 · 2026-11-20T12:35:51+08:00 · update

- Agent：`codex-t3-orchestration-20261120`；任务：`T3-001`
- 记录：已安装独立 Claude Code 和 Pi CLI，Strata 鉴权成功，Pi 能列出本机实际 Qwen；开始通过 T3 验证。
- 证据：无新增验收证据
- 源码：`a75d0cf3841e9c96a8ef48f53d843c47d512e6c9`
## #276 · 2026-11-20T12:33:55+08:00 · claim

- Agent：`codex-t3-orchestration-20261120`；任务：`T3-001`
- 记录：认领 Wall Monitor 的多模型路由说明和本机配置验证。
- 证据：无新增验收证据
- 源码：`a75d0cf3841e9c96a8ef48f53d843c47d512e6c9`
## #275 · 2026-11-20T12:33:54+08:00 · add

- Agent：`codex-t3-orchestration-20261120`；任务：`T3-001`
- 记录：用户要求依照附件的多模型方案操作，并将本地 Qwen 的 Pi 作为备用。
- 证据：无新增验收证据
- 源码：`a75d0cf3841e9c96a8ef48f53d843c47d512e6c9`
## #274 · 2026-11-20T04:45:17+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：本轮增加产品侧 UI 线程归因计量并沿 PR 链同步到栈顶 e3a9519；等待 rc.71 结果决定下一轮。
- 证据：无新增验收证据
- 源码：`210020f2c686ffc00ec4e9726a95a09aa810a7b0`
## #273 · 2026-11-20T04:45:14+08:00 · log

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：发布开关被拒的归因补到产品侧：宿主现在计量自身心跳迟到时长/时刻与 Program 拆除各段耗时（停止输出等待、释放推流对象、停止 MediaMTX），写入私有状态观测；已安装门禁在记录 UIA 拒绝时同时带上这份产品自述与状态发布时间。验收阈值未变。该提交已沿 PR 链推进到栈顶。
- 证据：commit 9ed32ae (codex/v51-r3-output, PR #67)；栈顶 codex/v51-r4-legacy-import e3a9519f7a61376ba4f5ca1e53798f55dd17fbd9；静态契约缺少计量时 FAILED、补齐后 OK；native-host/tests 在 v51 worktree 通过
- 源码：`210020f2c686ffc00ec4e9726a95a09aa810a7b0`
## #272 · 2026-11-20T04:33:37+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：rc.70（run 44599567300，源码 ed25609c…）再次停在 program-publish-disconnect，但新判定把范围缩小了：failureDetail 明确是断线后恢复推流的第二次开关；productControlWaits 显示首次调用即被 UI Automation 拒绝（unusableAttempts 空、lastUnavailable=null），不是本次 product-state.json 不可用；lastUiFailure 仍只有共享的 initialize/product-window，因为 product-ui.ps1 对 FromHandle 返回空与 Current.ProcessId≠FrontendPid 抛同一个 code，且该 code 在  赋值前设置，与启动阶段 wait_for(ui('inspect')) 的正常等待无法区分。修复 460789d：拒绝分开发回 window-handle-gone / window-pid-mismatch，并在触碰任何控件之前最多再问三次（400 ms，点击尚未发生）；Python 把 window_owner() 的现场判定写进 lastUiFailure.reportedHandles（gone/other-process(N)/frontend）。发布验收与阈值不变。栈再次重放：#70 3e485f9、#71 6c86adb、#74 bab66ab、#75 3bb51fa、#76 cdfe818（顶层完整 SHA cdfe8182a4928a75d4eff31b7afe0b110f3bde92，相对 ed25609 只差 3 个文件 37+/5-）。
- 证据：rc.70 回执 /tmp/rc70.aZVt/：installed-ui passed=false failurePhase=program-publish-disconnect failureDetail='the product publish control could not resume Program publishing after the relay loss' lastCheckpoint=program-publish-disconnect-reported publishDisconnectError=publish-relay-exited publishRelayPid=7824 productControlWaits=[{label:'publish again after a relay loss',recoveredAfterAttempts:0,unusableAttempts:[],lastUnavailable:null,lastUiFailure:{stage:'initialize',code:'product-window'}}] lastStateObservation={code:'state-from-other-boot',pidMatched:false,bootIdMatched:false}（该条来自结束时的观察，不属开关调用）；entry-ui passed=true、restore 通过、size-split 含 installedTree；restore-pair、legacy-import、lan、updater、upgraded-ui 仍未执行。本机 test_build_contract 55 OK（新契约在修复前的 product_windows.py 上失败于 reportedHandles 计数 1≠2；在修复前的 product-ui.ps1 上缺少两个区分 code），git diff --check 干净，无新增 rtsp userinfo。rc.71 run 44609775780 已派发，监视 /tmp/watch71.log。
- 源码：`37caa067b4f74f82a2d4409d905dfeadd21caa4d`
## #271 · 2026-11-20T03:34:48+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：rc.69（run 44587525224）首次跑到 NSIS 安装态：NSIS 新装、便携门禁、TAKE 像素、录像/发布双音、总线隔离、逐轨静音/增益（比值 1.01/1.005，降至 0.201）/偏移、设备操作、录像失败路径共 45 项通过，随后停在 program-publish-disconnect，failureDetail 只有 'AssertionError: '（裸 assert ui(...) 无消息），lastUiFailure 还停留在启动阶段。定位：ui() 返回 False 有两种原因——本次启动 product-state.json 不可用，或 UI Automation 拒绝被拥有窗口——空消息把两者混在一起。修复 4a79201：state() 记录 lastStateObservation（state-file-count/state-file-unreadable/state-from-other-boot），ui() 在提前返回前记录 lastUiUnavailable（matchedWindows、reportedRoles、用 user32 IsWindow+GetWindowThreadProcessId 现场判定的 reportedHandles：gone/other-process/frontend），发布开关改用 ui_control（仅窗口暂不可寻址时有界等待并记录 productControlWaits；真实 UIA 拒绝不重试，因为点击从未发生），failure_detail() 在无消息断言时附上判定。发布验收与阈值未改。栈按依赖重放推送：#70 b25624c、#71 324413b、#74 8996b94、#75 0f59dc7、#76 ed25609（顶层完整 SHA ed25609c58933b10c52f4f86fd98369ad6d0d489，相对 bf8c1ce 只差这两个文件 194+/4-）。
- 证据：rc.69 回执 /tmp/rc69.ht0c/native-product-integration-receipts-5.1.0-rc.69/：installed-ui passed=false failurePhase=program-publish-disconnect lastCheckpoint=program-publish-disconnect-reported publishDisconnectError=publish-relay-exited publishRelayPid=2908 programTrackGain controlRatios 1.01/1.005 gainPointTwo 比值 0.2012 programTrackMute 880=6.5 programBusIsolation busTwo 440=4070.2/1200=2.7、busThree 1200=4102.9/440=5.5 programTrackOffsets [[0,500,300],[1,0,-200]] recordingFailureReceipt=recording-directory-failed deviceOperations 有 ONVIF GetProfiles；entry-ui passed=true（77 项）restore/size-split 通过，restore-pair、legacy-import、lan、updater、upgraded-ui 因门禁中断未执行；本机 native-host/tests/test_*.py 全部 OK（两个需 --probe 的真机探针除外），test_build_contract 56 OK（非 v51 worktree 仍因 obs 子模块未初始化报 1 error，与本轮无关），git diff --check 干净，staged diff 无新增 rtsp userinfo；新回归在修复前文件上失败于残留裸 assert（2686/2703），修复后三种结局与空消息补全全部通过。rc.70 run 44599567300 已派发，监视 /tmp/watch70.log。
- 源码：`fc63607a4ec03c0e1cc2829f193d00445f329e0c`
## #270 · 2026-11-20T03:05:28+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：长稳门禁补上 Linux 回放回归（#74 提交 0686c2b）：假宿主、假时钟、假夹具发布进程重放同一个 soak_watched_inputs，夹具发布进程窗口内退出被重启并继续观察、不记成产品停滞，而输入停滞、进程树变化、私有内存/句柄增长、不可读进程、CPU 过低与回环服务退出仍分别失败；换回 1861627 的父提交即失败、换回修复版即通过。栈已按依赖重放推送：#75 da2fc15、#76 bf8c1ce（顶层完整 SHA bf8c1ce…，只差测试文件）。另外在临时 worktree 里把 #67→#70→#71→#74→#75→#76 顺序试合进 origin/dev：六个 merge 全部自动干净，合并树 native-host/tests/test_*.py 除两个需 --probe 的真机探针与未初始化 obs 子模块外全部 OK；workflow 在 soak_minutes>0 时 job timeout 为 260 分钟，够容纳 120 分钟长稳。
- 证据：codex/v51-r5-soak 0686c2b（test_build_contract.py 55 项 OK；换回 bd617e8 的 product_windows.py 后新增回放断言失败于已重启发布进程）；codex/v51-r3-005-devices da2fc15；codex/v51-r4-legacy-import bf8c1ce；试合树 /tmp/merge-dry.9r6A 六次 merge 无冲突且 native-host 套件 OK；rc.69 run 44587525224 仍 in_progress，当前步骤 Build and qualify a fresh integrated product NSIS installation（首次执行安装态门禁）。
- 源码：`6feda94c64c0595b19d68c98d66251aaad845dda`
## #269 · 2026-11-20T02:30:16+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：第二个本轮修复：public-audit 在 native-host/tests/test_build_contract.py:322 报 non-placeholder RTSP credentials，#67/#70/#71/#74/#75/#76 的 PR 检查因此全部失败（run 44587405965 与 44578735870 都是 public-audit → Audit and build the public PWA 步骤 exit 1），合并被阻塞。混音辅助进程夹具必须携带 userinfo 才能证明净化器真的剥离凭据，故按仓库既有测试约定改为 fixture-user:fixture-password 与 TEST-NET 文档网段 192.0.2.9，并把该引用登记进 tests/run-public-audit.sh 与 .ps1 两个允许列表（与其余 17 条既有登记同流程）。为此把这两个审计入口加入本任务声明范围。本机按审计脚本同一规则复跑：RTSP AUDIT OK；净化断言仍要求身份与 tail 不含 userinfo 与远端主机。
- 证据：codex/v51-r3-output e5a87b0；栈再次重放推送：#70 d475a70、#71 da082ee、#74 1861627、#75 9c59f49、#76 6971a60（顶层完整 SHA 6971a60aadd5fe7244b16192c24450f2a1705f52；相对 e955d9e 的树差只有 test_build_contract.py 与两个审计入口）；本机 native-host/tests/test_build_contract.py 54/54 OK、审计 RTSP 规则复跑 OK、git diff --check 干净。
- 源码：`d803d1283290c888a5f86a4a491415c1bf7dfc41`
## #268 · 2026-11-20T02:25:35+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：rc.68 run 44577184643（源码 2c0e99dc，soak_minutes=0）已完成并失败：49 项通过，首个失败点 phase=program-track-controls、detail=AssertionError: the unchanged gain configuration measured differently twice: {'440': 0.58, '880': 0.359}（checkpoint program-mix-audible-per-track gain reference repeat）；该轮只有 entry-ui 与 restore 两份回执，NSIS 安装、逐轨增益、成对恢复均未跑到。本轮只验证一个已定位失败点：测量把整窗一次性投影当成音调本身。用真实 FFmpeg（ffmpeg 8.1.3，本机 Fedora）回放录制形状复现——在 1.2 s 处丢掉 40 ms 音频块后，440 Hz 的整窗投影从 2890.0 掉到 991.3（比值 0.343）、880 Hz 掉到 0.814；偏离标称 0.4 Hz 时比值 0.286，而音调始终明显可闻。混音重采样带漂移校正并在流抖动时交接丢弃块，相位断裂后整窗投影读的是各段之和。修复 768fa07：幅度改为 0.5 s 短段在 ±1 Hz 带宽内最强投影的平均（平均而非中位数，保证窗口内静音仍按比例低估，lead-in 保护仍有效），并把增益对照的测量证据写在断言之前（rc.68 的比值是失败回执里唯一的数字）。验收阈值一字未改。
- 证据：codex/v51-r3-output 768fa07；栈已重放推送：#70 4f81086、#71 5348d3b、#74 04370d4、#75 0b387c8、#76 e955d9e（顶层完整 SHA e955d9ea5d7947917a4a85292b923c5e91afc6f6，与旧栈顶 a71d561 的树差仅为本次 4 个测试文件 236+/19-）；本机 native-host/tests/test_pixels.py 31 项 OK（2 skip）、test_build_contract.py 54/54 OK、native-host/tests/test_*.py 全套 exit 0（仅两个需显式 --probe 的 Windows 真机探针 exit 2）、test_product_lan 24 OK、test_legacy_import OK、git diff --check 干净；把 pixel_windows.py 换回 HEAD 版本回放：丢弃块对照 0.343/0.814 失败、偏离标称音调 0.286 失败、toneReadings KeyError，换回修复版全部通过。非 v51 worktree 未初始化 obs/obs-studio 子模块时 test_lock_matches_pinned_obs_and_only_needed_dependencies 报缺 CMakePresets.json，与本轮改动无关（#69 待补）。
- 源码：`c435bb063ee94d3dd8acde1640bef95c345e5bd7`
## #267 · 2026-11-20T01:35:30+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：进行中轮：rc.68 run 44577184643（源码 2c0e99dc04a81fd8d92f878a5e2f6da682507420，soak_minutes=0）仍在编译 OBS，沿用该 run ID。本轮补上修复前失败、修复后通过的本地回归 c64a76b，并在 Fedora 用同一份 rc.67 脱敏回执复跑得出台账期望结论：三个采样 unserved 均为空、停止后 live==claimed，即 rc.67 的停止本不应判为丢 feeder。
- 证据：rc.67 run 44568325933 首个失败点 phase=program-publish-disconnect、detail=TypeError: list indices must be integers or slices, not str（门禁把混音观察返回的 PID 列表当成回执行），已由 0874fd4 修复；该轮 49 项通过并保留 TAKE、双总线隔离、逐轨静音、逐轨增益 0.2007、录像失败路径、设备操作入口、发布与恢复解码帧等有效证据。本机 test_build_contract.py 53/53 通过；把 product_windows.py 换回修复前版本（deaec20）后新回归失败于 AssertionError: [12, 13] is not an instance of <class dict>，换回修复版即通过。Fedora 容器 v51qt（fedora:44，Python 3.14.10）内 -k mix 3 项通过，脱敏回执回放：publish-disconnect-start live=[51078,51389] claimed=[51389] unserved=[] orphan=[51078]；before/after stop live=[51389] claimed=[51389] unserved=[] orphan=[]；converged=True；MIX-PORT VERDICT: PASS。链式同步后 #67 c64a76b、#70 0f3f078、#71 3a282f8、#74 b7f0f01、#75 f964680、#76 a71d561（栈顶自身提交数仍 24，相对 2c0e99d 只多 1 个测试文件 80 行）。
- 源码：`1dbe364a10867dab7cee08f1692d46431de608d4`
## #266 · 2026-11-20T01:35:22+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：进行中轮：rc.68 run 44577184643（源码 2c0e99dc04a81fd8d92f878a5e2f6da682507420，soak_minutes=0，17:26Z 起仍在编译 OBS），沿用该 run ID。本轮补上可在修复前失败、修复后通过的本地回归 c64a76b：用 rc.67 脱敏回执行在本地回放取状态-记录-比较链路；并在 Fedora 容器 v51qt 用同一份脱敏回执复跑得出台账期望结论（三个采样 unserved 均为空、停止后 live==claimed，即 rc.67 的停止本不应判为丢 feeder）。
- 证据：rc.67 run 44568325933 首个失败点 phase=program-publish-disconnect、detail=TypeError: list indices must be integers or slices, not str（门禁把混音观察返回的 PID 列表当成回执行），已由 0874fd4 修复；该轮 49 项通过并保留 TAKE、双总线隔离、逐轨静音、逐轨增益 0.2007、录像失败路径、设备操作入口、发布/恢复解码帧等有效证据。本机 test_build_contract.py 53/53 通过；把 product_windows.py 换回修复前版本（deaec20）后新回归失败于 ，换回修复版即通过。Fedora 容器 v51qt（fedora:44，Python 3.14.10）内  3 项通过，脱敏回执回放输出：publish-disconnect-start live=[51078,51389] claimed=[51389] unserved=[] orphan=[51078]、before/after stop live=[51389] claimed=[51389] unserved=[] orphan=[]、converged=True、MIX-PORT VERDICT: PASS。链式同步后 #67 c64a76b、#70 0f3f078、#71 3a282f8、#74 b7f0f01、#75 f964680、#76 a71d561（栈顶自身提交数仍 24，相对 2c0e99d 只多 1 个测试文件 80 行）。
- 源码：`1dbe364a10867dab7cee08f1692d46431de608d4`
## #265 · 2026-11-20T01:27:37+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：rc.67（run 44568325933、源码 c29227a）49 项通过但仍失败于门禁：混音观察返回 PID 列表而端口比较按回执行读取 row["hostClaims"]，抛 TypeError；观察现返回记录行并断言行形状（修复 0874fd4）。该轮端口读法已生效：start 端口 51078/51389、停止前后 51389、宿主声明混音 mixerPort=51389，TAKE/双总线隔离/逐轨静音/逐轨增益 0.2007/录像失败路径/设备操作入口均已落进回执。rc.68 run 44577184643 已派发。
- 证据：rc.67 回执 /tmp/rc67.0oFX/native-product-integration-receipts-5.1.0-rc.67/native-product-entry-ui.json：programTrackGain gainOne 2165.6/2159.0、gainPointTwo 2160.3/433.6（比值 0.2007）、programTrackMute 880Hz=0.1、programBusIsolation busTwo 440Hz=2889.5/1200Hz=0.5 与 busThree 1200Hz=2542.5/440Hz=0.7、recordingFailureReceipt recording-directory-failed、deviceOperations 有 ONVIF probe/GetProfiles；发布流探针 firstDecodableFrameMs 3452（首次）/1844（恢复）、windowTimedOut true、returnCode 1，伴随 h264 中途加入解码告警。本机 test_build_contract.py 52/52、native-host/tests/test_*.py 全套通过（两个需显式 --probe 的真机探针除外）、git diff --check 干净。链式同步后 #67 0874fd4、#70 559a0f9、#71 dd92696、#74 33ce403、#75 c5ed74f、#76 2c0e99d（各分支自身提交数不变）。rc.68 run 44577184643 源码 2c0e99dc04a81fd8d92f878a5e2f6da682507420、soak_minutes=0。NSIS 安装态、两小时长稳与目标机 OBS 对照仍未执行；本机无 PowerShell，NSIS 脚本只静态核对了 Python 参数与文件存在性。
- 源码：`da197f9108b68914632b573d31c2a17ddf067fbd`
## #264 · 2026-11-20T00:40:00+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：门禁命令行截断缺陷已修：helper_port() 原来解析被截到 160 字符的显示串，真实混音命令行约 485~509 字符且回环目标在末尾，导致每个存活混音都被读成无端口；现从掩码后未截断的命令行读取端口并记录 80 字符 tail（修复 329178b，文档 deaec20）。rc.66 run 44563580338 已取消；rc.67 run 44568325933 已派发。
- 证据：本地 native-host/tests/test_build_contract.py 52/52、native-host/tests/test_*.py 全套通过（两个需显式 --probe 的真机探针除外）、git diff --check 干净；真实形状 485 字符命令行本机验证端口 58964 在截断后仍可读、URL 与私有根不外泄。rc.67 run 44568325933 派发源码 c29227a8a5bd0e4bce697aad083506d6528dd554（栈顶，含 329178b），soak_minutes=0。#67 头 deaec20、#70 e1c62b0、#71 080bd45、#74 80a0d2d、#75 078fd32、#76 a469db1 已链式同步。NSIS 安装态、两小时长稳与目标机 OBS 对照仍未执行。
- 源码：`eaf2a477a51cd9899741dd8410da5abc521d7003`
## #263 · 2026-11-20T00:13:44+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：rc.65（run 44557855349）在同一断言处失败后，其门禁步骤失败导致回执上传步骤不会执行，已在恢复步骤中取消；rc.66 已从栈顶 496be556 派发（run 44563580338，soak_minutes=0），本轮同时是第一次可能取得安装态回执（NSIS 安装步骤只在门禁成功时运行）
- 证据：run 44563580338 head 496be556b6b642eb36a7b13170e629d893df08f7 与栈顶一致；rc.65 无产物（取消于恢复步骤）；门禁 watch66 日志 /tmp/watch66.log
- 源码：`38db2a50b4f73ccb7ec07b4e910c205904eef6d2`
## #262 · 2026-11-20T00:04:56+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：复核 rc.64 失败现场：宿主当时只声明 1 条混音、也只有 1 个存活 FFmpeg 辅助进程，消失的 PID 属于正在释放的上一版 Scene 图；门禁断言因此改为按同一时刻比较——每次采样要求声明端口都有存活辅助进程，停止 Program 输出后 40 秒内收敛到存活端口多重集等于声明端口集合。另在本机 ffmpeg 8.1.3 证实 tcp listen 写端在读端断开后以 Broken pipe 退出、同端口可立即重新监听，记为开放加固风险（本轮未改混音生命周期）
- 证据：codex/v51-r3-output 89fe334；rc.64 回执 observedState.audioSources 1 条声明（available true / processExitCode -1 / mixers 2）与 1 个存活辅助进程；本机 /tmp/mixprobe2.sh 记录 Broken pipe 退出与同端口重新监听；栈已重放推送：#70 6fb81b2、#71 c39afab、#74 c6ae922、#75 56b6d33、#76 496be55（顶层完整 SHA 496be556b6b642eb36a7b13170e629d893df08f7）；test_build_contract.py 52/52
- 源码：`8f4e0a43730f7961a97c35b5eea8bfa7b3ec8503`
## #261 · 2026-11-19T23:57:09+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：补齐 V51-008 实际改动范围：混音端口需要 product_scene.cpp 记录监听端口、test_build_contract.py 承载门禁契约与单元测试，两者此前未写进声明范围
- 证据：无新增验收证据
- 源码：`832c25e175d281ced0ca49784dd9df8e348f994b`
## #260 · 2026-11-19T23:54:56+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：rc.65 仍在运行；本轮把混音辅助进程与混音源用回环端口绑定：ProductAudioProgress 增加 mixer_port、audioSources 行新增 mixerPort，门禁净化命令行保留 tcp:<port> 并把归属断言改为混音端口多重集相等；同时记录 otherHelpers（录像收尾重混）与夹具发布进程状态，避免把一次性子进程或夹具断流算作混音缺失
- 证据：codex/v51-r3-output c6ffb7f；build contract 52/52；Fedora 容器 -fsyntax-only 通过 product_scene.cpp/product_window.cpp；栈已重放到 #67 c6ffb7f：#70 b3c16b5、#71 b1df906、#74 4b9d9cc、#75 90aff05、#76 5237e79（均已 --force-with-lease 推送）
- 源码：`b45dd8690cf1b56faaeff848ef6ce661e46a7454`
## #259 · 2026-11-19T23:43:15+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：rc.64 通过 49 项：关键帧窗口读取在 Windows 首次通过（首次推流 89 帧/跨度 3.866s/首个可解码帧 2437ms/包探针 3 个关键帧包），恢复推流 65 帧/跨度 2.2s 通过，逐轨静音·增益·偏移首次取得 Windows 声学实测。新的第一失败为辅助进程归属：停止 Program 输出后两个宿主拥有的 FFmpeg 混音进程只剩一个，而宿主仍报 mixers: 2、processExitCode: -1。已加身份观察（阶段开始/停止前/停止后三采样 + 脱敏命令行 + 宿主声明），断言仍为精确 PID 集合相等。
- 证据：rc.64 run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44548882087 @ 0a7726a983694bd62621e46617d90b3c0f3ccb2b：49 项通过，failurePhase=program-publish-disconnect，detail 'AssertionError: stopping Program output changed the Scene audio mixers ([5092, 6176] -> [6176])'；programStreamVideoProbe frames 89/span 3.866/firstDecodableFrameMs 2437/packetProbe 170包-3关键帧-firstPacketIsKey false-gap 2.0；publishReplayVideoProbe frames 65/span 2.2/firstDecodableFrameMs 4875；programTrackGain gainOne 2170.5/2161.6、gainPointTwo 2165.4/433.7（比值 0.2006）、controlRatios 0.998/0.999；同窗 measuredFramesPerSecond 23.02、laggedFrames 1086→1216（记录但未断言）；codex/v51-r3-output@297b637；test_build_contract.py 51/51（新增假 PowerShell 身份脱敏测试）；栈已同步推送：#70 af8793b、#71 e9dbca5、#74 b209690、#75 afc5a53、#76 8603c02（顶层完整 SHA 8603c025cf20b34ccb81a407ef2f995da08b7ffd）；run 44557855349 = 5.1.0-rc.65 @ 8603c025cf20b34ccb81a407ef2f995da08b7ffd（soak_minutes=0）queued；门禁日志 /tmp/watch65.log
- 源码：`b8bfb623147fc4752ead29df6b4e44a5bfcff4db`
## #258 · 2026-11-19T22:55:36+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：rc.63 的失败是门禁自身的缺陷：副连接包探针用 %-格式化生成含 % 的 MediaMTX 读取区间，抛 ValueError 并因两个探针完成后才写回执而丢掉已跑完的 6 秒帧窗口结果。已改为字符串拼接读取区间、诊断整体 try/except 记为 diagnosticFailed 并保留 readInterval，主断言不再受诊断影响。
- 证据：rc.63 run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44544305133 @ dab2e0fa3e87db7f11d0331f6ccf2043266be9f1：42 项通过，failurePhase=program-streaming，detail 'ValueError: unsupported format character ':' (0x3a) at index 4'，无 programStreamVideoProbe；同轮通过项含录像 13558804 字节/19 秒、录像双音、发布流双音 1384.1/907.3、streamConnected true、laggedFrames 0；codex/v51-r3-output@c28ddea；test_build_contract.py 50/50（新增假 ffprobe 区间/关键帧计数/缺可执行文件三条断言）；栈已再次同步推送：#70 fdf4c9c、#71 3c31f7c、#74 54fc756、#75 f18fe12、#76 0a7726a（顶层完整 SHA 0a7726a983694bd62621e46617d90b3c0f3ccb2b）；run 44548882087 = 5.1.0-rc.64 @ 0a7726a983694bd62621e46617d90b3c0f3ccb2b（soak_minutes=0）in_progress；回执目录将落在 mktemp 的 /tmp/rc64.*；门禁 /tmp/watch64.log
- 源码：`39266e04bafb177c65cd54dc538740c6a8859473`
## #257 · 2026-11-19T22:35:30+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：追加一个用假 ffprobe 直接驱动 published_video_window() 的单元测试，锁定字符串 pts_time 解析、N/A 记入 unparsableStamps 而非计数、stderr 噪声不阻塞窗口；栈已再次同步到新基线。
- 证据：codex/v51-r3-output@b893905；test_build_contract.py 49/49（在 .worktrees/v51）；已 rebase 推送：#70 67699ee、#71 66facec、#74 893e3af、#75 f62004c、#76 8023fff（顶层完整 SHA 8023fff7cbc147cc38d0c5f3e838c16dd7c6827e）；rc.63 仍在跑 run 44544305133 @ dab2e0fa3e87db7f11d0331f6ccf2043266be9f1，回执将绑定该 SHA；b893905 之后仅新增测试文件，不改门禁行为。非 v51 worktree 未初始化 OBS 子模块时 test_lock_matches_pinned_obs_and_only_needed_dependencies 报缺文件，与本轮改动无关（属 #69 待补）。
- 源码：`8a9be92ced0ec3b036f97fb3debac6e00faf3a3b`
## #256 · 2026-11-19T22:33:05+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：本机用固定 MediaMTX v1.18.2 复现并确认：晚加入 RTSP 客户端的 20 包读取返回码 0 且 0 帧，而同一连接读 6 秒解出 148 帧（首个可解码帧 1977 ms，跨度 4.9 s，30.2 fps），副连接包探针显示中继每 2 秒交付关键帧（3 个关键帧包、firstPacketIsKey false、间隔 2.0/2.0）。缺陷在读取窗口，不在产品推流侧。
- 证据：本机实验目录 /tmp/latejoin.elgB；mediamtx v1.18.2（与 docker/Dockerfile 固定版本一致），配置与 product_output.cpp::media_mtx_config 同形状；旧探针 returnCode 0/jsonFrames 0；新探针 frames 148、monotonic true、span 4.9 s、firstDecodableFrameMs 1977、fps 30.2；packetProbe packets 181/keyframes 3/firstPacketIsKey false/firstKeyPacketPts 1.0676/keyGaps [2.0, 2.0]
- 源码：`806d0800758638fa7c5becc278c47a5a222fcb0b`
## #255 · 2026-11-19T22:30:40+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：rc.62 与 rc.61 同点失败已定位方向：晚加入的 RTSP 客户端在下一个关键帧前就结束了 20 包读取；两个 Program 发布视频门禁改为共用按秒窗口读取器并新增包探针，中继被杀后的恢复门禁同修，pts_time 字符串解析修正，新增契约测试锁定 keyint 与断言。
- 证据：rc.62 run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44534272424 @ f88b525e：42 项通过，failurePhase=program-streaming，programStreamVideoProbe frames=0/ptsSpanSeconds=0.0/returnCode=0，stderr 'co located POCs unavailable'+'mmco: unref short failure'，renderFrames 10620→10680、laggedFrames 8→8、streamConnected true、renderProbe available=false；programStreamBandRms 1377.1/907.2；codex/v51-r3-output@d6d2624；test_build_contract.py 48/48；native-host/tests/test_*.py 全套通过（两个需 --probe 的真机探针除外）；栈头已 rebase 推送：#70 825442d、#71 46f7b14、#74 223c7b7、#75 41fc1ad、#76 dab2e0f；run 44544305133 = 5.1.0-rc.63 @ dab2e0fa3e87db7f11d0331f6ccf2043266be9f1（codex/v51-r4-legacy-import，soak_minutes=0）in_progress
- 源码：`7afa8a22439ba549b4857ed0f5967cc14835bebe`
## #254 · 2026-11-19T21:31:51+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：rc.61（run 44524750280 @ 937129b）42 项通过后首次不再停在 TAKE，改停在 program-streaming：published Program did not deliver enough video frames。该断言原先没有 ffprobe 返回码/stderr/帧数/pts 跨度与宿主渲染计数，无法区分编码器 pacing、中继拒读与宿主图形线程停滞；已补 programStreamVideoProbe 且阈值不变。同时把 render probe 改为只在 harness 通过 product-render-probe.control 打开的窗口内绘制（tick ≤250 ms 读一次，缺文件/过期/untilMs:0 都不绘制），像素断言窗口内关闭，只在像素断言即将失败时加一次探针开启的采集（pixelFailureDiagnostics.probeOnWindow），避免探针拖慢发布 pacing 或用 inc_showing 复活播放掩盖冻结。已在 f88b525（rebased heads 2a635b3/8f5e5b4/fade489/148fa38）派发 5.1.0-rc.62（run 44534272424，soak_minutes=0）。
- 证据：rc.61 回执 /tmp/rc61rec.xbza/native-product-integration-receipts-5.1.0-rc.61/native-product-entry-ui.json：checks 42、failurePhase=program-streaming、programStreamBandRms {below600Hz:1379.3,above660Hz:911.2}、WebOBS async backlog/timestamp jump 均为 0；TAKE、逐轨总线录像与发布双音调都已通过；本机验证：Fedora 44 容器内 product_window.cpp/product_scene.cpp -fsyntax-only -Wall -Wextra exit=0；应用补丁后的 libobs/obs-source.c -fsyntax-only -Wall exit=0（patch -p1 通过）；native-host/tests/test_*.py 全套通过（两个需 --probe 的真机探针除外）；git diff --check 干净
- 源码：`8c9c74bcd2f654805280bb127f5daece35f4e599`
## #253 · 2026-11-19T20:32:44+08:00 · log

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：rc.60（run 44474401536 @ 3c9d6f6）38 项通过后失败于 native-program-take 的 pixels-program-after-take-captured（Frozen final pixels on slot 1），NSIS 安装被跳过，逐轨增益修复未到达 Windows 断言。先核清旧证据不能归因的原因：SerialWatch 读的 product-state.json 只按 2000 ms 心跳发布，inputs[].maxStallMs（2250）与 renderFramesMaxStallMs 实为发布间隔，8 个采样 serial 完全相同（35/18/10/37/38）只说明读到同一快照，而 serial 只证明帧被交给 source、不证明 OBS 画出它。本轮在同一短窗口对齐三层且不放宽像素/帧断言（提交 a1af1b9）：OBS 补丁在 get_frame() 记录帧时间戳、内容摘要与 os_gettime_ns 到达毫秒，webobs_get_video_progress 升 schema 2；product_scene 接受 schema 1/2、拒绝 3；快照新增 frameTs/frameHash/frameAgeMs（-1=无遥测）；WEBOBS_PRODUCT_RENDER_PROBE=1 时宿主按 OBS 截图 helper 模式把预览 Scene 与 Program 通道画进 ≤960x540、每 slot ≤160 ms 的离屏纹理并按同一 3x2 网格发布逐格摘要环；SerialWatch 记录 publishedAtMs/发布次数/最大发布间隔，stallMs 改名 stallWindowMs，逐输入给出窗口内 distinct frameHash/frameTs；失败时按本次 order 反查相机输出 layerAttribution，并用 ffmpeg 解码该相机回环 4 秒逐帧摘要；OBS 日志新增有界标记 WebOBS async video backlog（async 队列 ≥30 整队丢弃且清掉 cur_async_frame）与 WebOBS async timestamp jump。修掉两处会在 MSVC 失败的写法：source->name→source->context.name、不存在的 os_time_msec()→os_gettime_ns()/1000000。本机 git apply --check 与 patch -p1 通过，容器内 -fsyntax-only 全绿，native-host Python 测试全绿。已按新基线 rebase 并推送 #70 d772808、#71 cd3dd2f、#74 42bc704、#75 705fa08、#76 937129b，并派发 rc.61（run 44524750280，soak_minutes=0）。按用户指示：不合并、不跑两小时长稳；TAKE、逐轨增益与完整 NSIS 须在同一轮通过才推进合并与冻结候选。探针开启的同机 CPU/GPU 窗口需在正式对比回执中披露，不当作 OBS 等价证据。
- 证据：gh run 44524750280 = 5.1.0-rc.61 @ 937129b7c759132b7f7f6af632ac72e8bc7dccb2；commit a1af1b9（codex/v51-r3-output）；rebased heads d772808/cd3dd2f/42bc704/705fa08/937129b；pinned OBS fb4d98bf git apply --check 与 patch -p1 通过；Fedora 44 容器（gcc/gcc-c++、Qt6、jansson、simde、uthash）-fsyntax-only exit=0；test_build_contract.py 47/47、test_pixels.py 28（2 skip）；rc.60 回执 /tmp/rc60rec.QsaP
- 源码：`2d4e249652889bce85d6d652ef8d2671fcc6d327`
## #252 · 2026-11-19T20:32:35+08:00 · update

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：rc.60 归因与三层同窗测量已提交 a1af1b9；rc.61 已派发，不合并、不长稳 / rc.60 attribution and three-layer same-window measurement committed at a1af1b9; rc.61 dispatched, no merge and no soak
- 证据：commit a1af1b9; gh run 44524750280 @ 937129b = 5.1.0-rc.61 (soak_minutes=0); 容器内应用补丁后的 libobs/obs-source.c 与 product_window/product_scene/product_scene_libobs_test -fsyntax-only 全部 exit=0；test_build_contract 47/47、test_pixels 28（2 skip）
- 源码：`2d4e249652889bce85d6d652ef8d2671fcc6d327`
## #251 · 2026-11-19T14:45:03+08:00 · log

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：V51-008 | worktree .worktrees/v51 (codex/v51-r3-output) | rc.59 run 44385767337 @ a5337f8 | failurePhase program-track-controls | 本轮只验证逐轨增益。结论：不是混音增益缺陷——回执同一文件内 432.2/2164.5=0.1997，说明第二轨被线性缩放 0.2 且第一轨未受影响；两轨都为 1.0 的对照低到 0.58/0.38，原因是门禁在录制文件前 3 秒做相关测量，那段仍含 owned 混音器 adelay 与后到音频轨的前导静音。产品混音图未改。修复只在测量层：pixel_windows 新增 steady_tone_window()（跳过前导静音、要求半窗一致 ±25%，无连续窗口以实测数值失败），隔离/静音/增益都改用它，并新增同配置二次录制的 1.0→1.0 对照（0.8–1.25）；原阈值不变。本机 Fedora 复现 1250/1850ms 前导静音得 1.63/0.50，与 rc.59 的 1.716/0.522 同形；稳态窗口回到 1.000/0.200；写错轨(0.2)与忽略增益(1.0)仍被判失败；全静音报无连续窗口。test_build_contract 47/47、test_pixels 28/28（2 跳过）。已派发 rc.60 run 44474401536 @ 3c9d6f67591aece94a69a8c5d7bc2beeadc4f8cd（product_mode/complete，soak 0）。 / Diagnosis: mixer gain was correct (0.1997 in the same file); the reference window held lead-in silence. Fix confined to the measurement layer plus a 1.0-to-1.0 control; thresholds unchanged; rc.60 dispatched.
- 证据：run 44385767337 receipt programTrackGain {1261.6,828.1}/{2164.5,432.2}; local Fedora reproduction with the product graph; native-host/tests/test_pixels.py AudioWindowContractTests 4/4; run 44474401536 queued at 3c9d6f6
- 源码：`b99027bb2dcc4f1c28ff2359e5818085a795da8f`
## #250 · 2026-11-19T14:37:29+08:00 · claim

- Agent：`qwen38-next-v51-20261119-01`；任务：`V51-008`
- 记录：V51-008 | worktree .worktrees/v51 (codex/v51-r3-output) | rc.59 run 44385767337 @ a5337f8c205180de1f45ec5f6276ec84d44eb287 | failurePhase program-track-controls | 本轮只验证：逐轨增益 1.0→1.0→0.2 对照，先区分录制启动窗口波动与真实轨道增益缺陷。 / Handover taken from the retired session; this round only tests the 1.0 to 1.0 to 0.2 gain control and whether the drift comes from the recording start window instead of the mixer.
- 证据：python3 scripts/v51-ci-gate.py 44385767337 --sha a5337f8... --version 5.1.0-rc.59 → result inspect-first-failure; gainOne 440=1261.6 880=828.1; gainPointTwo 440=2164.5 880=432.2
- 源码：`b99027bb2dcc4f1c28ff2359e5818085a795da8f`
## #249 · 2026-11-19T14:37:25+08:00 · release

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：原会话退出，按用户指示交接 V51-008 给本地 Qwen 会话；当前失败点为 rc.59 program-track-controls。 / Retiring the departed session claim for V51-008 so the local Qwen session can take it over; current failure is rc.59 program-track-controls.
- 证据：run 44385767337 receipt native-product-entry-ui.json phase=program-track-controls
- 源码：`b99027bb2dcc4f1c28ff2359e5818085a795da8f`
## #248 · 2026-11-19T14:05:18+08:00 · update

- Agent：`codex-qwen-handoff-20261119`；任务：`HANDOFF-005`
- 记录：后续由本地 Qwen 3.8 Next 接手。新增 Qwen 手册和只读 CI 检查脚本。真实 rc.59 run 44385767337 已失败于 program-track-controls，NSIS 未执行；旧任务认领原样保留，按手册交接。
- 证据：docs/coordination/V51-QWEN-RUNBOOK.md；scripts/v51-ci-gate.py 对 rc.59 实测退出 3 并输出失败断言和双频幅度；模拟验证进行中、安装检查、两小时缺失、长稳通过、错 SHA、失败回执、缺 portable 回执的编译失败；git diff --check 通过
- 源码：`b99027bb2dcc4f1c28ff2359e5818085a795da8f`
## #247 · 2026-11-19T14:01:07+08:00 · claim

- Agent：`codex-qwen-handoff-20261119`；任务：`HANDOFF-005`
- 记录：仅提交接手指南、项目入口和只读 CI 检查工具的变更；原开发任务归属另外交接
- 证据：无新增验收证据
- 源码：`b99027bb2dcc4f1c28ff2359e5818085a795da8f`
## #246 · 2026-11-19T14:01:07+08:00 · add

- Agent：`codex-qwen-handoff-20261119`；任务：`HANDOFF-005`
- 记录：用户指定后续本地 Qwen 3.8 Next 接手，要求详细流程和 harness 控制
- 证据：无新增验收证据
- 源码：`b99027bb2dcc4f1c28ff2359e5818085a795da8f`
## #245 · 2026-11-19T04:02:29+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：rc.59 已派发并处于 OBS 编译阶段（run 44385767337，sha a5337f8，含 #67→#76 全栈）；等待期间对四个尚无 Windows 证据的安装态门禁做了静态预审：导入入口文本断言由 stage_product_runtime.py 复制的 migrate-legacy.cmd 满足（含 %LOCALAPPDATA%\WebOBS\Native\config、--confirm-stopped、--include-backup-key）；会话库 config/auth-sessions.db 不在 migrate_legacy 的 DATABASES 列表内，因此旧 cookie 在导入档必为 401；supervisor.prepare 在持有独占锁后、创建 config/native-profile 之前调用 recover_interrupted_restore，且 encrypted_backup 仅在 SodiumStream 实例化时才加载 libsodium；无私网 IPv4 时 plan 仍 enabled=true 且 start_lan_switch 无条件启动，故 LAN 降级分支可成立；complete 且 soak=0 时 job 超时 180 分钟。 / rc.59 dispatched (run 44385767337, sha a5337f8, full #67→#76 stack) and compiling OBS; while waiting I statically pre-reviewed the four install-gate suites that still lack Windows evidence.
- 证据：gh run 44385767337; native-host/scripts/migrate_legacy.py DATABASES; native-host/scripts/product_supervisor.py prepare()/recover_interrupted_restore(); native-host/scripts/product_lan.py plan(); .github/workflows/windows-obs-native-host.yaml timeout-minutes
- 源码：`a0377c781ccaa725ba32c604c09c72fd4b2e52da`
## #244 · 2026-11-19T03:57:12+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：rc.58（run 44380596633，sha 99b6734）证明 RTMP 发布链路可用：门禁推进到 program-publish-disconnect，Program 以回环 RTMP 发布、RTSP 回读双音 AAC、WHEP 端点应答、杀掉私有中继后报告 publish- 断开并在新端口重启；唯一失败为 recovered publisher is not readable by a real consumer，原因是恢复后只单次 ffprobe，而中继路径需等关键帧才 ready（首次推流本来就有 30 秒有界重试）。已在 92238a3 让恢复后的播放 URL 走同一有界重试并要求至少 10 个解码帧（回执新增 publishReplayFrameCount），未放宽任何断言。随后把 #70→#76 重新变基（73abac5/543cae6/9bb6962/89d7238/a5337f8）并从 #76 头派发 rc.59（run 44385767337，完整栈：Program 输出、成对备份恢复、LAN 入口、设备操作、旧数据导入）。NSIS 安装态门禁在 rc.58 因先前失败被跳过，LAN 与成对恢复仍无 Windows 证据。/ rc.58 proved the RTMP publish chain works: the gate reached program-publish-disconnect with RTSP AAC read-back, an answering WHEP endpoint and a publish- disconnect plus restart on fresh ports; the only failure was a single post-recovery ffprobe against a relay path that is readable only after a keyframe, fixed in 92238a3 with the same bounded retry plus a ten-frame requirement. The stack was rebased and rc.59 (run 44385767337) was dispatched from the full stack head a5337f8. The NSIS install gate was skipped in rc.58, so the LAN entry and paired restore still lack Windows evidence.
- 证据：rc.58 receipt failurePhase program-publish-disconnect / lastCheckpoint program-publish-disconnect-reported; fix commit 92238a3; rc.59 run 44385767337 sha a5337f8
- 源码：`a0377c781ccaa725ba32c604c09c72fd4b2e52da`
## #243 · 2026-11-19T03:28:28+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：rc.57 回执直接证实两处根因：中继现已就绪并分配动态端口（streamPublishUrl=127.0.0.1:58303、streamPlaybackUrl=rtsp://127.0.0.1:58302/program，不再出现 mediamtx-timeout），但 streamError=stream-service-unavailable，因为固定 Windows OBS 构建的禁用插件清单含 obs-webrtc，whip_custom/whip_output 不存在。同一回执还证明默认总线 Program 录像真实可用：Program 20261118-191832.mp4 17,446,129 B、41 秒、mask=1、低于 600Hz RMS 1378.5、高于 660Hz RMS 908.8。已取消该 run（后续门禁必然在同一处失败）并从 #74 头 99b6734 派发 rc.58（run 44380596633，complete=true、soak=0、measure_obs_baseline=true、upgrade_previous=true），验证 RTMP 发布、成对备份恢复与 LAN 入口。/ The rc.57 receipt proves both root causes: the relay is now ready with dynamic ports (publish 127.0.0.1:58303, playback rtsp 58302, no mediamtx-timeout) while streamError=stream-service-unavailable because the pinned Windows OBS build disables obs-webrtc, so whip_custom/whip_output do not exist. The same receipt also shows a real default-bus Program MP4 (17,446,129 bytes, 41 s, mask 1, 1378.5 below 600 Hz and 908.8 above 660 Hz). Cancelled that run and dispatched rc.58 (run 44380596633) from #74 head 99b6734 to validate RTMP publishing, paired backup restore and the LAN entry.
- 证据：run 44374662264 artifact native-product-integration-receipts-5.1.0-rc.57 (failurePhase program-streaming, streamError stream-service-unavailable); rc.58 run 44380596633 sha 99b6734
- 源码：`1c3875fada7c561e153a8e936a01919f8df0d5ab`
## #242 · 2026-11-19T03:16:24+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：Program 发布传输收敛为回环 RTMP：固定 Windows OBS 树以 -DENABLE_WEBRTC=OFF 构建且锁定 vcpkg 无 LibDataChannel，安装态没有 whip_custom/whip_output（rc.16 运行时清单有 rtmp-services.dll/obs-outputs.dll，无 obs-webrtc.dll），故下一次失败是 stream-service-unavailable。现用 rtmp_custom+rtmp_output+ffmpeg_aac 发布到同一按需私有 MediaMTX，中继对外 RTSP+WHEP；发布 URL 无 app 段、key=program，用固定 v1.18.2 实测路径为 program（RTSP 回读 h264+aac，视频包持续前进），带 app 段则变成 program/program 且中继关闭发布。门禁新增传输=WHEP 端点应答断言，构建契约拒绝 whip_* 并要求 rtmp_*，本机 47/47 通过。OBS 侧 WHIP 直推仍记为缺口。/ Program publishing now uses loopback RTMP (rtmp_custom+rtmp_output+ffmpeg_aac) into the same private relay because the pinned Windows OBS tree builds with -DENABLE_WEBRTC=OFF and the locked vcpkg archive has no LibDataChannel, so whip_custom/whip_output do not exist in the installed host; verified against the pinned relay that a URL without an app segment plus key program maps to path program (RTSP reads h264+aac) while an app segment produced program/program and the relay closed the publish. Gate adds transport and WHEP-endpoint assertions, build contracts now refuse whip_* and require rtmp_*, 47/47 pass locally; direct OBS WHIP stays a documented gap.
- 证据：PR #67 head b003ae7; run 44374662264 in progress (rc.57, sha 738a62a)
- 源码：`7749d77e05942dda0441aa7c6bcb338ce93c0c0d`
## #241 · 2026-11-19T02:55:31+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-010`
- 记录：共用停机助手 window_close 由本任务维护，供安装态门禁复用
- 证据：无新增验收证据
- 源码：`544bb39a11b49eba982d5cbb6f7e18dc60773fba`
## #240 · 2026-11-19T02:55:24+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-014`
- 记录：window_close 助手归属 V51-010，本任务只复用
- 证据：无新增验收证据
- 源码：`544bb39a11b49eba982d5cbb6f7e18dc60773fba`
## #239 · 2026-11-19T02:55:12+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-014`
- 记录：门禁实跑前的两处停机/Origin 修正
- 证据：无新增验收证据
- 源码：`544bb39a11b49eba982d5cbb6f7e18dc60773fba`
## #238 · 2026-11-19T02:55:12+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-014`
- 记录：旧数据导入门禁两处会在首次实跑即失败的写法已修正：停机改为 WM_CLOSE 正常退出；认证后的每个请求都带产品自身 Origin（控制服务校验携带的 Origin，浏览器/产品 UI 都带）。同时确认导入器/DB 清单与 API 形状一致：accounts 在 cluster.sqlite3、cameras.db/events.db/nvr.json 在迁移清单内，auth-sessions.db 故意不迁移。
- 证据：提交 e547301→rebase 后 817ee88（PR #76）；py_compile 通过；门禁尚未实跑
- 源码：`544bb39a11b49eba982d5cbb6f7e18dc60773fba`
## #237 · 2026-11-19T02:55:12+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-010`
- 记录：安装态 LAN 门禁的停机方式修正：webobs-wall.exe 的 Job 是 KILL_ON_JOB_CLOSE，terminate 启动器会连带杀 supervisor，有序停机与 phase stopped 回执不会发生；改为向产品主窗口投递 WM_CLOSE（新增共用 native-host/tests/window_close.py），仍断言 phase stopped 与进程回收。
- 证据：提交 1136cdf（PR #71），py_compile 通过；门禁仍只在 Windows 安装态实跑
- 源码：`544bb39a11b49eba982d5cbb6f7e18dc60773fba`
## #236 · 2026-11-19T02:55:12+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：rc.56（run 44373450534）派发后在下线前取消：其树仍含旧的启动器硬杀停机代码，安装门禁必然在 installed-legacy-import/installed-lan-entry 失败。改从含修复的 #74 头 738a62a 派发 rc.57。
- 证据：run 44373450534 conclusion=cancelled；run 44374662264 in_progress sha 738a62a
- 源码：`544bb39a11b49eba982d5cbb6f7e18dc60773fba`
## #235 · 2026-11-19T02:55:12+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：program-streaming 的 mediamtx-timeout 根因确认并修复：私有中继配置写了 logDestinations: [stderr]，固定 MediaMTX v1.18.2 只接受 stdout/file/syslog，启动即 ERR: invalid log destination: stderr 退出；等待循环用 QProcess::state() 判退出，而该状态只在事件循环更新，UI 动作内的阻塞等待看不到，于是只报 timeout 且丢掉中继日志。
- 证据：本机用同一 v1.18.2 二进制复现：改前 ERR+exit1，改后 API/RTSP/WHIP 就绪且 WHIP 返回真实握手错误；test_build_contract.py 46 项通过；提交 ea2d704（PR #67）
- 源码：`544bb39a11b49eba982d5cbb6f7e18dc60773fba`
## #234 · 2026-11-19T02:12:46+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-014`
- 记录：补充 f2df106/2512b58：NSIS 安装门禁现在用同一个 IShellLinkW Unicode 读取器逐一验证三个辅助入口快捷方式（导入旧数据、检查更新、恢复备份）存在、目标真实存在且指向本次安装目录内的 MIGRATE-LEGACY.cmd / CHECK-UPDATES.cmd / RESTORE-BACKUP.cmd，并把 helperEntryShortcutsQualified 写入 NSIS 回执。
- 证据：本机无法运行 pwsh，PowerShell 接线需在 Windows 安装门禁首次执行时验证；NSIS 源 WebOBSProductIntegration.nsi 第 88-92 行确认三个快捷方式只在 COMPLETE 构建创建，门禁也只在 complete 阶段运行。
- 源码：`7aa74da29934f0e118aaa1b472d02e2d87740e05`
## #233 · 2026-11-19T02:11:41+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：rc.53（run 44364213218）未到达 UI 门禁：MSVC C2039 指出投影聚合循环把 std::unique_ptr<ProjectorView> 当作值使用（view.graph）。修复为 view->graph（提交 a33b267）。同时撤销我上一版把回环 flow 改为“最旧 pts 前进”的规则（提交 8b09fa3）：fixture 用 -re -stream_loop -1 -c copy，循环处时间戳会回绕，且 MediaMTX 会向新读者吐出环形缓冲，健康路径同样可能给出不变或负的时间戳；若据此重启健康的发布进程，产品会重连并重新出帧，可能掩盖真实解码停滞。现在只有“两次新读取都为空”才算发布方故障（本机 MediaMTX 1.18.2 实验证实杀进程后 [0,0]），包数与最新时间戳仅作证据。派发 rc.55（run 44366851677，soak 分支 5b8a9ac）。
- 证据：run 44364213218 编译日志 11_Compile…txt 第 2914/2918 行 C2039；本机 python3 -m py_compile 通过；rc.54 run 44366334192 已取消（含不可靠的 pts 规则）；栈头 8b09fa3/7169e21/985226a/5b8a9ac/f78e76e/bc7dc97。
- 源码：`a3dc48a4d9c96d1ed30114ed3ef7c2624f10ca56`
## #232 · 2026-11-19T02:07:03+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-014`
- 记录：新增安装态门禁 native-host/tests/legacy_import_windows.py 并接线 NSIS 安装门禁 installed-legacy-import + 回执上传，提交 d9c8c0f 已开 PR #76（基线 #75 427cde6）。门禁把“包内 importer=受审脚本”“MIGRATE-LEGACY.cmd 指向产品数据根”“旧安装→导入→新安装登录/保留/拒绝覆盖/会话失效/进程回收”写成可证伪断言。
- 证据：本机：python3 -m py_compile 通过；workflow YAML 解析通过且回执清单含 native-product-legacy-import.json；无 pwsh 本机，PowerShell 接线需在 Windows 运行验证；门禁尚未执行，未记为通过。
- 源码：`85bce74c10bb32c8e6d1ffe7602d9bbc5964005a`
## #231 · 2026-11-19T02:05:57+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-014`
- 记录：V51-014 承接安装脚本与工作流的旧数据导入接线（V51-007 已提交其恢复门禁部分）；门禁脚本与文档同步在本 PR。
- 证据：无新增验收证据
- 源码：`85bce74c10bb32c8e6d1ffe7602d9bbc5964005a`
## #230 · 2026-11-19T02:05:57+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：收窄 V51-007 范围：#70 的恢复门禁与其安装脚本/工作流接线均已提交（03f877c、9d00b7f），本任务剩余工作只在备份/恢复模块；把 desktop/scripts/test-native-product-install.ps1、.github/workflows/windows-obs-native-host.yaml 与 docs/windows-native-feature-parity.md 三条路径交还给协调，由 V51-014 在同一 Agent 内做旧数据导入接线，避免同一文件两个进行中声明。
- 证据：无新增验收证据
- 源码：`85bce74c10bb32c8e6d1ffe7602d9bbc5964005a`
## #229 · 2026-11-19T02:02:16+08:00 · claim

- Agent：`deepseek-v51-20261118-01`；任务：`V51-014`
- 记录：重新认领 V51-014（范围已收窄为新增门禁与文档），开始实现。
- 证据：无新增验收证据
- 源码：`57e65dc8e9eddf130f0ee023019d1edee5a62adc`
## #228 · 2026-11-19T02:02:16+08:00 · claim

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：重新认领 V51-007：#70 备份一致性继续由本 Agent 负责，范围与之前一致。
- 证据：#70 head 9d00b7f 已 rebase 到 #67 2004cf3；本机 test_complete_supervisor.py PASS。
- 源码：`57e65dc8e9eddf130f0ee023019d1edee5a62adc`
## #227 · 2026-11-19T02:02:16+08:00 · release

- Agent：`deepseek-v51-20261118-01`；任务：`V51-014`
- 记录：收窄范围后立即重新认领 V51-007，恢复其对安装脚本与工作流文件的持有（#70 仍在评审）。
- 证据：无新增验收证据
- 源码：`57e65dc8e9eddf130f0ee023019d1edee5a62adc`
## #226 · 2026-11-19T02:02:16+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-014`
- 记录：范围限定为新增门禁脚本与其文档；NSIS 安装门禁与回执上传两条路径仍由 V51-007 持有，接线提交将在 #70 合入 dev 后补入。
- 证据：无新增验收证据
- 源码：`57e65dc8e9eddf130f0ee023019d1edee5a62adc`
## #225 · 2026-11-19T02:02:16+08:00 · claim

- Agent：`deepseek-v51-20261118-01`；任务：`V51-014`
- 记录：认领 V51-014 并开始编写 native-host/tests/legacy_import_windows.py：已安装入口建立旧账号/设备/事件→包内导入→新档案登录与保留→拒绝覆盖→无残留进程。
- 证据：基线 codex/v51-r3-005-devices @ 427cde6；rc.53 run 44364213218 正在验证解码计数修复。
- 源码：`57e65dc8e9eddf130f0ee023019d1edee5a62adc`
## #224 · 2026-11-19T02:02:16+08:00 · release

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：为消除与 V51-014 的文件范围冲突，临时释放 V51-007（同一 Agent 顺序处理，随后立即重新认领；#70 分支与提交保持不变）。
- 证据：无新增验收证据
- 源码：`57e65dc8e9eddf130f0ee023019d1edee5a62adc`
## #223 · 2026-11-19T02:01:47+08:00 · add

- Agent：`deepseek-v51-20261118-01`；任务：`V51-014`
- 记录：登记安装态旧数据导入验收：R4-001 因依赖 R2-002 未完成无法认领，故把“已安装完整产品上的旧数据导入入口与保留”单列为 V51-014，范围只含新增门禁、NSIS 接线、回执上传与文档，不改迁移脚本本体。
- 证据：test_migrate_legacy.py 本地 PASS；安装包文件清单含 MIGRATE-LEGACY.cmd；尚无安装态导入回执。
- 源码：`57e65dc8e9eddf130f0ee023019d1edee5a62adc`
## #222 · 2026-11-19T01:57:10+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：提交 2004cf3：产品快照改为在快照时刻读取各 Scene 自有 video_progress() 原始解码计数（缺计数记为 -1，不再冒认“冻结”），心跳缓存值降级为 healthSerial 仅供界面标签；LoopbackRtsp.path_progress() 改用两次新读取的最旧包 pts 前进判定 flow（rc.52 里两个样本都返回 11/11 包但产品侧全部停滞，说明计数不可作证）。#67→#70→#71→#74→#75 已按旧基线重排并推送（9d00b7f/d5bd146/d5a39dd/427cde6）。派发 rc.53（run 44364213218，soak 分支 d5a39dd，product_mode/complete/upgrade_previous/measure_obs_baseline，soak_minutes=0）验证该修复。
- 证据：run 44356064395 receipts /tmp/rc52.Vf3r；本地 MediaMTX 1.18.2 验证：活路径 oldestPts 3600→14791 flowing=true，杀发布进程后 packets=[0,0] flowing=false；py_compile 通过；native-host/tests/test_build_contract.py 45 OK
- 源码：`4459100339745f675d0d14528d5fce4670a0af51`
## #221 · 2026-11-19T01:23:04+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：继续 Program 输出验收。
- 证据：无新增验收证据
- 源码：`baf033540fd90e0b4a006562fa40c9fddc0d9cda`
## #220 · 2026-11-19T01:23:04+08:00 · claim

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：重新认领：Program 输出验收与像素/回环门禁证据，包含 39c43fd 的回环恢复修复。
- 证据：python3 -m py_compile native-host/tests/product_windows.py；native-host/tests/test_build_contract.py 45 OK；native-host/tests/test_complete_supervisor.py PASS
- 源码：`baf033540fd90e0b4a006562fa40c9fddc0d9cda`
## #219 · 2026-11-19T01:23:04+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-013`
- 记录：协调后调整声明范围：native-host/tests/product_windows.py 的门禁改动归同一 Agent 的 V51-008 持有，本任务声明合成设备与相机注册表测试文件；实现同在一个 PR。
- 证据：PR #75 head c19bcda
- 源码：`baf033540fd90e0b4a006562fa40c9fddc0d9cda`
## #218 · 2026-11-19T01:23:04+08:00 · claim

- Agent：`deepseek-v51-20261118-01`；任务：`V51-013`
- 记录：已实现并提交为 PR #75（分支 codex/v51-r3-005-devices，head c19bcda，base #74）：抽出共享合成 ONVIF 设备 tests/onvif_device_emulator.py；安装态门禁新增 complete-business-device-operations 相位，实跑 probe(authenticated/credentialsExtracted/含 snapshot profile)、camera 创建 201 且文档不含口令、onvif/sync、预置位列表、连续 PTZ autoStopMs=350 且设备实际收到 PT0.350S、定时 Stop 到达设备、SetPreset/GotoPreset、快照 content-type 与 sha256；再以 camera 作用域 viewer 取得 403，并证明拒绝窗口内控制面未出现任何 PTZ/预置位/快照 SOAP 动作且合成设备 snapshot_reads 未增加；最后删除相机并刷新回 5 路。
- 证据：python3 tests/test_camera_registry.py 58 OK；合成设备冒烟：三个 profile(含 snapshot)、sync、presets [preset-1]、moved state accepted/autoStopMs 350/deviceTimeoutMs 350、ptz_moves PT0.350S、自动停止到达设备、preset-created、goto accepted、快照 image/jpeg；Windows 安装态证据待后续 rc 运行；合成 SOAP 设备不等于真机验收
- 源码：`baf033540fd90e0b4a006562fa40c9fddc0d9cda`
## #217 · 2026-11-19T01:23:04+08:00 · release

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：临时释放以便消除与 V51-013 的声明范围重叠；任务仍在进行，稍后重新认领。
- 证据：见上一条 revision 216 日志
- 源码：`baf033540fd90e0b4a006562fa40c9fddc0d9cda`
## #216 · 2026-11-19T01:22:23+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：rc.51(run 44349201714)在 program-before-take 暴露第六路 Program 专用静音源 serial 恒为 0；同时发现两处回环修复路径用 UI video-progress 标签（只允许 1..5 路且需已收帧等于路数）证明恢复，Program 相位必有 6 路输入因此该修复必然抛错。已在 #67(39c43fd)改为用 LoopbackRtsp.path_progress 包数与逐输入帧计数器在实测 2.5s 窗口内推进来证明，blank 相位只证包流；未削弱任何像素/帧断言。rc.52(run 44356064395, 4a487d1)仍在跑，将给出停滞输入名与逐路包数。
- 证据：python3 -m py_compile native-host/tests/product_windows.py；native-host/tests/test_build_contract.py 45 OK；native-host/tests/test_complete_supervisor.py PASS；分支链已 rebase 并强推：#67 39c43fd → #70 84c9302 → #71 89ec20a → #74 b03008d → #75 c19bcda
- 源码：`3ddaacb3c835d589f413803180d06a2f7fb05c8d`
## #215 · 2026-11-19T01:14:36+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：按新 #67 head 顺序 rebase：#70=307910f、#71=2560a52、#74=4a487d1，均 --force-with-lease 推送；rebase 后本机复跑 tests/test_encrypted_backup.py 12 OK 与 native-host/tests/test_complete_supervisor.py PASS（含恢复收敛断言）。
- 证据：307910f/2560a52/4a487d1 pushed; suites re-run green
- 源码：`19695a5dffb571ad4afdcc4d7889b69eb85677f5`
## #214 · 2026-11-19T01:14:33+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：rc.51 回执给出新故障形状：program-before-take 里 Program 专用源 'WebOBS Program fixture-five.fixture-source-4' 连续 30 s 报告 showing/active/mediaState=PLAYING 而 serial 仍为 0，另有已计数输入停滞；旧回执把停滞输入与包计数证据截断，无法区分'合成回环停止推包'与'产品打开但不出帧'。因此给 #67 门禁增加判定与证据而不放宽像素断言：等待窗口失败后先实测五条回环路径（发布进程状态、ffprobe 可读性、两次包计数），只重启确实停止推包的路径并重新计时（最多两次）；路径仍在推包则直接失败，并把 stagnantInputs（uuid+前后 serial）、完整 videoInputs 快照、发布进程状态与 pathProgress 写进回执；PLAYING 且零回调持续 ≥8 s 判为真实停滞。本机 py_compile + native-host/tests/test_build_contract.py 45 OK + test_complete_supervisor.py PASS；Windows 证据待 rc.52（run 44356064395，ref codex/v51-r5-soak=4a487d1，version 5.1.0-rc.52）。
- 证据：commit 4adff47 (PR #67); receipt /tmp/rc51.NjL1/native-product-entry-ui.json lastCheckpoint pixels-program-before-take-observed programPixelInputWait waitedMs 30077 windows 12 countedInputs 5
- 源码：`19695a5dffb571ad4afdcc4d7889b69eb85677f5`
## #213 · 2026-11-19T01:14:18+08:00 · add

- Agent：`deepseek-v51-20261118-01`；任务：`V51-013`
- 记录：抽共享合成 ONVIF 设备并接入安装态门禁；Linux Registry 58 项仍通过，Windows 证据待回执。
- 证据：PR #75 (codex/v51-r3-005-devices 35134da, base codex/v51-r5-soak); python3 tests/test_camera_registry.py 58 OK; smoke run of probe/sync/presets/ptz/autostop/snapshot green locally
- 源码：`19695a5dffb571ad4afdcc4d7889b69eb85677f5`
## #212 · 2026-11-19T00:50:50+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：审阅 #70 时发现并修掉恢复回滚的半对缺陷：recover_interrupted 的“配置未落盘”分支只把旧配置放回原位，却忽略同一交换窗口里已换出的旧 OBS 档案（journal 记录了 nativeRollback 却从未使用），普通启动因此会读到缺失的 OBS 档案，旧档案永远停在 .webobs-native-rollback-* 无人认领。现在回滚分支成对收回两半；若配置已落盘且后续启动重建了活动档案，改为把这些字节挪到 .webobs-native-parked-* 保存并落下与已落盘配置成对的档案副本（不再报 inconsistent 拒绝启动），恢复失败路径同样改为挪开而非 shutil.rmtree 删除活动档案。本机 tests/test_encrypted_backup.py 12 项通过且去掉本修复两项新测试即失败（可证伪）；安装态门禁 backup_restore_windows.py 新增第二个交换窗口（OBS 档案换出后、配置落盘前）终止真实恢复进程再从安装入口启动，断言两半回到旧对且不再有滞留 parked/rollback。已提交 be25901(#70) 并按顺序 rebase #71=b3653a4、#74=eb1c61f 后推送；rc.51 仍 pinned 在旧栈顶 2e7695d 运行中，不重复派发。剩余：读 rc.51 回执判定 Program 捕获窗口内的冻结槽位成因；两个交换窗口的 Windows 门禁结果需新 run 回执。
- 证据：commit be25901 on codex/v51-r4-backup-consistency; python3 tests/test_encrypted_backup.py 12 OK; same file against HEAD~1 service = 2 errors (falsifiable); test_complete_supervisor/test_native_updater/test_build_contract OK; run 44349201714 in_progress
- 源码：`29df4501720ebcd82b43f55cafa4c39a39194d27`
## #211 · 2026-11-19T00:37:12+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：rc.50(run 44339344891)在 pixels-program-before-take-observed 失败：点名一个 OBS 报告 showing/active/PLAYING(mediaState=1) 但 serial 始终为 0 的输入(stalledMs=1370)。宿主每 2s 刷新一次逐输入健康，stalledMs 只能按 2s 刻度变化，且刚创建的 Program 专用源在媒体打开前 serial 必为 0，两者都不是画面冻结，旧计数器门无法判定。已提交 a92d11b(#67 codex/v51-r3-output)：等待改为实测推进(两次≥2.5s 快照必须出现更新的帧计数，仅覆盖已真正计过帧的输入)，零帧/仍在打开的输入改为记录并命名；状态快照新增 name/removed；回执新增 inputWaitLogLines(点名该输入的 OBS 日志行/MP: 行)、fixtureServerLogTail(脱敏 MediaMTX 推流日志尾部)与更多 media_playback 标记。已按顺序 rebase #70(78e8b60)→#71(3147f40)→#74(2e7695d) 并推送，从栈顶 codex/v51-r5-soak 派发 rc.51 run 44349201714(product_mode=true,complete=true,measure_obs_baseline=true,upgrade_previous=true,soak_minutes=0)。本地 test_build_contract 45 项、test_product_lan 24 项、test_encrypted_backup 10 项通过；本机无 Qt6/MSVC，C++ 仍以 Windows CI 编译为准。剩余：读 rc.51 回执判定零帧输入到底是哪一层；若仍是产品侧的“打开但静默”，需在宿主加有界重开并如实登记。
- 证据：run 44339344891 receipt native-product-entry-ui.json; commit a92d11b; run 44349201714
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #210 · 2026-11-18T23:46:22+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：定位并修掉 Program 前置等待的自身缺陷：rc.48(run 44332713711 @9a694ce) 与 rc.47(run 44332749108 @447dbba) 都在 program-before-take 等待 20s 超时，回执里可见条目全部 showing/active/mediaState=1、stalledMs 315–1217、serial 980–1028，说明超时来自刚创建、尚未收到第一帧的 Program 自有输入（serial 仍为 0，宿主 2s 心跳才刷新健康计数），不是画面停滞。现在等待只覆盖 OBS 自己报告为 showing/active/PLAYING 的输入，未开播输入只记录；失败消息改为给出原因与被卡条目而非截断原始列表；每个出现的 OBS 启动日志标记另存一行脱敏样例（含 Failed to initialize 究竟指向谁）。同时把栈重基到 dev@4b4e512：#67=6286fd4、#70=c56c9cf、#71=b13deb9、#74=4f38150，并派发覆盖全栈的 rc.50 完整运行。
- 证据：rc.48 receipt artifact(sha 9a694ce,version 5.1.0-rc.46): lastCheckpoint=pixels-program-before-take-observed, programPixelInputWait=null；rc.47(447dbba) 同阶段同症状；重基后本机 test_build_contract/test_product_lan/test_encrypted_backup/test_complete_supervisor/test_native_updater/test_compare_runtime_sizes/test_complete_release_policy 全部 OK；新 run 44339344891 @4f38150 product_mode+complete+measure_obs_baseline+upgrade_previous, soak_minutes=0
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #209 · 2026-11-18T23:21:25+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：#69 分支本地复跑发布链：候选 Tag 取自共享策略、稳定发布需验收 JSON 与 main 祖先、pending/verify-only 不写任何内容；安装包与 latest.yml 大小/SHA-512 一致。待 #67 合入 dev 后 rebase（publish_candidate.py add/add，保留 #69 超集）。
- 证据：python3 native-host/tests/test_candidate_publish.py PASS；test_stable_packaging.py PASS(5.1.0→v5.1 / rc 候选独立)；test_update_manifest.py PASS；tests/test_release_identity.py 8 OK(4 skip)
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #208 · 2026-11-18T23:21:25+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：接续会话核对 rc.46/rc.47 回执后确认：Program 像素停滞发生在捕获窗口内，媒体侧 serial 在窗口内确实推进（+840 帧），因此需要 rc.48(9a694ce) 的 SerialWatch renderFramesPerSecond/renderFramesMaxStallMs 才能区分图形线程停滞与槽位未重绘；同时 rc.47 在 program-before-take 的逐输入推进等待上超时 20s，与 rc.44 的 serial 走平误判同源，若 rc.48 再超时将撤销该前置等待、只保留捕获窗口内证据。
- 证据：rc.46 artifact receipt(run 44323126258): lastCheckpoint=pixels-program-after-take-captured, progressError=Frozen final pixels on slot 2, inputSerialDelta 6/6 advanced, stalledMsAfterCapture 0, publishers alive, stalledPaths empty
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #207 · 2026-11-18T22:20:43+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：e23b8ed：Program 像素阶段捕获前先用宿主自身逐输入健康计数（serial>0 且距上次变化 ≤2s，输入数量取自状态而非写死5）有界 20s 等待并记录 programPixelInputWait；分析失败时新增跨捕获窗口的 inputSerialDelta 与 stalledMsAfterCapture，把‘媒体侧停止供帧’与‘帧已到达但未重绘’分开。不放宽像素断言。重基 #70=7344250/#71=f34c592/#74=7901bc7；重派 rc.46=run 44323126258 @e23b8ed、rc.47=run 44323161102 @f34c592
- 证据：rc.46(5dfcde8,run 44314586162)失败在 program-after-take：Frozen final pixels on slot 5（8 个样本槽位5计数恒为1，temporalProgress=false）；诊断显示 5 个推流全 alive、5 条 RTSP 路径全部 flowing、stalledPaths 为空、宿主对 6 个输入全部 stalledMs=0、wallItems=5/programItems=2、fixture-5 槽位 uuid serial=1037 而同批其他输入 1140-1148。同一 head 的上一次运行(23886e4)同一阶段通过（slot5 计数 5,5,16,16,16,27,27,1），因此这是间歇性且当时无法判定成因
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #206 · 2026-11-18T21:32:22+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：修复 5dfcde8：四个中继监听器全部按空闲回环端口分配、WHIP URL 由分配端口推导、每条拒绝路径都写入 stream_error；移除未使用 port_available；门禁失败信息带宿主 programOutput；test_build_contract.py 新增禁止固定发布端口并要求记录拒绝（45 OK）；product_output.cpp 在固定 libobs 头+Qt6.11 下 g++ -fsyntax-only 通过。已取消旧头 rc.47(44307757343)，重基 #70=2add0cc/#71=8cb5070/#74=88b4e6f 并推送；重派 rc.46=run 44314586162 @5dfcde8、rc.47=run 44314611367 @8cb5070
- 证据：rc.46(23886e4,run 44308229704)两个 Program 像素阶段首次通过、两次录像首次解出双音调（programRecordingBandRms 1387.9/912.4 mask2；programRecordingDefaultBus 1381.6/910.1 mask1；programMixLeadIn 47ms/7328ms/15ms 已披露）；随后停在 program-streaming：programOutput streaming=false、mediaMtxRunning=false、streamPublishUrl 与 streamError 同时为空。定位为私有中继把 WHIP/WebRTC 写死 8889（产品分发网关 MediaMTX 也绑 8889，且 Windows 预留动态端口段可使固定端口在无人监听时不可绑定），拒绝只回给按钮文案，可观察状态看起来像空闲且无失败
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #205 · 2026-11-18T20:54:19+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：发布链验证到待发布状态：Tag v5.1↔版本 5.1.0 单一映射、验收 JSON 缺失/无效拒绝、源码未进 main 拒绝、安装器与 latest.yml 名称/size/sha512 一致；未写入任何 Tag/Release
- 证据：#69 head 21b0d00 已含 dev tip 4b4e512（#68 已合并）且 origin/dev 为其祖先；OBS 子模块固定 fb4d98bf(32.1.2)、go2rtc b5948cfb(v1.9.14) 已初始化；补跑 native-host/tests/test_build_contract.py 44 OK、test_complete_release_policy.py PASS、test_stable_release_identity.py PASS、test_preview_release.py 4 OK、test_component_size_report.py PASS、test_compare_runtime_sizes.py OK、tests/test-immutable-release-assets.sh PASS、test_candidate_publish.py/test_stable_packaging.py/test_update_manifest.py/test_release_identity.py(8, skip4) 全绿
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #204 · 2026-11-18T20:54:19+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-010`
- 记录：rebase 时误用 --onto <upstream>=自身导致分支短暂指向父 head，已用 77958c3..15b1fd1 的 11 个提交恢复完整历史
- 证据：PR#71 rebase 至 3161e9a（11 个自有提交）；python3 -B native-host/tests/test_product_lan.py 24 OK；rc.47 run 44307757343 在旧 head fabec5d 上仍在跑（同一 product_mode+complete 门禁），最终 dev 候选会再次覆盖
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #203 · 2026-11-18T20:54:19+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：已确认普通产品启动接线满足要求；安装态门禁 backup_restore_windows.py 改为直接启动 bin/webobs-wall.exe 收敛，需 Windows 完整候选运行验证
- 证据：PR#70 rebase 到新 #67 head（770b0e1，4 个自有提交无冲突）；tests/test_encrypted_backup.py 10 OK；native-host/tests/test_complete_supervisor.py PASS（含 'converged the interrupted restore as completed' 与二次 prepare 不被中断日志拒绝、无 run/restore-recovery.json）；复核 product_supervisor.prepare() 顺序：独占锁+protect 之后、创建 config/native-profile 目录与读取 user.ini 之前调用 recover_interrupted_restore()
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #202 · 2026-11-18T20:54:11+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：保留 a864c25 诊断与 cd94df9/4746e0c 混音修复；#70/#71/#74 已 rebase 到新 #67 head 并 force-with-lease 推送
- 证据：revert a4d2512（videoInputs.serial 帧计数门槛在 Windows 上 30s 全部走平而像素阶段本身通过，rc.44 因此误判停滞；像素内容仍是连续性证据）b447c48；23886e4 首次录像与 WHIP 开播前也调用 wait_program_mix_audible；python3 -B 语法 AST OK；rc.46 run 44308229704 @23886e4 product_mode=true complete=true 已派发，旧 head 的 44307720185 已取消以保证被测头与合并头一致
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #201 · 2026-11-18T20:18:16+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：#70 双目录配对恢复分支无代码改动，仅重排到 #67 新头 a4d2512（新头 77958c3）；其安装态门禁 backup_restore_windows.py 与备份恢复回执将在 rc.45 的完整融合运行中一并验证。
- 证据：git rebase a4d2512 clean；codex/v51-r4-backup-consistency=77958c3；gh pr 70 base=codex/v51-r3-output
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #200 · 2026-11-18T20:18:08+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：#69 发布链分支已 rebase 到 dev 尖端 4b4e512（含 #72 组件体积拆分），新头 21b0d00；本地 test_candidate_publish、test_stable_packaging、test_update_manifest、tests/test_release_identity 全部通过，发布链仍只验证到待发布状态、不写任何 Tag/Release。待 #67 合入后再 rebase 到 dev 并转入正式审查。
- 证据：native-host/tests/test_candidate_publish.py PASS；test_stable_packaging.py PASS（v5.1↔5.1.0 与 rc Tag 映射）；gh pr 69 head=codex/v51-publish-chain@21b0d00
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #199 · 2026-11-18T20:18:08+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-010`
- 记录：rc.43(44296848704)在编译步骤的 CTest 中失败于 native-product-lan-switch（“the LAN switch never answered”）。原因不是回环不可达：测试用 3 秒事件循环等待，而 ProductLanSwitch 自身 4 秒期限会中止回复，负载高的 runner 上一次交换可超过 3 秒。修复 a25f44d：先用原始 socket 加事件循环证明 fixture 可达（阻塞式 waitForReadyRead 无法证明，fixture 在 readyRead 中回答）、给每次交换命名并记录 connections/responses、等待预算延长到 6 秒；未削弱任何 fail-closed 断言。Windows 验证 run 44300526460(5.1.0-dev.lanswitch, product_mode=false) 全绿：CTest 11/11 含 native-product-lan-switch。栈已重排 #67 a4d2512 → #70 77958c3 → #71 15b1fd1，并派发 rc.45=44302553239 跑完整融合门禁。
- 证据：gh run 44300526460 conclusion=success；podman v51qt 容器内 Qt6.11 offscreen 运行 product_lan_switch_test 通过；g++ -fsyntax-only -DWEBOBS_NATIVE_PRODUCT_MODE product_window.cpp 无错误
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #198 · 2026-11-18T20:18:00+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：rc.42(44296843744)程序合成阶段首次通过逐输入像素连续性：TAKE 前后五路槽位均推进、sessionBound=true、mediaSources=7、无撤权。新缺口为节目混音建立间隔：混音进程只有在 ffmpeg 打开相机输入后才绑定本地 TCP 端点，媒体源首次打开失败，rc.42 在重连完成前结束默认总线录制，导致唯一音轨两个音调皆缺失（band RMS 0/0）。修复：混音源 reconnect_delay_sec 2→1(4746e0c)；每次 Program 录制前先确认每个可用混音源 mediaState=1 且声明了未静音非零增益输入时峰值高于 -60dBFS，并把实测间隔写入 programMixLeadIn(cd94df9)。另把像素失败诊断并入分支：回环路径包流采样 pathProgress/stalledPaths(a864c25) 与 Program 捕获前逐输入帧计数推进等待(a4d2512)。已派发 rc.44=44302537880 于 codex/v51-r3-output@a4d2512。
- 证据：gh run 44296843744 回执 native-product-entry-ui.json：failurePhase=program-recording-default-bus、programRecordingDefaultBus={below600Hz:0,above660Hz:0,audioTrackMask:1}、obsDiagnosticLines 显示 12:00:14.215 开始写文件、12:00:17.321 MP: Failed to open media、12:00:19.594 Reconnected
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #197 · 2026-11-18T19:18:30+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：#69 发布链分支已 rebase 到 dev 现 tip 并推送；发布链可在不写入任何内容的前提下验证到待发布状态
- 证据：codex/v51-publish-chain head 0b0c7cc；test_candidate_publish/test_stable_packaging/test_update_manifest 本机全部 PASS（Tag v5.1 ↔ 版本 5.1.0 映射由共享策略给出）
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #196 · 2026-11-18T19:17:40+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-012`
- 记录：#72 组件体积拆分已合入 dev（tip 4b4e512），发布说明与矩阵将引用同一次候选运行的 native-product-size-split.json；#73 文档分支已 rebase 到新 dev tip 以免显示为删除 #72 文件
- 证据：docs/release-notes-v5.1.md 候选身份表仍标记待绑定，绑定值将在最终候选 run 与安装包校验后写入
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #195 · 2026-11-18T19:17:39+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-011`
- 记录：#74 长稳分支已同步到 #67 的 535a9af 并推送；R5-001 认领被依赖未完成阻挡，本轮先在自有任务记录进度
- 证据：codex/v51-r5-soak head f741497（3 个提交 rebase 无冲突）；native-host/tests 全部本机可跑项通过，仅两个需要 --probe 的 Windows 探针脚本按要求跳过
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #194 · 2026-11-18T19:08:19+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-010`
- 记录：LAN 开关回归两处修正：Qt 把原始头名规范化为 X-Webobs-Native-Token（HTTP 头名不区分大小写，接收侧 Python/beast 本就不区分），改为整体小写比较并校验自身 Origin 与无 Cookie；不可读 2xx 仍返回 0 保留上次回执，真实 HTTP 错误（含 HTML 500、401）如实上报，使界面能区分拒绝与无响应
- 证据：02b3ff2；容器内 Qt 6.11 下 native-product-lan-switch-test PASS；test_product_lan.py 24 项 OK
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #193 · 2026-11-18T19:08:19+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：#70 已复核：prepare() 先取 run/native-owner.lock、保护目录、收敛恢复日志，之后才创建 config/native-profile 与 user.ini；Windows 安装态回归覆盖两次目录交换之间 kill、真实已安装入口首次启动收敛成对、可重试、回滚对保留、仅含配置的旧归档保留原生档案
- 证据：rebase 后 PR #70 head 4d60479（base #67 535a9af），native-host/tests/backup_restore_windows.py 由 workflow 步骤执行，证据待 rc.41 run 44291812392
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #192 · 2026-11-18T19:08:19+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：定位 rc.36/rc.37 在 native-program-take 失败的真实原因：2 秒授权续期在最忙时被中止，产品把任何非 200 当作会话撤销并拆掉预览与投影，导致 window-identity/冻结像素；已改为繁忙/超时（0/408/429/500/502/503）最多重试两次后失效关闭，401/403、设备版本或场景指纹变化仍立即锁，续期超时提到 6 秒对齐服务端 10 秒预算
- 证据：535a9af（PR #67）新增 lastLock/lockCode/renewTransient 分类，门禁在像素采集前直接报告撤销类别；Windows rc.40 run 44291675017 已派发在 codex/v51-r3-output 验证
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #191 · 2026-11-18T18:27:25+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：rc.36(run 44280347568) 失败点已定位：native-program-take 的 program-after-take 最终像素 8 帧里 slot 4 计数器 38 冻结、temporalProgress=false、progressError=Frozen final pixels on slot 4，同时宿主 verify-video-input-progress 也报停滞；该槽位由合成回环 RTSP 推流提供（带 B 帧 HEVC、-c copy、-stream_loop -1），ffmpeg 会在循环中因时间戳问题自行退出，因此不能判定为产品解码缺陷。已提交 c250c85：像素门禁采集前先检查五个推流进程状态并重启已退出者、重新要求五路全部推进后再采集，事件写入 fixturePublisherWatch；像素分析仍失败时记录 pixelFailureDiagnostics(阶段/角色/progressError/进程状态/五个回环路径可读性)，仅在确有死进程或不可读路径时重启并重跑同一像素阶段一次；夹具健康而像素停滞仍判失败。并行派发 rc.37(run 44285491534, c250c85, #67 单独) 与 rc.38(run 44285510872, 65cddb9, #67+#70+#71 组合，product_mode+complete+pixel_test=false)。#70 rebase 到 c250c85 干净；#71 rebase 需手工并集解决 product_window.cpp 支持包字段(programApply 与 lan 同时保留)，本机 test_product_lan/test_build_contract 通过。长稳门禁分支 codex/v51-r5-soak 已 rebase 并推为 PR #74。
- 证据：run 44280347568 failed; commit c250c85; runs 44285491534/44285510872
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #190 · 2026-11-18T18:04:24+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：rc.36(1be9c2f, run 44280347568) 仍在执行，等待结果后再合并 #67。已核对 #70 head 296f2bc：prepare() 在取得 run/native-owner.lock 并 protect(root) 之后、创建 config/native-profile 与读 user.ini 之前调用 recover_interrupted_restore()，满足“普通产品启动即收敛中断恢复”。修正派发口径：build-obs-native.ps1 规定 ProductMode 与 PixelTest/SmokeTest 互斥，完整候选必须 pixel_test=false（先前计划的 pixel_test=true 会在编译步骤直接抛错）；measure_obs_baseline/upgrade_previous 仅非 product 路径生效，同机 OBS 体积对照由 #72 存储参考与 size-split 回执承担。docs 分支 codex/v51-docs(f967634) 写了候选发布说明与矩阵 AUDIO/OUTPUT/REMOTE/OPS/BACKUP/LIFE 更新，其中托盘后台输出标为源码接线但 CI 无系统托盘未自动化。
- 证据：run 44280347568; branch codex/v51-docs@f967634; commit 296f2bc
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #189 · 2026-11-18T17:59:39+08:00 · claim

- Agent：`deepseek-v51-20261118-01`；任务：`V51-012`
- 记录：接手撰写 v5.1 候选发布说明与矩阵更新 / take over the v5.1 candidate notes and matrix update
- 证据：无新增验收证据
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #188 · 2026-11-18T17:59:32+08:00 · add

- Agent：`deepseek-v51-20261118-01`；任务：`V51-012`
- 记录：先写内容框架，实机与候选回执数字在候选冻结后绑定 / draft content now, bind candidate receipts at freeze
- 证据：无新增验收证据
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #187 · 2026-11-18T17:59:03+08:00 · claim

- Agent：`deepseek-v51-20261118-01`；任务：`V51-011`
- 记录：安装态长稳门禁已实现于组合预览树 f0eb858，待 #67 合入后转 PR / installed soak gate implemented in the preview tree, PR after #67 merges
- 证据：无新增验收证据
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #186 · 2026-11-18T17:55:04+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：定位 rc.34 的真实失败：门禁在 wait_for 调用点立即格式化失败信息，而 programDefaultBusApplyAttempt 只在第一次探测写入，导致 KeyError 在进入等待前崩溃，完全掩盖 apply 结果；wait_for 现接受可调用 message 并在超时时组装，默认总线信息改用 .get 保留 core/host 两侧证据
- 证据：rc.34 run 44275460558 failurePhase=program-recording-default-bus, failureDetail=KeyError: 'programDefaultBusApplyAttempt'（lastCheckpoint=program-recording-audio-decoded，说明双音轨录像解码已通过）；修复提交 1be9c2f 已推送，rc.36 run 44280347568 在其上派发
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #185 · 2026-11-18T17:49:13+08:00 · add

- Agent：`deepseek-v51-20261118-01`；任务：`V51-011`
- 记录：工作流开关与安装脚本参数已在 codex/v51-r5-soak；本任务补上门禁本体，避免把工作流参数当成已完成长稳
- 证据：试合并工作树 .worktrees/v51-combined 提交 f0eb858：py_compile 通过、test_build_contract.py 44 OK
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #184 · 2026-11-18T17:45:12+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：审阅 #70：recover_interrupted_restore() 确实在 prepare() 内、run/native-owner.lock 独占加锁与 protect 之后、创建 config/native-profile 与读取 user.ini 之前调用；restore 成对交换的日志恢复(rolled-back/completed)与不可读日志 fail-closed 均属实
- 证据：.worktrees/v51-combined 试合并后 test_complete_supervisor.py PASS（含 'converged the interrupted restore as completed'）、tests/test_encrypted_backup.py 10 OK、native-host/tests/test_native_updater.py 4 PASS
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #183 · 2026-11-18T17:37:31+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：接续同一会话继续（模型切换，沿用原认领）：rc.35 run 44276526382 正在编译 OBS 前端/插件，作为 #67 head 867c11b 的权威完整运行；rc.34 run 44275460558 为上一提交 a16f1f9 的对照运行
- 证据：rc.33 失败断言 program-recording-default-bus 已由 a16f1f9（读 GET /api/v1/studio/runtime 回执）与 867c11b（瞬时 apply 有限重试 4 次）覆盖；两个运行均为 product_mode/complete
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #182 · 2026-11-18T17:32:25+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：codex/v51-publish-chain@c1e1018：publish_candidate.py 增加 --verify-only，可把发布链验证到‘待发布状态’（全部拒绝逻辑照跑，不写文件、不上传）
- 证据：本机 release 测试全 PASS：test_candidate_publish、test_stable_packaging、test_update_manifest、test_stable_release_identity、test_complete_release_policy、test_preview_release；test_build_contract 44 OK；control-auth CTest 18/18；native-host graph CTest 8/8；固定 OBS 32.1.2 libobs 构建 98/98 + real-loader CTest 1/1
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #181 · 2026-11-18T17:30:34+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：已定位 rc.33 失败是门禁自身缺陷（用了宿主令牌专用的 /api/v1/native/*），改为读 GET /api/v1/studio/runtime 的核心侧宿主 apply 回执；另修 Program apply 一次失败即永久锁死的缺陷（瞬时原因有限重试 4 次，结构性原因仍永久）
- 证据：codex/v51-r3-output@a16f1f9 = run 44275460558 (rc.34)；@867c11b = run 44276526382 (rc.35)；Qt6 + libobs 32.1.2 SDK -fsyntax-only product_window.cpp exit=0；test_build_contract.py 44 OK
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #180 · 2026-11-18T17:27:35+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-010`
- 记录：codex/v51-r3-004-lan@b274bb7：端口占用不再拒绝整个产品启动，改为入口关闭 + 有界原因；本机 24 项契约与 44 项构建契约复跑通过
- 证据：test_product_lan.py 24 OK（含新的 busy-port 用例断言本机回环 Origin 保持、不写 Caddy 文档、failure_reason 仍为空）；test_complete_supervisor.py PASS
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #179 · 2026-11-18T17:26:02+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：codex/v51-r4-backup-consistency@296f2bc：中断交换后改为启动已安装入口（开始菜单目标）自行收敛；并修门禁把成对归档误当仅配置归档的错误，先断言拒绝再验证真正旧版仅配置备份保留现有原生档案
- 证据：本机 python3 -B tests/test_encrypted_backup.py 10 OK；native-host/tests/test_complete_supervisor.py PASS；test_build_contract.py 44 OK（本工作树已初始化 obs/obs-studio 子模块）；backup_restore_windows.py ast 语法校验通过（需 Windows 已安装运行时才能执行）
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #178 · 2026-11-18T17:21:35+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：复核 #70：recover_interrupted() 已在 supervisor.prepare() 内、持有 run/native-owner.lock 之后、创建任何产品目录与读取 config/native-profile 之前调用；backup_restore_windows.py 已存在并接入 NSIS 安装验收与工作流上传
- 证据：codex/v51-r4-backup-consistency@d0b9506：prepare() 顺序为独占锁 → protect → recover_interrupted_restore() → 目录创建/ini；Linux 侧 test_complete_supervisor.py 中断交换契约 PASS；Windows 安装态门禁（两次目录交换之间终止恢复进程 → 从已安装入口再启动 → 成对恢复/可重试/仅含 config 的旧归档保留原生档案）尚未有 CI 回执，不写成通过
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #177 · 2026-11-18T17:21:35+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：在 codex/v51-publish-chain@a39b2c5 上补跑此前缺失的构建检查（该树已初始化 obs/go2rtc 子模块）
- 证据：cmake -S native-host/tests/control-auth + ctest：18/18 通过（Linux, Ninja, Release）；cmake -S native-host -DWEBOBS_NATIVE_BUILD_TESTS=ON + ctest：8/8 通过；固定 OBS 32.1.2 构建 libobs（98/98）并导出 SDK，native-host/tests/real-loader ctest 1/1 通过（本机无 Xvfb 也能跑，标签 no-gpu/no-media）
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #176 · 2026-11-18T17:21:29+08:00 · claim

- Agent：`deepseek-v51-20261118-01`；任务：`V51-010`
- 记录：已修并推送 codex/v51-r3-004-lan@34a8297：门禁先在回环创建首账号（201/409），再用同一账号做 LAN HTTPS 与回环独立会话；无私网地址时诚实降级并通过
- 证据：PR #71 描述已更新；desktop/scripts/test-native-product-install.ps1 改为 report.lanEntryQualified/lanEntrySkipReason 取自回执真实值（该文件在 V51-007 声明范围内，一并在此记录）
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #175 · 2026-11-18T17:21:26+08:00 · add

- Agent：`deepseek-v51-20261118-01`；任务：`V51-010`
- 记录：V51-009 声明的 native-host/scripts 与 native-host/tests 范围与在办的 V51-005/007/008 冲突，无法认领；本任务只登记本次实际修改的门禁文件，监督器/窗口实现与打包证据仍记在 V51-009 的历史证据中
- 证据：python3 -B native-host/tests/test_product_lan.py 24 OK；test_build_contract.py 44 OK；lan_entry_windows.py 本机仅 ast 语法校验（需 Windows 已安装运行时）
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #174 · 2026-11-18T17:21:15+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：读 rc.33 回执的 programDefaultBusNativeStudio 与 programDefaultBusApplyAttempt，区分 core programSupported 判定与宿主 apply 拒绝原因
- 证据：无新增验收证据
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #173 · 2026-11-18T17:21:15+08:00 · claim

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：PR #67（codex/v51-r3-output）Program 合成输出：AAC/Opus 用具名 QByteArray 传编码器标签、按场景实际总线录像/推流、解码实际产物；rc.32 在 program-recording-default-bus 失败，已补 programApplyError 与 core/host 双侧证据（0b6edc2）并派发 rc.33
- 证据：rc.32 run 44266163975 failurePhase=program-recording-default-bus；此前 program-recording-decodes-both-fixture-pitches 通过（below600=1380.5/above660=908.8, mask=2）；本机 Qt6 + 固定 libobs 32.1.2 SDK + 固定 obs-frontend-api.h：product_window/product_output/product_scene/product_media -fsyntax-only 全部 exit=0；run 44271844168 = 5.1.0-rc.33 @ 0b6edc2 in_progress（product_mode/complete）
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #172 · 2026-11-18T17:20:59+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`R2-003`
- 记录：多轨音频已双语合并进 dev（PR #66），本机与 Windows 门禁证据已在案
- 证据：PR #66 merged into dev (merge commit be9c231 'merge: 合并v5.1原生多轨音频混音与电平')；Windows run 44224335029 之后的 rc.32 run 44266163975 门禁内 programAudio mixers=2、peakDbfs=-20.02、programRecordingBandRms below600=1380.5/above660=908.8（多轨总线证据）
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #171 · 2026-11-18T16:21:53+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：更正上一条日志断字：被拒绝的场景为 缺少 --confirm、缺少 --acceptance、验收文件缺失、验收门禁未记录(fullFeatureMigrationQualified=false)、latest.yml 与安装包字节不一致、稳定发布源码不在 main 可达(compare=behind)。
- 证据：同一 /tmp/v51chain 场景 A-H、F1/F2 的实际命令输出
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #170 · 2026-11-18T16:21:46+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：在已初始化 OBS/go2rtc 子模块的 codex/v51-publish-chain 工作树补跑缺失构建检查并用一次性 gh 替身把发布链验证到“待发布”状态（不写真实 Release）：候选发布成功且 prerelease=true、Tag v5.1.0-rc.32；缺 -
confirm、缺 --acceptance、验收文件缺失/门禁未记录(fullFeatureMigrationQualified)、latest.yml 与安装包字节不一致均被拒绝；5.1.0 稳定映射为 Tag v5.1 且要求源码在 main 可达（compare=behind 被拒，ahead 才允许 --latest）。
- 证据：native-host/tests/test_candidate_publish、test_stable_packaging、test_update_manifest、test_stable_release_identity、test_build_contract(44)、test_complete_release_policy 全 PASS；/tmp/v51chain 场景 A-H、F1/F2 实际输出
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #169 · 2026-11-18T16:02:14+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-009`
- 记录：新增已安装态局域网入口门禁 lan_entry_windows.py 并接入 NSIS 完整候选验收与内部回执上传：已验证 TLS 健康检查、外来 Origin 拒绝、LAN 与回环两客户端独立会话/退出、禁用后重启不再监听、退出无残留进程。本机全部相关测试再次通过。
- 证据：codex/v51-r3-004-lan@97b4efe 已推送；test_product_lan 24 PASS、test_product_package OK、test_build_contract 44 OK、test_complete_supervisor PASS、test_native_updater/test_migrate_legacy PASS
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #168 · 2026-11-18T15:59:16+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-009`
- 记录：完成 supervisor 侧局域网 HTTPS 入口（上一会话未提交的 WIP 已接续并实现）：prepare_lan 读取持久化设置并把 HTTPS 源写入 WEBOBS_CONTROL_ALLOWED_ORIGINS/WEBOBS_PWA_MEDIA_ALLOWED_ORIGINS，占用端口或非法设置失败关闭；打包 Caddy 反代到回环控制端口并实测本地可连；仅回环开关端口供原生窗口用宿主令牌读写；打包与校验强制 services/product/product_lan.py。
- 证据：codex/v51-r3-004-lan@13bc640 已推送；native-host/tests/test_product_lan.py 24 项通过；test_build_contract.py 44 项通过（已在该工作树初始化 obs/obs-studio 与 go2rtc/go2rtc 子模块）；test_complete_supervisor.py PASS；git diff --check 通过
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #167 · 2026-11-18T15:46:27+08:00 · add

- Agent：`deepseek-v51-20261118-01`；任务：`V51-009`
- 记录：复用 desktop/src/lan.mjs 既有实现语义，不引入 Electron 宿主
- 证据：无新增验收证据
- 源码：`b7ab83060ca6f955cee461a2a3e17e2109b5ef63`
## #166 · 2026-11-18T15:44:56+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`R2-003`
- 记录：rc.31 派发：#67 head e20dd28（掩码修复+启动预检+selectedAudioTracks+采集身份重试）；rc.27/rc.30 录像启动失败与 rc.29 投影窗口身份失效均已定位到具体阶段
- 证据：无新增验收证据
- 源码：`82bf19ff0151204ff6813f54bedcffddc6ae4889`
## #165 · 2026-11-18T15:44:56+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`R2-003`
- 记录：定位并修复 Program 录像/推流静默启动失败根因：audio_output_tracks() 跳过被静音的相机源，声明 audioInputs 的场景因此掩码恒为0，AV muxer/WHIP 在 can_begin_data_capture 内无错误拒绝。现分别读取相机源与混音源掩码，无路由音频时在默认总线挂静音轨；新增启动预检与 selectedAudioTracks 证据；像素采集在句柄失效时按新身份重试一次。
- 证据：codex/v51-r3-output e20dd28 已推送；rc.31 run 44261174753 派发（rc.31 未被 Tag/Release 占用）；rc.27/rc.30 回执 recordingError=recording-start-failed 且 last_error 为空；rc.29 在 program-after-take 出现 window-identity 失效
- 源码：`82bf19ff0151204ff6813f54bedcffddc6ae4889`
## #164 · 2026-11-18T15:41:30+08:00 · update

- Agent：`codex-ci-download-mktemp-20261118`；任务：`COORD-008`
- 记录：已在 AGENTS.md 写入中英双语 CI 下载目录规则和 Bash 示例
- 证据：AGENTS.md:42；Bash 使用 gh 替身验证两次执行得到不同空目录，带空格的产物名和目录值保持为独立参数；git diff --check 通过
- 源码：`82bf19ff0151204ff6813f54bedcffddc6ae4889`
## #163 · 2026-11-18T15:41:01+08:00 · claim

- Agent：`codex-ci-download-mktemp-20261118`；任务：`COORD-008`
- 记录：仅修改 AGENTS.md 的 CI 下载约定，保留已有未提交修改
- 证据：无新增验收证据
- 源码：`82bf19ff0151204ff6813f54bedcffddc6ae4889`
## #162 · 2026-11-18T15:41:01+08:00 · add

- Agent：`codex-ci-download-mktemp-20261118`；任务：`COORD-008`
- 记录：用户要求将 CI 下载避免递归强制删除的做法加入 AGENTS.md
- 证据：无新增验收证据
- 源码：`82bf19ff0151204ff6813f54bedcffddc6ae4889`
## #161 · 2026-11-18T15:03:17+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：#70 再次同步到 #67 最新 head（32e8d18），远端 head 现为 4664251；本机契约测试仍全通过。
- 证据：.worktrees/v51-backup@4664251；test_complete_supervisor PASS、test_encrypted_backup 10/10、test_native_updater 3 PASS
- 源码：`82bf19ff0151204ff6813f54bedcffddc6ae4889`
## #160 · 2026-11-18T15:03:17+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：静态复核发现并修好两处门禁缺陷：逐轨偏移等待条件对可能缺失的 audioSources 条目直接 .get 会抛 AttributeError（改为显式探针重试）；停止后资源对照把场景逐轨混音 ffmpeg.exe 也断言为空（改为 MediaMTX 必须为 0 且场景混音进程集合与推流前一致）。另在 Linux 用 ffmpeg 实解码复现 tone_amplitude：存在≈4095、不存在≈0、gain 0.2 比 0.200。
- 证据：head 32e8d18；rc.30 run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44255867749；本机 /tmp/tonecheck 双轨与单轨文件解码对照
- 源码：`82bf19ff0151204ff6813f54bedcffddc6ae4889`
## #159 · 2026-11-18T14:58:48+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：已派发 rc.29（run 44255084712，head de8eebe，complete=true）：包含具名 QByteArray 编码器 label、具名 QString 恢复原因、WHIP 握手 5 秒宽限、Direct-only 按需进程门禁、录像目录失败正反对照、总线隔离（1200Hz 单轨夹具+锁相音调检测）、逐轨静音/增益/偏移、WHIP 断线后回收。rc.27（44251999122）编译与集成服务步骤已过，产品 UI 步骤失败，日志要等 job 结束才能读取。
- 证据：https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44255084712
- 源码：`48e0a7892c7172df4435fd5f298c0f96e7924361`
## #158 · 2026-11-18T14:58:48+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：#70 已 rebase 到新的 #67 基线（de8eebe）并推送 head 7a7d64d；本机中断交换收敛契约、加密备份、更新器错误码全部通过。安装态恢复门禁 backup_restore_windows.py 只在 NSIS 安装验收里执行，必须有 Windows 回执才能写安装态通过。
- 证据：.worktrees/v51-backup@7a7d64d；native-host/tests/test_complete_supervisor.py PASS；tests/test_encrypted_backup.py 10/10；native-host/tests/test_native_updater.py 3 PASS；PR #70 checks 将随 force-push 重跑
- 源码：`48e0a7892c7172df4435fd5f298c0f96e7924361`
## #157 · 2026-11-18T14:58:48+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：补齐 #69 的本机重验：初始化固定的 OBS 子模块后 test_build_contract 44/44；发布链否定用例补全（验收 JSON 缺失/非法/非对象/其他仓库/未写 sourceRevision；latest.yml 单独 size 不符、单独 sha512 不符、version 不符、缺 size、文件名非 latest.yml），并把未绑定源码版本的验收回执改为失败关闭。发布链只验证到待发布，未创建 Tag/Release/稳定 feed。
- 证据：.worktrees/v51-publish@dc6d1b4；native-host/tests/test_build_contract.py 44 tests OK；test_candidate_publish/test_stable_packaging/test_update_manifest/test_stable_release_identity PASS；PR #69 全部 checks SUCCESS（含 windows-native-control-contracts、windows-update-contracts、offline staging）
- 源码：`48e0a7892c7172df4435fd5f298c0f96e7924361`
## #156 · 2026-11-18T14:58:39+08:00 · add

- Agent：`deepseek-v51-20261118-01`；任务：`V51-008`
- 记录：承接 #67：编码器 label、失败上报、音轨隔离与按需进程门禁都在同一分支；先修编译再复跑。
- 证据：PR #67 head de8eebe（base dev）；rc.26 失败原因 MSVC C2664（QString→const char*）已用具名 QByteArray 修复；rc.28 失败原因 product_output.cpp(412) C2664（三目临时量绑到 QString&）已修复
- 源码：`48e0a7892c7172df4435fd5f298c0f96e7924361`
## #155 · 2026-11-18T14:49:31+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：扩展 V51-007 范围并接入普通启动恢复：supervisor 在持有数据目录独占锁后、创建目录与读取 config/OBS profile 之前调用 recover_interrupted()，成对完成或回滚并保留旧对；非法日志失败关闭并写 run/restore-recovery.json。新增安装态门禁 backup_restore_windows.py（真实恢复进程在两次目录交换之间被终止→从安装入口启动收敛→可重试→config-only 旧包保留现有原生档案），并接入 NSIS 安装验收与工作流回执上传。
- 证据：python3 -B native-host/tests/test_complete_supervisor.py PASS（含中断交换收敛契约）；python3 -B tests/test_encrypted_backup.py 10/10；python3 -B native-host/tests/test_native_updater.py 3 项 PASS；本任务书 Windows 门禁待 CI 回执
- 源码：`48e0a7892c7172df4435fd5f298c0f96e7924361`
## #154 · 2026-11-18T13:02:02+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：PR #70 head 56e25e7（含更新器错误码映射）。本机测试全通过；等待 Windows CI 与本分支的 web-runtime-ci 结果后再决定关闭。
- 证据：PR #70 checks 进行中
- 源码：`48e0a7892c7172df4435fd5f298c0f96e7924361`
## #153 · 2026-11-18T13:02:02+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：补交遗漏：publish_candidate.py 与 test_candidate_publish.py 改为复用 release_policy.read_acceptance/apply_acceptance（先前一次提交漏加这两个文件）。分支 head 现为 99f8f30，PR #69 自动更新。
- 证据：.worktrees/v51-publish@99f8f30；本机 test_candidate_publish/test_stable_packaging PASS
- 源码：`48e0a7892c7172df4435fd5f298c0f96e7924361`
## #152 · 2026-11-18T12:56:21+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：已派发 rc.26（run 44240683072，head ae4fce7，complete=true）验证 Direct-only 复原后的首启与恢复隔离、Program 录像/推流按节目音轨编码、默认与第二总线对照、录像/回放解码带能量、托盘与备份/支持包门禁。
- 证据：https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44240683072
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #151 · 2026-11-18T12:56:21+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`R2-003`
- 记录：rc.25（run 44236342016，head 98e1e99）关键门禁已通过：step 13「Exercise the actual integrated launcher and authenticated product window」success，step 14「pre-authentication restore isolation」success。即完整来源 ID fixture-alt.fixture-alt-source 的三段断言（TAKE 生效/指定混音源出现/该源非静音）、夹具与 RTSP 双轨音调解码、mixers==2、volume 0.75、TAKE 前无混音源、清场与注销后释放混音进程，均在便携/安装后/升级后运行中通过；此前 rc.23 的短 ID 超时与 rc.24 的 composite 启动失败已消除。剩余 step 15 NSIS 安装验收、step 16 更新元数据、step 17 上传、step 20 体积预算仍在执行。
- 证据：https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44236342016 steps 13-14 success
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #150 · 2026-11-18T12:44:20+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：扩展范围：恢复日志与成对拒绝的新失败信息需要映射为有界更新器错误码，避免只显示通用 backup-create-failed。
- 证据：本机 tests/test_encrypted_backup.py 10 OK；native-host/tests/test_native_updater.py PASS（含新增错误码映射断言）
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #149 · 2026-11-18T12:42:22+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：已实现并推送 codex/v51-r4-backup-consistency@aeb6cb5，开 PR #70（base codex/v51-r3-output）：有界恢复日志与 recover_interrupted 收敛成对状态、含 native 存档必须成对恢复、失败清理暂存与日志、回滚名随机后缀、CLI recover 动作。
- 证据：本机 tests/test_encrypted_backup.py 10 tests OK（libsodium 可用）；native-host/tests/test_native_updater.py 与 test_migrate_legacy.py PASS
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #148 · 2026-11-18T12:38:54+08:00 · claim

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：开始实现恢复日志与成对交换一致性。
- 证据：分支 codex/v51-r4-backup-consistency 基于 codex/v51-r3-output@ae4fce7
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #147 · 2026-11-18T12:38:54+08:00 · add

- Agent：`deepseek-v51-20261118-01`；任务：`V51-007`
- 记录：双目录加密备份的中间步骤故障仍可能留下不一致：config 与 native-profile 交换过程无崩溃可读日志、失败时 activated 临时目录不清理、同秒回滚目录名可冲突、含 native 数据的存档在调用方未指定 native 目录时只恢复 config。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #146 · 2026-11-18T12:38:01+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：已提交并推送 codex/v51-publish-chain（6301ae7 Tag/main 祖先接线，a0a6ae6 单一验收契约接入 stage/update_manifest），Draft PR #69 说明已更新为完整发布链范围。
- 证据：PR #69 head a0a6ae6; 本机 release-chain 测试 6 个 PASS；test_build_contract 43/44（本树未初始化 obs 子模块）
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #145 · 2026-11-18T12:37:20+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：扩展同一发布链分支的实际改动：release_policy 新增 read_acceptance/apply_acceptance 单一验收契约；stage.py 增加 --stable/--acceptance；update_manifest.py 稳定版本需验收文件并输出 releaseTag；新增 test_stable_packaging.py，test_update_manifest.py 加入 scripts sys.path。候选路径行为与 workflow 调用保持不变。
- 证据：本机 PASS：test_stable_packaging/test_candidate_publish/test_update_manifest/test_stable_release_identity/test_complete_release_policy/test_preview_release；test_build_contract 43/44（本树未初始化 obs 子模块）
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #144 · 2026-11-18T12:37:17+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`V51-004`
- 记录：稳定身份与 Tag 映射已实现并本机验证，提交 codex/v51-release-identity@f176fba，PR #68 待合并到 dev；合并前 dev 仍不含该实现，后续接线与真实发行分别由 V51-005/V51-006 跟踪。
- 证据：PR #68; test_stable_release_identity PASS; test_build_contract 44/44 in .worktrees/v51-release; docs/release-flow.md §4.1 与 versioning Tag 映射已更新
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #143 · 2026-11-18T12:36:57+08:00 · add

- Agent：`deepseek-v51-20261118-01`；任务：`V51-006`
- 记录：正式打包链缺稳定模式：stage.py 只接受 dev/preview/candidate，update_manifest.py 只接受 rc 版本，二者都没有验收门槛。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #142 · 2026-11-18T12:34:07+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：publish_candidate.py 已接线：Tag 来自 release_policy（候选 configure_complete + 稳定 configure_stable/releaseTag），--final 需仓库外验收 JSON 绑定 version/repository/sourceRevision 且四项验收为 true，并要求 compare/<sha>...main 为 ahead/identical；新增 test_candidate_publish.py 用 gh 替身做正反对照，无网络调用。已推 codex/v51-publish-chain@6301ae7，开 Draft PR #69（依赖 #67 提供该文件、#68 提供 tag_for_version）。
- 证据：PR #69 (draft); .worktrees/v51-publish@6301ae7; test_candidate_publish.py PASS; test_stable_release_identity/test_complete_release_policy/test_preview_release PASS; test_build_contract 43/44（本树未初始化 obs 子模块）
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #141 · 2026-11-18T12:31:20+08:00 · claim

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：开始接线 publish_candidate.py：Tag 映射改用 tag_for_version，--final 增加验收文件与 main 可达性校验。
- 证据：分支 codex/v51-publish-chain 基于 codex/v51-release-identity@f176fba
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #140 · 2026-11-18T12:31:20+08:00 · add

- Agent：`deepseek-v51-20261118-01`；任务：`V51-005`
- 记录：为 v5.1 正式收口做准备：候选发布脚本目前拼 "v"+version 会算出 v5.1.0，且 final 路径不校验源码是否来自已审查 main。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #139 · 2026-11-18T12:31:05+08:00 · log

- Agent：`deepseek-v51-20261118-01`；任务：`V51-004`
- 记录：稳定身份与 Tag 映射已提交 f176fba 并开 PR #68（base dev）：tag_for_version 单一实现（5.1.0→v5.1、补丁三位、rc 保留后缀、dev 无 Tag）、configure_stable 需登记安装/升级/迁移验收与有界回执；docs/release-flow.md 与 docs/versioning-and-branches.md 补双语说明。本机 test_stable_release_identity/test_complete_release_policy/test_preview_release/test_build_contract(44/44) 全通过。尚未接线：publish_candidate/stage/workflow 仍自行拼 Tag。
- 证据：PR #68; .worktrees/v51-release@f176fba; python3 -B native-host/tests/test_stable_release_identity.py PASS
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #138 · 2026-11-18T12:25:07+08:00 · claim

- Agent：`deepseek-v51-20261118-01`；任务：`V51-004`
- 记录：认领并开始实现稳定身份与映射（工作树 .worktrees/v51-release@codex/v51-release-identity，基于 origin/dev 07c4be0）。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #137 · 2026-11-18T12:25:07+08:00 · add

- Agent：`deepseek-v51-20261118-01`；任务：`V51-004`
- 记录：依据 V51-DEEPSEEK-COMPLETION-GUIDE-2026-11-18.md 第 7 节第 2 点：正式打包前需补齐稳定模式、Tag／版本映射与对应测试；范围限于策略、测试与文档，不触碰发布权限。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #136 · 2026-11-18T12:24:14+08:00 · update

- Agent：`deepseek-v51-20261118-01`；任务：`R2-003`
- 记录：已修正 rc.23 的 Program TAKE 来源断言并拆成三段等待，补配置正反对照与夹具/回环 RTSP 的解码音调证据；新 SHA 98e1e99 已推送，rc.25 Windows 运行进行中。同时定位 rc.24 首启失败根因：supervisor 将 WEBOBS_COMPOSITE_ENABLED 设为 true 使 webobsd 进入完整 OBS 引擎路径并在原生宿主启动时退出（RuntimeError control exited during startup），产品入口与恢复隔离两条门禁同时受影响。
- 证据：本机 python3 -B native-host/tests/test_build_contract.py 44/44 OK（两树）；native-host/tests/test_complete_supervisor.py PASS；test_product_package.py 6/6 OK；pixel_windows.tone_probe 实测 /tmp 合成双音轨文件返回 (2895.2,439.8)/(2887.5,879.8)，band_rms 混合样本 2620/1727、带外高通 20.9；py_compile 两个测试文件通过；git diff --check 通过。Windows rc.25 run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44236342016（head 98e1e99，当前步骤 11 编译 OBS 前端/插件）。
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #135 · 2026-11-18T11:43:34+08:00 · claim

- Agent：`deepseek-v51-20261118-01`；任务：`R2-003`
- 记录：接手 R2-003：先按 rc.23 回执修正 native Program TAKE 音频等待断言（完整 sourceId、拆分三个检查点），再补逐轨可区分音频证据；实际代码树 .worktrees/v51-audio@codex/v51-r2-003。
- 证据：gh run view 44224335029 --log-failed：failurePhase=native-program-take，programApplyState=applied，programSceneId=fixture-alt，audioSources[0].sourceId=fixture-alt.fixture-alt-source，peakDbfs=-20.866，mixers=2，available=true；obs 日志显示 WebOBS audio mix fixture-1 断开后 2.3s 重连。
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #134 · 2026-11-18T11:43:30+08:00 · release

- Agent：`deepseek-v51-20261118-01`；任务：`R2-003`
- 记录：协调交接：原负责人 codex-v51-continue-20261117-01 会话已被用户中断且不再继续；用户 2026-11-18 通过 docs/coordination/V51-DEEPSEEK-COMPLETION-GUIDE-2026-11-18.md 明确要求新会话接手 R2-003。释放原认领后由新唯一 ID 认领；保留其两个工作树与提交。
- 证据：用户 2026-11-18 指示：按 V51-DEEPSEEK-COMPLETION-GUIDE-2026-11-18.md 第 1 节与原负责人交接后用新唯一 ID 认领；原会话 run_interrupt_result 已停止。；git worktree list：根目录 codex/windows-native-monitor@24fd012、.worktrees/v51-audio@codex/v51-r2-003(44ce627 干净)、.worktrees/v51@codex/v51-r3-output(2c64a5a，ahead 1 本地文档提交)；未重置或覆盖任何工作树。
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #133 · 2026-11-18T11:06:44+08:00 · update

- Agent：`codex-v51-guide-20261118`；任务：`HANDOFF-004`
- 记录：DeepSeek 的最新执行入口为 docs/coordination/V51-DEEPSEEK-COMPLETION-GUIDE-2026-11-18.md。优先修 #66 的 rc.23 运行态来源 ID 断言，再验证双轨与 Program 产物；#67 rc.24 产品 UI 已失败，独立恢复仍在运行。继续任务以指南和当前账本的证据为准，R2-003 原 owner 保留。
- 证据：rc.23 @44ce627 报告 Program=applied、-20.87 dBFS、sourceId=fixture-alt.fixture-alt-source。离线重算显示原短 ID 导致等待为假，完整 ID 条件为真。#67 AAC/Opus encoder 创建均选总线索引0，具体验证建议在指南，未声称已复现输出静音。指南链接与围栏核对、7项协作测试及三树 diff 检查均通过。
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #132 · 2026-11-18T11:02:41+08:00 · claim

- Agent：`codex-v51-guide-20261118`；任务：`HANDOFF-004`
- 记录：只编辑指南，保留 R2-003 现有 owner 和产品工作树。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #131 · 2026-11-18T11:02:41+08:00 · add

- Agent：`codex-v51-guide-20261118`；任务：`HANDOFF-004`
- 记录：用户要详细指导手册，后续由用户交给 DeepSeek 完成成品。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #130 · 2026-11-18T09:04:17+08:00 · log

- Agent：`codex-v51-continue-20261117-01`；任务：`R2-003`
- 记录：在2e9e736启动完整Windows门禁44211809863；定位音频源不启动根因：OBS ffmpeg_source在restart_on_activate=true时仅对showing源启动，纯音频源无show_refs，故UDP从未被消费。已在codex/v51-r2-003本地改为由所属图生命周期启动并保留诊断，待该run回执确认后推送新run。
- 证据：https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44211809863
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #129 · 2026-11-18T07:57:42+08:00 · claim

- Agent：`codex-v51-continue-20261117-01`；任务：`R2-003`
- 记录：V51-002已由当前Agent完成并记录run44194328169；接手多轨音频产品闭环，先复用现有schema-v6与空选择行为，再接实际原生音频混音/监听/电平。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #128 · 2026-11-18T07:57:24+08:00 · update

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：Windows v5.1更新/迁移门禁已完成：run44194328169/source472f3fe/rc.16成功，便携/安装态/升级后各55项，恢复9/9，真实rc.16→rc.17更新器下载/缓存拒绝/维护运行时/加密备份/NSIS/恢复通过，profile指纹30/30一致；资格摘要和矩阵/执行记录已提交。
- 证据：run https://github.com/LiaoYK001/Web-Camera-Monitor-Web-Camera-Monitor-Wall/actions/runs/44194328169 (actual URL https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44194328169); source472f3fe; setup 212162215 B sha256 12039948205f915de180eb0a84f74d0b51ef3fd737a30234851305dbe4242dbd; footprint 794579783 logical/806620488 allocation/6972 files; docs/qualification/windows-v51-update-gates-2026-11-18.json; docs/release-notes-v5.1.md; docs/windows-native-feature-parity.md; docs/windows-obs-parity-execution.md; public run44194330290 success; test_build_contract 44/44; agent-sync check/diff check通过
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #127 · 2026-11-18T06:53:19+08:00 · update

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：run44188738414证实状态发布重试后Program清屏/升级前UI到达normal-close；失败为历史PID复用导致的cleanup误报（normalCloseAlivePids=2，exit=0，state已locked/无媒体）。已改为记录内核创建时间，仅将同PID同创建时间进程视为产品所有；不改变真实存活断言。新run44194328169 source472f3fe/rc.16已启动。
- 证据：run44188738414: source20696af, entry-ui checks44 then failure normal-close, exit0, normalCloseAlivePids=2, state locked/media0; new source472f3fe, py_compile/diff check; run44194328169 identity
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #126 · 2026-11-18T06:18:22+08:00 · update

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：run44176217763已验证upgrade profile fingerprint通过（before/after 30，sameMachineUpgradeQualified=true）、实际NSIS升级到rc.15并完成注册；新失败在升级后UI的空Program清屏观察，state仍显示旧Program且cleanupFailed=true。定位为Windows读取方短暂持有product-state.json导致QSaveFile替换失败；已加有界重试并暴露programSyncPending，保留真实状态断言，等待预算12→25s。
- 证据：run44176217763 artifacts rc.14：native-product-updater passed=true；native-product-nsis sameMachineUpgradeQualified=true, registeredVersion=5.1.0-rc.15, profileFingerprint 30/30；upgraded-ui failurePhase=native-program-take lastCheckpoint=program-cleared-put；product_window Qt syntax、product_windows py_compile、build contracts 44/44、diff check通过
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #125 · 2026-11-18T05:05:41+08:00 · update

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：rc.13已实际通过统一入口UI/媒体、安装态UI、恢复、真实备份/升级和版本切换；唯一失败是升级后profile指纹。现已仅对可再生成日志/崩溃/sentinel/WAL sidecar做白名单，保留durable文件SHA-256并输出最多32个变化相对路径；同时为无上游修复的picomatch ReDoS补丁化并定向审计。
- 证据：run44165531375 failurePhase=same-machine-upgrade-profile-fingerprint，updater/registeredVersion通过；本地web typecheck/build、dependency-security 7/7、desktop test 60/60、audit(ignore GHSA-fc5q-39xc-vjpf)、test_native_updater 3/3、test_build_contract 44/44、encrypted_backup 3/3、git diff --check通过
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #124 · 2026-11-18T03:09:22+08:00 · update

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：rc.11已通过实际UI/安装UI/NSIS首装与升级后恢复；失败原因是Windows更新器用Python subprocess传递含中文/空格的/D=目录未按历史Start-Process落盘，导致私有安装根仍为旧manifest。6aa8602恢复受控Start-Process并保留退出码/超时
- 证据：codex/v51-hardening@6aa8602；rc.11 run44143228832实际UI 55/55、安装态UI通过、restore 9/9、NSIS首装setup 212123898B；失败Assertion installed manifest rc.11 != rc.12；本地test_native_updater 3 PASS、build contracts 44/44
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #123 · 2026-11-18T02:00:59+08:00 · update

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：rc.10实际UI/安装态UI/NSIS首装均通过；升级恢复根因由安装态诊断确认为Windows默认/backups非绝对路径。ea2b8b1恢复时传入绝对data-root/backups并加回归
- 证据：diagnostic run44141423769: installed native_updater restore stderr="backup paths must be absolute"; run44130563613 actual UI/installed UI pass, failurePhase=same-machine-upgrade; local test_native_updater now 3 PASS incl absolute backup root; source codex/v51-hardening@ea2b8b1
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #122 · 2026-11-18T00:00:38+08:00 · update

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：rc.8提前失败在管理入口UIA查找，原因是新查表对未知identity提前抛错；ffb1d83改为已知名称直查、未知identity后缀回退，并映射9个管理入口
- 证据：codex/v51-hardening@ffb1d83a272d039a6268c68f459a2ed36a84e07f；rc.8 run44114909394 failurePhase=complete-business-management-entries、code=find-webobsManageAudio；test_build_contract 44/44 PASS
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #121 · 2026-11-17T23:29:37+08:00 · update

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：rc.7安装态UI在Program投影关闭处UIA超时但产品状态已清理；57ea2cf改为AutomationId/名称+类型直接查找并提高受控UI预算，仍在同一真实关闭动作上验证
- 证据：codex/v51-hardening@57ea2cf9e38e80908f00c562d43a6ebb05abaca4；rc.7实际UI通过55项，安装态UI在projector-close ui-timeout；产品状态projectorCount=0；test_build_contract 44/44与Python编译PASS
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #120 · 2026-11-17T22:31:25+08:00 · update

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：rc.6的实际UI与安装态UI/媒体通过；失败在同一安装更新阶段的加密恢复子进程。4dc97e5让备份/恢复显式使用已安装运行时并输出有界错误码，更新门禁改走该运行时
- 证据：codex/v51-hardening@4dc97e5693be7d2064d148d5e15f1db44716b062；rc.6 run44093199118实际UI 55项/安装态UI 55项通过，setup 212107604B；失败phase=same-machine-upgrade，备份restore子进程exit1；本地test_native_updater、encrypted_backup、product_package、release_policy PASS
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #119 · 2026-11-17T21:29:28+08:00 · update

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：rc.5定位为门禁竞态：SetWindowPos已移动投影，但旧的fixed-1偏好使等待提前返回；b1681d4等待移动前后几何/偏好真实变化并比对运行时与workspace
- 证据：codex/v51-hardening@b1681d4402fea4901b8b6fb24877889a186d61eb；run44093199118 in_progress；rc.5回执projectorPlacement=968x689旧值、重开实际784x461；test_build_contract 44/44与Python编译PASS
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #118 · 2026-11-17T21:05:05+08:00 · update

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：rc.4证明fixed-1偏好已保存，失败后移到逐个关闭OBS投影：UIA WindowPattern.Close未实际关闭；afc7653改为对精确投影句柄发送WM_CLOSE，并加保存/重开几何检查点
- 证据：codex/v51-hardening@afc76537fcc78ec12059f3b3ffba456243db314d；run44089178485 in_progress；rc.4 run44085990284回执显示projectorPreferenceRoles=[fixed-1]、几何已保存；test_build_contract 44/44、Python编译与diff检查PASS
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #117 · 2026-11-17T20:44:44+08:00 · update

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：已修复rc.3暴露的投影移动未持久化：复用现有心跳做几何变化快照，仅在变化时去抖写，关闭/状态观察显式保存，门禁新增有界几何/偏好诊断
- 证据：codex/v51-hardening@6834994bd80e040558ea9f3f308f3c2a645907c3；product_window语法检查通过；test_build_contract 44/44、complete supervisor、product package 6/6、upgrade runtime PASS；run44085990284 https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44085990284 in_progress
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #116 · 2026-11-17T20:43:42+08:00 · update

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：run44081218082源码5add246：UI门禁通过工作区断言后在fixed-scene-projectors失败；投影已打开但移动后workspace无fixed-1偏好，定位为Qt Move事件未可靠触发保存；同任务本地修复product_window并增加诊断
- 证据：run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44081218082；failurePhase=fixed-scene-projectors；lastCheckpoint=pixels-continuous-reordered-captured；projectorCount=1；首个工作区修复已使后续studio/README检查通过；未把本轮当通过
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #115 · 2026-11-17T20:14:17+08:00 · update

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：已定位44057825506失败：投影偏好写入工作区导致旧严格等值断言误报；已在5add246分别校验媒体载荷与有界projectorPlacements schema，44构建契约/迁移/更新/包测试及语法检查通过
- 证据：codex/v51-hardening@5add246679c5ee22b6bf338e4601ffe81a5633fd；PR #65已推送；Windows run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44081218082 in_progress；本机 test_build_contract 44/44、test_product_package 6/6、test_upgrade_runtime 1、test_migrate_legacy 3、test_native_updater 2 PASS；投影工作区helper样例PASS；未把该run当已通过
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #114 · 2026-11-17T20:10:23+08:00 · claim

- Agent：`codex-v51-continue-20261117-01`；任务：`V51-002`
- 记录：接手v5.1迁移更新及完整Windows门禁；已核对源码2f676e9、PR65、run44057825506在实际UI步骤失败，先取失败日志修复并重跑
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #113 · 2026-11-17T18:09:15+08:00 · update

- Agent：`codex-v51-handoff-20261117`；任务：`HANDOFF-003`
- 记录：交接完成：请全文读取V51-NEXT-AGENT-HANDOFF-2026-11-17.md。已释放V51-002给新唯一Agent ID，保留最新v51代码/PR65和root未提交协作文件；单文件含已做/未做、具体接线位置、测试与失败历史、任务顺序和v5.1正式交付条件。最后复查44057825506已进入实际产品UI，尚无整轮结论。
- 证据：docs/coordination/V51-NEXT-AGENT-HANDOFF-2026-11-17.md；本轮7项协作测试通过，4文档31本地链接存在/围栏配对通过，root和v51两树diff检查通过，v51干净；PR65 OPEN@2f676e9、dev2258a37，Windows预检查/OBSQt/业务构建success、actual UI运行中；未改产品或发布
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #112 · 2026-11-17T18:04:56+08:00 · release

- Agent：`codex-v51-20261117`；任务：`V51-002`
- 记录：用户明确要求转交其他Agent完成v5.1；本会话释放任务。实际最新代码codex/v51-hardening@2f676e9已推PR65且工作树干净；Windows44057825506仍独立运行，预检查/OBSQt编译通过，当前业务服务构建中；下一Agent用新唯一ID认领后先查询此run并修失败，不重做旧预览。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #111 · 2026-11-17T18:03:41+08:00 · claim

- Agent：`codex-v51-handoff-20261117`；任务：`HANDOFF-003`
- 记录：本轮仅交接文档；已重新核对AGENTS、统一账本、4个工作树、PR65和Windows44057825506；不替用户发布或改产品代码
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #110 · 2026-11-17T18:03:41+08:00 · add

- Agent：`codex-v51-handoff-20261117`；任务：`HANDOFF-003`
- 记录：用户要求换其他Agent完成，针对v5.1尚未正式发布和多轨/输出/远端等剩余任务做完整交接
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #109 · 2026-11-17T17:42:58+08:00 · update

- Agent：`codex-v51-20261117`；任务：`V51-002`
- 记录：最新有效整轮为44057825506@2f676e9（5.1.0-rc.2）；刚核对Windows预检查整步SUCCESS，含修复后的维护工具中文/规范路径夹具，已进入OBS/Qt实际编译。2f676e9仅测试读取修正，运行时代码与8e18590一致。旧44057420866失败、wrapper44050932022/44055841340均已cancelled；不从旧运行交付。当前代码已推PR65、工作树干净，完整版本和正式发布仍未完成。
- 证据：https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44057825506；head2f676e93853c672dfa273320dbbb6db81adbe407；Windows Verify process accounting logic and actual Windows query APIs=success，Compile pinned OBS frontend and product plugin=running；本地迁移/更新维护、加密备份、Qt几何/语法和44契约通过；无正式Tag/Release/feed变更
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #108 · 2026-11-17T17:41:07+08:00 · update

- Agent：`codex-v51-20261117`；任务：`V51-002`
- 记录：最新直接Windows44057420866@8e18590在预检查维护工具夹具失败：中文origin文件UTF8写入而测试按系统默认编码读取。实际产品写/读均UTF8；已提交2f676e9修正测试明确UTF8并与resolve后的Windows规范路径比较，本机回归通过，重新dispatch新source完整流程。不得把失败当绿或只rerun旧SHA。
- 证据：失败日志定位test_native_updater.py:219 origin read_text()断言；source2f676e9仅2行测试修复，无运行时代码变化；本机test_native_updater.py通过；新Windowsrun待最新ID登记
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #107 · 2026-11-17T17:39:46+08:00 · update

- Agent：`codex-v51-20261117`；任务：`V51-002`
- 记录：最新源码8e18590的PR65公共CI已有10项SUCCESS、1项desktop candidate按配置SKIPPED。旧44050932022取消仍占wrapper队列，已请求force-cancel；为避免纯等待，取消未启动wrapper44055841340，改用现有独立windows-obs-native-host流程44057420866跑同一套完整门禁、相同源码和5.1.0-rc.2。运行器各自隔离，无发布或共享安装；不把queued/pending写成通过。
- 证据：PR65 statusCheckRollup已核对10SUCCESS/1SKIPPED；最新完整Windows https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44057420866 @8e185901e1895c29ccd58438c927000c6d4fded7，当前queued；旧c689e1b portable步骤success仅为历史局部证据；本机7项协作测试/check/diff通过，v51树干净
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #106 · 2026-11-17T17:34:10+08:00 · update

- Agent：`codex-v51-20261117`；任务：`V51-002`
- 记录：较早c689e1b的Windows44050932022已通过实际portable UI/媒体（含新迁移），到恢复I/O步骤；为避免在已被新修复替代的源码上重复后续安装/升级，主动取消旧整轮，不能记成全绿。最新run44055841340绑定8e18590、5.1.0-rc.2，继续所有门禁；后续正式交付仍未完成。
- 证据：gh run view确认旧actual integrated launcher步骤conclusion=success；gh run cancel44050932022；新run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44055841340 @8e185901e1895c29ccd58438c927000c6d4fded7；不从取消run发布安装包
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #105 · 2026-11-17T17:28:05+08:00 · update

- Agent：`codex-v51-20261117`；任务：`V51-002`
- 记录：新增源码8e18590：独立维护解释器防止NSIS覆盖占用中的安装Python；修复自定义安装路径/单引号路径、无更新误安装、安装前实际版本复检、稳定通道拒绝预发布、恢复入口确认/libsodium路径。临时维护字节纳入回执，完成后supervisor清理；本机维护/备份/恢复回归通过。Windows44050932022@c689e1b已进入实际UI，后续最新source另起5.1.0-rc.2整轮，未公开发布。
- 证据：PR65 source8e18590；native_updater/maintenance/cmd/restore实际接线；本机迁移、HTTP+缓存、独立维护工具隔离/清理及3项加密备份回归通过；Qt投影源码003a583已提交且只本机验证，新的Windows仍待结果
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #104 · 2026-11-17T17:08:54+08:00 · claim

- Agent：`codex-v51-20261117`；任务：`V51-002`
- 记录：继续实际Windows运行44050932022的迁移/更新验证，随后用新source验证投影；完整R2/R4仍开放
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #103 · 2026-11-17T17:08:54+08:00 · release

- Agent：`codex-v51-20261117`；任务：`R2-004`
- 记录：保留已提交窗口偏好子能力，完整任务仍开放；回到正在运行的Windows迁移/更新门禁处理，避免跨任务重叠修改脚本
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #102 · 2026-11-17T17:08:54+08:00 · update

- Agent：`codex-v51-20261117`；任务：`R2-004`
- 记录：窗口偏好已真实接入现有Qt/OBS窗口事件及账号workspace，屏幕缺失时可见区域回退，去抖保存不增加空闲采样。几何测试真实链接QtCore通过，product_window在Qt6.11.2/GCC下-Werror语法及44构建契约通过；实际Windows新source待跑。媒体自动恢复/物理DPI仍未完成，不关闭任务。
- 证据：v51树projector_placement.hpp、product_window.cpp与Qt回归/Windows移动保存重开断言；本机g++几何测试、product_window语法与44契约通过；历史Windows44050932022只含c689e1b不含此投影修改
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #101 · 2026-11-17T17:02:51+08:00 · update

- Agent：`codex-v51-20261117`；任务：`R2-004`
- 记录：先实现按账号保存投影位置/屏幕/全屏与移除屏幕后可见范围回退，复用OBS原窗口与已有授权打开流程；不新增播放器或未认证自动建图。媒体自动恢复/物理多屏仍是剩余项。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #100 · 2026-11-17T16:59:54+08:00 · claim

- Agent：`codex-v51-20261117`；任务：`R2-004`
- 记录：实际Windows迁移/更新整轮运行期间推进投影持久恢复；物理多屏/DPI仍留待v5.1目标机，不以现有投影像素替代恢复实现
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #99 · 2026-11-17T16:59:54+08:00 · release

- Agent：`codex-v51-20261117`；任务：`V51-002`
- 记录：管线源码已提交c689e1b并启动实际Windows整轮44050932022；本机检查通过，仍在编译，未关闭任务。等待期间释放脚本范围以串行认领投影恢复功能，不代表任务完成或他人可不看运行身份改结论。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #98 · 2026-11-17T16:57:48+08:00 · update

- Agent：`codex-v51-20261117`；任务：`V51-002`
- 记录：已提交c689e1b，PR65接续；实际v5.1 Windows整轮44050932022启动运行，版本5.1.0-rc.1，明确不发布/不改稳定feed。新门禁包含实际Qt工作区迁移恢复、已安装更新器真实NSIS和新payload入口媒体。Windows结果尚未产生，不能以源码/本机测试关闭该任务。
- 证据：source c689e1bab3c63bdd2b90046dacaf5c0fb4f106f7；run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44050932022；本机版本/元数据、独立payload/防改写、supervisor和6包测试、44构建契约通过；PR65公共CI与整轮Windows继续观察
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #97 · 2026-11-17T16:49:19+08:00 · claim

- Agent：`codex-v51-20261117`；任务：`V51-002`
- 记录：独占相关脚本/测试与版本管线范围，先读实际payload清单和安装流程后修改；其他产品任务仍未关闭
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #96 · 2026-11-17T16:49:18+08:00 · add

- Agent：`codex-v51-20261117`；任务：`V51-002`
- 记录：继续正式交付准备，纠正rc.1同payload升级门禁，已有修复需要Windows产品流程验证
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #95 · 2026-11-17T16:49:18+08:00 · update

- Agent：`codex-v51-20261117`；任务：`FIX-001`
- 记录：已接线并提交首批审查缺陷修复，源码cd33809已推送codex/v51-hardening；本机迁移3组/HTTP缓存负向及44构建契约通过。仅关闭源码回归子任务，新的Windows安装与完整R4仍未关闭，接续管线实测。
- 证据：source cd33809；v51树migrate_legacy/native_updater及新增负向回归；python3 -B test_migrate_legacy.py、test_native_updater.py、test_build_contract.py 44/44、git diff --check通过；不修改历史Release或稳定feed
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #94 · 2026-11-17T16:48:10+08:00 · update

- Agent：`codex-v51-20261117`；任务：`FIX-001`
- 记录：迁移实际插件路径/整profile提交回退、缓存EXE双阶段size/SHA512复检、同版回退拒绝和SemVer修复已接线；本机迁移3组及HTTP/缓存损坏负向回归通过。构建契约44项初跑43通过、1因新树OBS子模块未初始化缺CMakePresets，正初始化固定源码后重跑，未放宽断言。
- 证据：v51树native-host/scripts/migrate_legacy.py和native_updater.py，相关真实文件/SQLite/HTTP回归通过；尚未运行新Windows安装，安装执行器mock隔离
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #93 · 2026-11-17T16:42:50+08:00 · claim

- Agent：`codex-v51-20261117`；任务：`FIX-001`
- 记录：仅修改声明的迁移/更新和相关测试文档，不关闭整个R4；新工作树v51执行
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #92 · 2026-11-17T16:42:50+08:00 · add

- Agent：`codex-v51-20261117`；任务：`FIX-001`
- 记录：独立审查已证明缺陷，紧急子任务独立于R4整体迁移能力，保留R4未完成依赖
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #91 · 2026-11-17T16:42:50+08:00 · update

- Agent：`codex-v51-20261117`；任务：`V51-001`
- 记录：已登记v5.1交付目标和用户主要验证安排，建立隔离新工作树；立即进入缺陷修复，不把版本变更当完整验收。
- 证据：AGENTS/DECISIONS及v51树docs/release-notes-v5.1.md；新树codex/v51-hardening基于2258a37，旧三树未切换/重置；账本全局决定通过脚本锁/验证和原子生成写入
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #90 · 2026-11-17T16:42:50+08:00 · decision

- Agent：`codex-v51-20261117`；任务：`V51-001`
- 记录：用户最新正式交付目标转为v5.1，主要Windows验证使用v5.1；保留既有R任务验收和历史发行，继续自主开发/CI。
- 证据：本聊天2026-11-17用户明确指令；AGENTS.md及DECISIONS.md新决定
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #89 · 2026-11-17T16:41:52+08:00 · claim

- Agent：`codex-v51-20261117`；任务：`V51-001`
- 记录：已读共享账本和AGENTS，origin/dev=2258a37；保留三个已有checkout，新建隔离v5.1开发树
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #88 · 2026-11-17T16:41:52+08:00 · add

- Agent：`codex-v51-20261117`；任务：`V51-001`
- 记录：用户要求继续优化，争取v5.1正式版修复所有已指出缺点后Release，后续以v5.1在本人Windows主要验证
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #87 · 2026-11-17T16:06:12+08:00 · update

- Agent：`codex-rc1-review-20261117`；任务：`AUDIT-001`
- 记录：rc.1独立审查已完成，报告定位3项可复现缺陷及未闭合产品范围；仅关闭审查任务，不关闭R2–R7、性能或迁移验收。公开包与回执真实；建议继续修复/补功能后给用户最终完整候选，不把开发缺口转为实机待验。
- 证据：docs/qualification/v5-rc1-independent-review-2026-11-17.md；本轮匿名完整包212117618B SHA256=3d16014dab7700e6bc4f73c5c0bfba5700382c78fb3f24041589b58a4e67016c，SHA512同feed；迁移真实路径漏拷、缓存15B替换放行至mock安装命令、rc.2/rc.10反序复现；agent-sync check和git diff --check通过；未改产品代码/发行/用户数据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #86 · 2026-11-17T16:05:49+08:00 · update

- Agent：`codex-rc1-review-20261117`；任务：`AUDIT-001`
- 记录：独立核验公开rc.1资产及Windows回执属实；完整下载安装器SHA256/SHA512一致。隔离复现3缺陷：真实v4.5工作区路径漏迁移并回报成功、缓存安装器执行前不重验摘要、rc.10/rc.2字符串顺序错误；NSIS升级仅同runtime改VERSION，未测真实updater链。矩阵另有OUTPUT/REMOTE/OFFLINE等未接线，不能称仅剩目标机验收。
- 证据：docs/qualification/v5-rc1-independent-review-2026-11-17.md；11/13匿名下载资产size/hash对GitHub一致；52/52/9和35captures回执同8828532；本轮旧迁移/更新测试通过但独立负向反例复现；所有安装命令mock，没有执行EXE或触碰本人数据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #85 · 2026-11-17T16:02:23+08:00 · claim

- Agent：`codex-rc1-review-20261117`；任务：`AUDIT-001`
- 记录：已核对三工作树、账本、AGENTS、PR63/64和Release；当前无产品任务负责人，本轮仅认领审查报告范围
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #84 · 2026-11-17T16:02:23+08:00 · add

- Agent：`codex-rc1-review-20261117`；任务：`AUDIT-001`
- 记录：用户要求检查rc.1完成报告，本轮只审查和记录证据，不改变发行或替用户验收
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #83 · 2026-11-17T06:16:46+08:00 · merge

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`全局`
- 记录：v5.0.0-rc.1 完整候选证据文档 PR #64 已通过公共检查并合入 dev（merge 2258a37）；候选 Release、安装器字节和边界记录现与 dev 一致。
- 证据：PR64 https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/64 merged 2258a37; checks public-audit/native/contracts success; release v5.0.0-rc.1 unchanged
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #82 · 2026-11-17T06:09:14+08:00 · update

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`全局`
- 记录：更新当前进度摘要：v5.0.0-rc.1 候选已发布，R1/R2-001 关闭；保留目标机、旧数据、音频/OBS输出/远端和性能边界。
- 证据：release https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v5.0.0-rc.1; run 43956468003; v4.5 and v4.0 Latest unchanged; docs PR 64.
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #81 · 2026-11-17T06:08:15+08:00 · update

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`R7-001`
- 记录：集中验收候选已可通过 GitHub Release 下载；等待目标机与真实相机/旧档案。
- 证据：v5.0.0-rc.1 prerelease; 52/52 portable + 52/52 installed + 9/9 restore; no target-device evidence.
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #80 · 2026-11-17T06:08:15+08:00 · update

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`R6-001`
- 记录：已冻结并发布 v5.0.0-rc.1 完整候选（prerelease，13 assets），包含安装器/更新元数据/校验和/验收摘要/来源清单/候选 SBOM/回执；目标机最终验收未完成，故 R6/R7 不关闭。
- 证据：https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v5.0.0-rc.1; run 43956468003; installer sha256 3d16014d...
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #79 · 2026-11-17T06:08:15+08:00 · update

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`R5-001`
- 记录：完整候选首启安装树实测 794551075 logical/806587720 allocation B、6972 files；尚未做目标机逐路硬解、两小时长稳和 OBS 同条件 A-B。
- 证据：run 43956468003 native-product-nsis footprint; no target CPU/GPU/long-run/OBS comparison.
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #78 · 2026-11-17T06:08:15+08:00 · update

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`R4-002`
- 记录：原生更新器、SHA-512/size、确认安装、NSIS 覆盖升级、卸载保留和正常/崩溃收束已验证；稳定 feed 与旧稳定实机升级仍开放。
- 证据：run 43956468003: rc.1→rc.2 same-machine upgrade, fresh NSIS, normal close/restart/launcher crash; latest.yml byte-bound.
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #77 · 2026-11-17T06:08:15+08:00 · update

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`R4-001`
- 记录：旧 WebOBS 4.x 与 v4.5 NativePreview 显式迁移代码、SQLite 一致性/工作区/拒绝覆盖单测通过；已接入安装快捷方式，但用户本人档案实际迁移尚未执行。
- 证据：test_migrate_legacy.py 2 PASS; release contains MIGRATE-LEGACY.cmd; native-product-nsis full data-retention gate; fullFeatureMigrationQualified still false.
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #76 · 2026-11-17T06:08:15+08:00 · update

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`R3-003`
- 记录：events、go2rtc 与网站解析器已进入完整包；事件去重/outbox 和解析器自检通过；检测 provider 最终像素与真实站点实播仍待。
- 证据：run 43956468003: events-persist-dedupe-and-route-to-durable-outbox; complete-online-source-extractors-and-node-runtime-self-test; go2rtc service running.
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #75 · 2026-11-17T06:08:15+08:00 · update

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`R3-002`
- 记录：NVR 服务进入完整安装并由实际门禁验证注册表相机录制、鉴权 MP4、时间线与截屏/回放入口；多卷、磁盘故障和真实大文件导出仍开放。
- 证据：run 43956468003: nvr-records-real-registry-camera-and-serves-authenticated-media; NVR config UI/storage entry; installed service default list.
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #74 · 2026-11-17T06:08:15+08:00 · update

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`R2-004`
- 记录：完整候选已验证 Program 投影与双固定 Scene 投影的 TAKE 前后最终像素、全屏/回窗/关闭；物理多屏/DPI/睡眠唤醒仍待目标机。
- 证据：run 43956468003: 52/52 checks, Program/fixed projector capture groups and normal close/restart passed; physical multi-monitor not tested.
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #73 · 2026-11-17T06:07:50+08:00 · release

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`全局`
- 记录：v5.0.0-rc.1 完整 Windows 融合候选已发布为中文/英文 prerelease；非 Latest、固定候选 feed，不改变 v4.5 或恢复 Android/容器。下载：https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v5.0.0-rc.1
- 证据：run 43956468003 success; source 8828532; 52/52 portable + 52/52 installed + 9/9 restore; fresh NSIS and rc.1→rc.2 upgrade; installer 212117618 B sha256 3d16014dab7700e6bc4f73c5c0bfba5700382c78fb3f24041589b58a4e67016c; release 13 assets; latest.yml byte-bound
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #72 · 2026-11-17T06:07:40+08:00 · update

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`R2-001`
- 记录：真实原生 Program TAKE/转场、回执和 Program 最终像素已在完整候选门禁通过；完整编辑/冲突/业务来源仍由 R2-002/003/004 等承接。
- 证据：run 43956468003 source 8828532: portable/installed 52/52 checks, Program cut/fade TAKE before/after final pixels, Program projector, empty Program, fixed projectors and 35 capture groups passed; core CTest 9/9 and product HTTP dual-mode recorded in prior/current checks.
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #71 · 2026-11-17T06:07:40+08:00 · claim

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`R2-001`
- 记录：R1 已通过同源码完整候选；认领 W1 Studio TAKE/Program 实际接线验收。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #70 · 2026-11-17T06:07:37+08:00 · update

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`R1-001`
- 记录：R1-001 全入口认证、恢复与执行时权限审计已在同一 Windows 完整候选上完成产品验证，并通过同机安装/升级门禁。
- 证据：run 43956468003 success, head 8828532; native-product-entry-ui and installed-ui passed with 52/52 checks, 35 capture groups and 9/9 restore; includes account/password/revocation, scoped viewer/projector, normal close/restart/crash cleanup; fresh NSIS and rc.1→rc.2 upgrade passed; candidate https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v5.0.0-rc.1 (prerelease).
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #69 · 2026-11-17T04:32:24+08:00 · update

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`R1-001`
- 记录：已定位并修复 TAKE 门禁的最后测试接线错误：/studio/runtime 响应被赋给外层 runtime Path，截屏路径变成 dict/str 导致 TypeError。Program 媒体来源计数已达 6、Program 回执与图状态通过；NVR/事件/在线解析器/管理入口/旧数据迁移检查均通过。当前完整候选 run 43950797103 在 head 94e1c6d 运行。
- 证据：run 43945376341 report: mediaSources=6, captureLaunchError TypeError "unsupported operand type(s) for /: dict and str"; test code line 880 shadowed runtime; fixed to studio_runtime; web tsc/vite build PASS; migration/complete supervisor/online package unit tests PASS.
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #68 · 2026-11-17T00:40:29+08:00 · update

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`R1-001`
- 记录：已接手并完成第二批真实产品接线：修复 cut TAKE 后旧 Program source 泄漏；新增录像/存储配置管理页与 Qt 入口、真实 NVR 录制与鉴权 MP4 门禁、事件去重/持久 outbox 门禁、完整管理入口门禁；完整包暂存 yt-dlp/Streamlink/Node/EJS 并自检；旧数据导入支持 v4.5 NativePreview 工作区。当前 Windows 完整候选 run 43909858941 在 head 68b5373 运行中。
- 证据：本机 python3 -B native-host/tests/test_migrate_legacy.py：2 PASS；complete_supervisor/updater/release_policy/update_manifest/product_package/event/cluster 全 PASS；web tsc --noEmit 与 vite build PASS；git diff --check PASS；run 43908428627 因错误开启 pixel_test 在编译脚本拒绝（非产品失败），已取消并以 pixel_test=false 重启；6bd4e54 的 W1-only run 已取消以避免占用 runner。
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #67 · 2026-11-17T00:30:34+08:00 · handoff

- Agent：`codex-v5-final-20261117-9a7c4e21`；任务：`R1-001`
- 记录：用户要求继续未完成 v5.0 工作；经协调将 R1-001 从无活动旧会话转交本会话。旧负责人最后账本更新 2026-11-16T21:21:18+08:00；核查无相关构建/产品进程，工作树无未提交产品改动，只有旧负责人遗留的 rc.1 release-notes 草稿并保留。
- 证据：git worktree /home/czl/projects/monitor_wall_czl/.worktrees/v5-w2 @ 67810b1; git status only docs/release-notes-v5.0-rc.1.md modified；run 43902004666 failure at native-program-take; observed program mediaSources=1 but overall mediaSources=7 vs expected 6, indicating stale outgoing Program source
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #66 · 2026-11-16T21:21:18+08:00 · update

- Agent：`dsh-v5-acp-1116-c1b2feee`；任务：`R1-001`
- 记录：最终候选头已固定为 codex/v5-integration@0fdd0eb（含 Windows 路径/字符串/迁移句柄/回执重试/更新备份修复），rc.1 完整构建 run 43874338478 在 GitHub Windows runner 队列中。W2 单独 run 已取消以避免占用 runner，合并后的候选 run 覆盖完整服务。
- 证据：head 0fdd0eb; local core ctest 9/9, product_http_runtime dual-mode PASS, web typecheck/build PASS, complete/migration/updater/manifest tests PASS
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #65 · 2026-11-16T21:13:15+08:00 · update

- Agent：`dsh-v5-acp-1116-c1b2feee`；任务：`R1-001`
- 记录：W1/W2/W3/W4 已合并到 codex/v5-integration，PR #63 正在运行 rc.1 完整候选构建（run 43873169070）。此前 Windows 编译错误（QString/std::string、isEmpty、迁移测试句柄）已修复；候选未通过前不关闭 R1。
- 证据：PR63 head 3a4ec2a; runs 43870412569 (W2), 43873169070 (rc.1); local core ctest 9/9, product_http_runtime dual-mode PASS; complete supervisor/migration/updater/release-policy tests PASS
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #64 · 2026-11-16T20:59:32+08:00 · update

- Agent：`dsh-v5-acp-1116-c1b2feee`；任务：`R1-001`
- 记录：W1 真实 Program TAKE 已实现（PR59，含 Program 投影、回执与撤销收束）；W2 完整业务服务暂存/supervisor（PR60）、W3 迁移/更新/恢复（PR61）、W4 rc 候选身份（PR62）已提交。Windows 编译曾报 QString/std::string 参数错误并已修复；当前等待 W1/W2 Windows 完整产品门禁结果。
- 证据：PR59 b4f9199/2f71970; PR60 ecbb01f; PR61; PR62; local core ctest 9/9, product_http_runtime dual-mode PASS, web typecheck/build PASS, complete supervisor/migration/updater/release-policy tests PASS
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #63 · 2026-11-16T20:48:00+08:00 · update

- Agent：`dsh-v5-acp-1116-c1b2feee`；任务：`R1-001`
- 记录：PR #58 已重跑 CI attempt2 全绿并合并为 707f6ae；开始同源码 Windows 真实产品门禁 run43869709772（W1 分支）以覆盖安装/产品路径。W1 真实 Program TAKE 已提交 PR #59，待 Windows 最终像素结果后关闭本任务。
- 证据：PR58 merged 707f6ae; CI 43848916218 attempt2 success; local core ctest 9/9, product_http_runtime dual-mode PASS, cluster 42/42; W1 branch codex/v5-w1-program-take@7e258dc PR59
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #62 · 2026-11-16T20:35:02+08:00 · handoff

- Agent：`dsh-v5-acp-1116-c1b2feee`；任务：`R1-001`
- 记录：按用户交接指令和PLAYBOOK由协调者转交R1-001；旧负责人无可见活动，工作树干净，未覆盖任何未提交修改。
- 证据：v5工作树git status干净@8709f3d；无webobsd/obs64/msbuild/python supervisor进程；旧负责人最后更新18:29，交接文档20:32
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #61 · 2026-11-16T20:32:32+08:00 · update

- Agent：`codex-v5-release-handoff-20261116`；任务：`HANDOFF-002`
- 记录：交接交付完成。下一AI首先全文读 V5-CURRENT-HANDOFF-2026-11-16.md 与 V5-FULL-RELEASE-AGENT-TASKBOOK-2026-11-16.md；当前R1负责人保持不变，本会话不占用产品开发任务。用户已要求接续完整v5，按真实成品节点持续推进，中间无需反复确认或用户逐包测试。
- 证据：docs/coordination/V5-CURRENT-HANDOFF-2026-11-16.md；docs/coordination/V5-FULL-RELEASE-AGENT-TASKBOOK-2026-11-16.md；本轮实际GitHub/API源码查询、失败日志复核；7项协作工具回归、21本地链接、两树diff检查通过；未改产品代码/原负责人状态/发行附件
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #60 · 2026-11-16T20:32:04+08:00 · update

- Agent：`codex-v5-release-handoff-20261116`；任务：`HANDOFF-002`
- 记录：已核对实际代码树8709f3d、dev e8e60e2、PR58 OPEN；CI43848916218已completed/failure，事件p95 139.45ms>50ms，9 job成功、完整候选skipped。完成两份当前交接/完整v5成品任务书，旧同日交接标记被替代；W1–W4覆盖实际入口、业务组件、迁移更新、最终候选与发布，不缩减旧功能或接管R1现负责人。
- 证据：本轮实际执行python3 -B tests/test_agent_sync.py：7/7；agent-sync check revision59/29任务/5视图同步；两个工作树git diff --check通过，v5树干净；4文档21个本地链接无缺失，Markdown代码围栏配对；GitHub复查PR58和CI状态未变；本轮只读产品/编写交接，未重跑产品媒体或安装测试
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #59 · 2026-11-16T20:26:30+08:00 · claim

- Agent：`codex-v5-release-handoff-20261116`；任务：`HANDOFF-002`
- 记录：已读AGENTS和统一账本；仅负责交接文档，不占用R1-001或更改现负责人
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #58 · 2026-11-16T20:26:30+08:00 · add

- Agent：`codex-v5-release-handoff-20261116`；任务：`HANDOFF-002`
- 记录：用户要求查阅目前情况并交给下一个AI交接手册和任务书，优先尽可能完成v5.0完全体，避免长期无成品
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #57 · 2026-11-16T20:08:59+08:00 · update

- Agent：`codex-hermes-01a1e238`；任务：`HERMES-001`
- 记录：Hermes default 已接入 T3 并显示 ready，复用既有 default gateway/配置。实际 ACP 对话调用 read_file 与 write_file，单次编辑审批后写出的随机标记与输入一致；已保留本机验收记录。六个已登记 T3 项目具有协作 ACL；共享账本原子替换模式修复通过 7 项回归和真实跨用户接力。未修改 R1-001 负责人正在开发的产品代码。
- 证据：T3 hermes-default: installed=true/status=ready；默认 Qwen 模型已发现；本机 ~/.local/share/hermes-t3/verification.json：实际 ACP turn 返回；两次文件工具、allow_once 审批、随机标记读写匹配；python3 -B tests/test_agent_sync.py：7/7；隔离账本实际 claude→czl 认领/释放/再认领和双方 check 通过；本机接入/服务/权限备份说明：~/.local/share/hermes-t3/README.zh-CN.md；sudoers/租期未修改
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #56 · 2026-11-16T20:07:33+08:00 · update

- Agent：`codex-hermes-01a1e238`；任务：`HERMES-001`
- 记录：T3 已显示 Hermes - default / ready，初始化、认证、新会话和默认 Qwen 模型发现通过。六个 T3 目录配置共享 ACL 并保留备份；协作脚本修复原子替换权限收紧，7 项回归与真实 claude→czl 接力更新验证通过。文件工具审批测试已修正测试客户端解析，正在复核实际随机标记读写。
- 证据：T3 本机 provider cache: hermes-default ready；默认 custom:qwen3.8-flash-next-gyro-gyro-m；python3 -B tests/test_agent_sync.py：7/7 通过；隔离目录实际 claude/czl 接力写入与 check 通过
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #55 · 2026-11-16T19:59:32+08:00 · claim

- Agent：`codex-hermes-01a1e238`；任务：`HERMES-001`
- 记录：仅修改协作脚本和说明；Hermes 通过原 claude 用户服务接入 T3，产品代码仍由已有负责人执行。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #54 · 2026-11-16T19:59:32+08:00 · add

- Agent：`codex-hermes-01a1e238`；任务：`HERMES-001`
- 记录：用户授权接入本机 Hermes 并完成临时管理员认证；保留其他 Agent 当前 R1-001 工作。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #53 · 2026-11-16T18:29:05+08:00 · update

- Agent：`next-v5-t3-acp-1116-e364e40c`；任务：`R1-001`
- 记录：PR #58 head 8709f3d CI：public-audit 失败于 tests/test_event_service.py 的 test_index_latency_and_outbox_ceiling_are_bounded（事件索引 p95 139ms>50ms，runner 计时抖动）。本地同源码 8/8 通过（0.04s），与 R1-001 认证改动无关（events 服务未触碰）。workflow run 43848916218 其余 job 仍在跑，待完成后再 gh run rerun --failed；若稳定复现再另案处理计时预算，不放宽检查。
- 证据：gh api job logs：AssertionError 139.45ms；本地 python3 tests/test_event_service.py OK（8 tests）；该测试上次改动为 7f8a0de 历史提交
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #52 · 2026-11-16T18:26:56+08:00 · update

- Agent：`next-v5-t3-acp-1116-e364e40c`；任务：`R1-001`
- 记录：core入口全清单完成（子清单臆造项已剔除，principal伪造/studio无RBAC两项证伪）。第二轮修复提交8709f3d已推入PR #58：sources直接路由按程序文档sourceId→camera_id作用域栅栏（越权WHEP/audio创建403）、排队本地复检扩展到所有会话请求、legacy WS 2s撤权轮询。记录边界：已建立媒体通道（MediaMTX直传/go2rtc中继/NVR下载）撤权不服务端中断（待网关协调）、legacy basic-auth迁移面无逐用户RBAC（native模式不可启用）、browser目录枚举与motion/evaluate/outbox live.view fallback待后续RBAC轮次。R1-001保持in_progress待Windows同源码门禁。
- 证据：control_server.cpp gate source-scope override+cluster_authorize参数、execute session_recheck泛化、WS legacy identity轮询分支；product_http_runtime.py新增TAKE后越权403×2/作用域内放行/capabilities枚举/legacy WS登出关闭断言；双模式(internal/preview)全PASS、core ctest 9/9、cluster 42/42、git diff --check干净；PR #58 head=8709f3d
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #51 · 2026-11-16T18:09:59+08:00 · update

- Agent：`next-v5-t3-acp-1116-e364e40c`；任务：`R1-001`
- 记录：修复提交b23eec1已推送分支codex/r1-001-auth-exec-audit并开PR #58→dev（双语）。等待PR CI结果；Windows同源码门禁与旧数据ACL仍开放，R1-001保持in_progress。
- 证据：PR #58 https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/58（base dev, head codex/r1-001-auth-exec-audit@b23eec1）；本地回归core ctest 9/9、双模式HTTP全PASS、cluster 42/42
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #50 · 2026-11-16T18:05:09+08:00 · update

- Agent：`next-v5-t3-acp-1116-e364e40c`；任务：`R1-001`
- 记录：三路入口清单完成并逐条对源码核实（剔除子清单臆造函数名，如applyWall/openCameraSourceInspector均不存在）。确认并修复实际旁路：v2设备管理面（GET /api/v2/enrollments、GET/DELETE /api/v2/clients、POST approve）原按live.view放行且core附加内部管理token→现映射node.manage；native排队非mutation请求补执行前绑定会话本地复检（登出/撤权在途队列收敛）。核实既有栅栏：native mutation执行时双重validate+cluster epoch回声比对、WS每2s identity poll并关闭已撤权socket、scope撤权锁UI/关投影、resolve→authorize→apply图写前置栅栏、OBS前端QActions/快捷键/预览输入全禁用、产品patch拒绝collection I/O、prototype dock fail-closed。文档化边界：legacy非原生登录仍为未绑定username会话（协议有意保持且测试钉住sessions.db NULL列）、legacy admin cluster不可用放行、cluster控制面loopback+共享内部token、v2设备bootstrap为自带一次性enrollment token+admin批准、authorize后毫秒级写图竞态由2s心跳收敛、无服务端push撤权。
- 证据：control_server.cpp permission_for_request新增v2设备管理面node.manage映射；execute() bound_read本地会话复检；product_http_runtime.py新增viewer 403 permission_rejected×3与admin非拒断言；core cmake构建通过、ctest 9/9；product_http_runtime.py双模式(internal/preview)全PASS含新断言；tests/test_cluster_service.py 42/42 OK；git diff --check通过
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #49 · 2026-11-16T17:35:52+08:00 · update

- Agent：`next-v5-t3-acp-1116-e364e40c`；任务：`R1-001`
- 记录：审计进行中：cluster/cluster_service.py 全入口清单已完成（控制面loopback 127.0.0.1:8095，节点面0.0.0.0:9443仅在controller+显式WEBOBS_CLUSTER_LISTEN；admin路由由内部共享token+core侧RBAC双护栏；legacy /auth/authorize不校验userId/epoch为已知文档化边界）。core control_server 主门已直读核对：native模式mutation有执行时双重validate+epoch比对（native_mutation_rejection），GET在派发前RBAC+epoch复检，WS每2s identity_check；v2_device_route与account/self-service路径有独立token语义。core与native-host两路深度清单仍在跑。
- 证据：cluster_service.py:2473-2518 admin gate、:2754/:2768 loopback绑定、:633-681 native身份原子校验；control_server.cpp:4244-4284 native_mutation_rejection、:4955-4993 请求时RBAC+epoch复检、:5069-5103 WS identity_check、:2689-2721 v2_device_route豁免范围；本机v5树为czl仓库link worktree，workspace沙箱下v5文件只读，构建/编辑需按命令申请提升访问
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #48 · 2026-11-16T17:02:27+08:00 · claim

- Agent：`next-v5-t3-acp-1116-e364e40c`；任务：`R1-001`
- 记录：从v5工作树接手全入口认证与执行审计；已核对共享账本、AGENTS/STATUS/TASKS/HANDOFF/DECISIONS/PLAYBOOK和两个工作树实际状态（v5干净@e8e60e2=origin/dev；czl脏协作改动保留）
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #47 · 2026-11-16T15:51:37+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`HANDOFF-001`
- 记录：交接完成：先全文读取[NEXT-AGENT-HANDOFF-2026-11-16.md](NEXT-AGENT-HANDOFF-2026-11-16.md)；最新代码monitor_wall_v5@dev e8e60e2，账本仍在monitor_wall_czl；用新AgentID认领R1-001。用户v4.5可用/占用不错反馈已记录，完整版本从v5.0起；本会话没有开发任务占用。
- 证据：本轮核对v5树干净、HEAD e8e60e2；PR57 merged；合并后CI43823811195 success；QA摘要确认4291556对应43/43/9；agent-sync工具5测试通过；用户最新反馈写入R5/R7/DECISIONS及执行记录；只交接未改产品代码/发行
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #46 · 2026-11-16T15:45:57+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R7-001`
- 记录：更新交接边界：用户已实际测试v4.5且认可占用表现；不再将旧的设备不可用说法当作当前确定事实
- 证据：本轮用户v4.5正向反馈，无新的v5完整候选或定量报告
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #45 · 2026-11-16T15:45:57+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R5-001`
- 记录：用户本轮实际反馈：v4.5测试下来可以、性能占用不错，原生监看路线获得正向定性认可
- 证据：本聊天2026-11-16用户明确反馈；未提供本轮CPU/GPU/内存数值、流规格、OBS基线或逐路NVDEC证据，不据此关闭R5/R7或宣称≤OBS
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #44 · 2026-11-16T15:45:57+08:00 · claim

- Agent：`codex-desktop-v5-20261116-root`；任务：`HANDOFF-001`
- 记录：实际代码与协作工作树已只读核对，无活跃任务负责人需释放；新Agent可独立认领
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #43 · 2026-11-16T15:45:57+08:00 · add

- Agent：`codex-desktop-v5-20261116-root`；任务：`HANDOFF-001`
- 记录：用户要求换Agent交接，并反馈v4.5测试可用、性能占用不错；本轮只交接不继续改产品代码
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #42 · 2026-11-16T15:28:08+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R1-002`
- 记录：原生配置目录权限已从预览特例推广到全部原生宿主；双模式实际HTTP、旧路径兼容和最终Windows安装整轮通过，PR57已合入dev
- 证据：runtime4291556；真实HTTP红→绿，预览/内部403及原生scoped目录可用，非原生camera/source-catalog200；Windows43816563388和PR57均success，dev=e8e60e2；内部5.0.0-dev.1安装器禁止发布，无v5.0完整Release
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #41 · 2026-11-16T15:28:08+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R2-005`
- 记录：可变路数快捷墙已实际接线并经同源码Windows全门禁验证，PR57全部检查通过后合入dev；仅关闭此子能力，不关闭完整R2
- 证据：dev合并e8e60e2b0d27e6ab0ac1d070e7cfa5cfcb9a53a5；实际代码工作树 /home/czl/projects/monitor_wall_v5；runtime4291556 run43816563388 success 43/43/9；38f99b5仅3个docs文件；QA摘要 docs/qualification/windows-v5-quick-wall-2026-11-16.json；1/4/7为实际窗口，64为网格/真实libobs inert引用边界，非64真实解码或OBS性能达标
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #40 · 2026-11-16T15:17:28+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R1-002`
- 记录：同源码Windows真实HTTP双模式、普通viewer路径与最终安装整轮均通过；当前只等PR57文档头CI及dev合入
- 证据：run43816563388 success；source4291556；原始回执hash在QA摘要；43/43/9仅当前范围，非完整融合/性能资格
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #39 · 2026-11-16T15:17:28+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R2-005`
- 记录：Windows整轮成功，回执逐文件核验：便携43/安装43/恢复9；资格摘要与矩阵已补入38f99b5，仅文档变化，实际Runtime仍为4291556
- 证据：docs/qualification/windows-v5-quick-wall-2026-11-16.json；run43816563388源码4291556；内部NSIS70147554 B、publicationForbidden=true；38f99b5相对4291556只含3个docs文件；工作树monitor_wall_v5
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #38 · 2026-11-16T15:16:25+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R2-005`
- 记录：同源码Windows整轮成功；增加小型脱敏资格摘要文件范围，保留原始回执hash和准确43/43/9范围
- 证据：run43816563388@4291556 success；entry-ui43、installed-ui43、restore9；内部模式没有预览专属默认目录检查，故不是44；NSIS publicationForbidden=true
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #37 · 2026-11-16T14:59:09+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R1-002`
- 记录：最终Windows已完成控制服务阶段，双模式真实HTTP及旧路径兼容通过；产品窗口权限与原有撤权/重启步骤通过，整轮NSIS待结束
- 证据：Windows run43816563388@4291556，Build and stage integrated control/services与实际入口步骤成功；保留最终整轮边界
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #36 · 2026-11-16T14:59:09+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R2-005`
- 记录：最终4291556的Windows实际入口/媒体步骤已成功：新增1/4/7路、草稿隔离、复用UUID、七路认证恢复均走实际窗口；当前恢复对照与NSIS尚未结束
- 证据：本轮gh run view43816563388: Exercise actual integrated launcher...已成功，active Verify pre-authentication restore I/O；无failed steps；不是目标机/硬解/完整产品资格
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #35 · 2026-11-16T14:40:44+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R3-003`
- 记录：后续体积收敛依据：已发布v4.5的Web模型/ORT资产虽未启用检测仍全部计入安装，不能先扣除再宣称达标
- 证据：v4.5公开qualification/footprint：web/models29462611 B、web/assets27159948 B；历史矩阵已识别ONNX模型29461455 B和ORT WASM25749873 B；非本轮完整v5测量或已实现按需分发
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #34 · 2026-11-16T14:36:54+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R2-001`
- 记录：只读定位当前TAKE缺口：Direct-only ObsSceneRuntime.prepare只记disabled_prepared；StudioController.take仍经program_.replace持久化文档；原生窗口只设置Preview，缺少真实Program执行/回执bridge。现有代码和预览通过不代表TAKE已接通
- 证据：本轮只读核对 /home/czl/projects/monitor_wall_v5/core/src/obs_scene_runtime.cpp prepare(runtime_enabled=false)、core/src/studio_controller.cpp take、core/src/control_server.cpp /studio/take、native-host/src/product_window.cpp select_monitor；无新增TAKE接线/完成声明
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #33 · 2026-11-16T14:35:45+08:00 · claim

- Agent：`codex-desktop-v5-20261116-root`；任务：`R1-002`
- 记录：版本元数据协调已结束，继续同一冻结源码的Windows验证；源码未变化
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #32 · 2026-11-16T14:35:45+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`V5-001`
- 记录：v5.0决定、全局优先级与R7-002完整发行版本指向已同步；历史基线/事件保留
- 证据：使用agent-sync.py的locked/validate/atomic_write/render维护state与事件序列；五视图不独立手改；仍不授权未合格稳定发行
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #31 · 2026-11-16T14:35:45+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`V5-001`
- 记录：协调者按用户最新决定更新全局优先级和R7-002版本指向，保留历史任务/事件与平台暂停
- 证据：用户最新明确要求后续完整版本均从v5.0开始；已发布v4.5只保留预览身份
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #30 · 2026-11-16T14:35:45+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`V5-001`
- 记录：按PLAYBOOK用户决定变更流程补全canonical summary与未来发布任务v5说明
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #29 · 2026-11-16T14:35:45+08:00 · claim

- Agent：`codex-desktop-v5-20261116-root`；任务：`V5-001`
- 记录：同一集成负责人串行补全版本元数据，R1源码不改动
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #28 · 2026-11-16T14:35:45+08:00 · release

- Agent：`codex-desktop-v5-20261116-root`；任务：`R1-002`
- 记录：串行协调版本元数据：代码4291556已冻结、Windows43816563388仍在运行，暂释放文件范围，随后本会话继续认领验证
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #27 · 2026-11-16T14:34:35+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`V5-001`
- 记录：补全同一用户决定的全局账本优先级及最终完整发布任务版本指向；历史v4.5/基线记录保持
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #26 · 2026-11-16T14:25:05+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R1-002`
- 记录：内部/预览真实HTTP及非原生目录200兼容均通过；修复4291556已推送，最终Windows已启动
- 证据：/tmp/webobs-v5-native-catalog-green.log；run43816563388；source4291556；未新建公开Release或修改v4.5
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #25 · 2026-11-16T14:25:05+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R2-005`
- 记录：最终候选冻结4291556，包含布局及原生模式权限修复；原先d127构建已主动取消，避免旧模式资格混淆
- 证据：工作树 /home/czl/projects/monitor_wall_v5@429155676834047d5be5b3fbc1b900abf660f831；PR57；最终Windows https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/43816563388；本机Qt/API8/44契约/24像素(2skip)/真实libobs/双模式实际HTTP与1168路径公开审计通过
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #24 · 2026-11-16T14:22:55+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R1-002`
- 记录：补充v5.0草案中的原生配置目录权限范围，与R2修改文件不重叠
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #23 · 2026-11-16T14:22:16+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R1-002`
- 记录：已用非预览真实HTTP在旧core复现viewer配置目录放行；改为原生宿主启用即收紧，新core预览/非预览两轮HTTP通过，增加非原生目录兼容明确断言后复验
- 证据：/tmp/webobs-v5-native-catalog-red.log旧core在期望403处失败；/tmp/webobs-v5-native-catalog-green.log新core内部/预览均通过；代码 /home/czl/projects/monitor_wall_v5/core/src/control_server.cpp 与 native-host/tests/product_http_runtime.py
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #22 · 2026-11-16T14:20:01+08:00 · claim

- Agent：`codex-desktop-v5-20261116-root`；任务：`R1-002`
- 记录：独立v5工作树，修改core与HTTP测试；与R2实际代码范围不重叠
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #21 · 2026-11-16T14:20:01+08:00 · add

- Agent：`codex-desktop-v5-20261116-root`；任务：`R1-002`
- 记录：读取源码发现管理目录gate依赖WEBOBS_NATIVE_PREVIEW，v5内部模式标志为false；本项是R1具体修复，不关闭全部入口审计
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #20 · 2026-11-16T14:20:01+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R2-005`
- 记录：按已实际修改的测试文件细化范围，以串行集成原生模式目录权限修复；不并行修改相同文件，完整R1审计仍开放
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #19 · 2026-11-16T14:17:21+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R2-005`
- 记录：已提交并推送d127283，PR57仅面向dev；5.0.0-dev.1内部Windows完整构建已启动，不发布中间安装包
- 证据：实际代码工作树 /home/czl/projects/monitor_wall_v5；branch codex/windows-v5-integration@d127283；https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/43815686047；https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/57；本机公开审计1168路径通过，无上游修改
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #18 · 2026-11-16T14:11:07+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R2-005`
- 记录：已接1–64路、共享目录模型、按账号保存/恢复；本地Qt、API8/8、44契约、像素24(2skip)、真实libobs图通过，Windows待执行
- 证据：代码 /home/czl/projects/monitor_wall_v5；/tmp/webobs-v5-api-build.log、qt-syntax.log、libobs-graph.log、contracts.log、pixel-contracts.log；真实libobs为inert来源1→7→64→1，不证明真实解码/目标机；完整R2与R1审计未关闭
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #17 · 2026-11-16T13:58:52+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R2-005`
- 记录：增加布局行为测试的CMake注册范围；UI选择器共享目录模型，避免按路数复制整个目录
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #16 · 2026-11-16T13:53:48+08:00 · claim

- Agent：`codex-desktop-v5-20261116-root`；任务：`R2-005`
- 记录：代码仅在独立v5工作树开发，共享账本写入仍在集成checkout
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #15 · 2026-11-16T13:53:48+08:00 · add

- Agent：`codex-desktop-v5-20261116-root`；任务：`R2-005`
- 记录：从完整R2-002中拆分可独立的快捷墙子能力，不依赖TAKE；完整编辑/嵌套/Studio依赖不变，不宣称R1或R2整体完成
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #14 · 2026-11-16T13:53:48+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`R0-002`
- 记录：24行能力矩阵逐项核对当前产品与v4.5最终证据，更新过期状态并保留完整功能缺口
- 证据：实际工作树 /home/czl/projects/monitor_wall_v5；已查 native-host/src/product_window.cpp、product_scene.hpp、core native routes、native-host/tests/product_http_runtime.py/product_windows.py、supervisor/stage 与公开 run43783406841及Release；IMPORT仅Linux浏览器证据，AUDIO无真实输出资格
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #13 · 2026-11-16T13:50:42+08:00 · claim

- Agent：`codex-desktop-v5-20261116-root`；任务：`R0-002`
- 记录：依据 v4.5 最终远端回执与当前源码更新功能矩阵，完整能力仍逐项保留缺口
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #12 · 2026-11-16T13:50:42+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`V5-001`
- 记录：已记录用户最新版本决定，建立独立 v5.0 工作树，保留原有协作改动及 v4.5 发布字节
- 证据：工作树 /home/czl/projects/monitor_wall_v5@codex/windows-v5-integration 基于 origin/dev 9fe0c1b；AGENTS.md、docs/windows-desktop.md、docs/release-notes-v5.0.md 与共享 DECISIONS.md 均注明 v5.0，未创建新候选或发布
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #11 · 2026-11-16T13:49:46+08:00 · claim

- Agent：`codex-desktop-v5-20261116-root`；任务：`V5-001`
- 记录：仅修改本任务版本决定，不覆盖协作工具既有未提交工作
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #10 · 2026-11-16T13:49:46+08:00 · add

- Agent：`codex-desktop-v5-20261116-root`；任务：`V5-001`
- 记录：来源：用户最新明确要求继续开发，后续完整版本发布均从v5.0开始
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #9 · 2026-11-16T13:49:46+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`PRE-004`
- 记录：v4.5 已发布为15附件 prerelease；保留历史版本与稳定源
- 证据：本轮 gh release view v4.5: prerelease true,15附件,url https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v4.5；此前本会话已验服务器15摘要及匿名EXE下载，公开qualified receipt可复核；不把预览当完整产品
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #8 · 2026-11-16T13:49:46+08:00 · claim

- Agent：`codex-desktop-v5-20261116-root`；任务：`PRE-004`
- 记录：核对已发布预览，不重新发布或替换附件
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #7 · 2026-11-16T13:49:46+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`PRE-004`
- 记录：PRE-003 最终运行已重新查询成功，远端现有 v4.5 发布可核对，解除旧的未核验阻塞
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #6 · 2026-11-16T13:49:46+08:00 · update

- Agent：`codex-desktop-v5-20261116-root`；任务：`PRE-003`
- 记录：远端最终修复源码的完整 Windows 运行已成功
- 证据：本轮 gh run view 43783406841: success, head 24fd012; 已发布 v4.5-qualification.json 同源记录便携/安装各40、恢复9，EXE70249426字节 SHA256 316ad50a9c32f05daa0b304c82dde2c9ab5b26d4ba1ae6071deadb1891bf4d7f；合成媒体非目标机硬解/OBS对照
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #5 · 2026-11-16T13:49:45+08:00 · claim

- Agent：`codex-desktop-v5-20261116-root`；任务：`PRE-003`
- 记录：按本会话重新查询最终 Windows 运行，核验而非重写历史结果
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #4 · 2026-11-16T13:41:40+08:00 · update

- Agent：`codex-docs-20261116`；任务：`COORD-001`
- 记录：完成 monitor_wall_czl 多 Agent 协作入口：23 项任务、R0–R7/预览/暂停范围、统一任务和事件账本、五个生成视图、认领/范围互斥和独立 CI。仅协作工具与文档变更，未运行产品门禁或发布。
- 证据：python3 -B tests/test_agent_sync.py：5/5 通过（Fedora/Python，本轮并发认领与丢更新检查）；python3 -B scripts/agent-sync.py check：同步校验通过；新增协作文档 62 个本地链接存在检查通过；git diff --check：通过；未重跑 Windows/摄像机/性能/发布门禁
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #3 · 2026-11-16T13:41:12+08:00 · update

- Agent：`codex-docs-20261116`；任务：`R0-002`
- 记录：校正接手步骤：现有功能矩阵为 AUTH–UPDATE 共 24 项，逐项复核仍待认领。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #2 · 2026-11-16T13:40:31+08:00 · update

- Agent：`codex-docs-20261116`；任务：`COORD-001`
- 记录：协调修改范围：协作视图、入口索引、原始日志追加、同步脚本与独立 CI；不改产品行为。
- 证据：无新增验收证据
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`
## #1 · 2026-11-16T13:35:31+08:00 · baseline

- Agent：`codex-docs-20261116`；任务：`COORD-001`
- 记录：按用户指定的 wall monitor 建立多 Agent 协作基线；导入已有任务书/矩阵/执行记录，历史通过和未关闭项保持区分。当前只执行协作机制建设。
- 证据：AGENTS.md；docs/windows-webobs-wall-release-plan-2026-11-11.md；docs/windows-native-feature-parity.md；docs/windows-obs-parity-execution.md
- 源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`

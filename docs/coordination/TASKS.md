# 任务与认领 / Tasks and ownership

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 233 · 2026-11-19T02:11:41+08:00（UTC+08）

[总览](STATUS.md) · [路线图](ROADMAP.md) · [任务](TASKS.md) · [日志](DEVLOG.md) · [交接](HANDOFF.md) · [协作规则](PLAYBOOK.md)

| ID | 优先级 | 状态 | 负责人 | 任务 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| COORD-001 | P0 | 完成 | — | 建立统一任务账本、开发日志、认领和交接机制 | — |
| R0-001 | P1 | 完成 | — | 冻结本轮仓库基线和已知验证边界 | — |
| R0-002 | P1 | 完成 | — | 把功能迁移矩阵逐项更新到当前源码 | R0-001 |
| PRE-001 | P0 | 完成 | — | 修复首用管理入口及包内 Web root 门禁接线 | — |
| PRE-002 | P0 | 完成 | — | 修正公开 NativePreview 目录的恢复测试夹具 | — |
| PRE-003 | P0 | 完成 | — | 核对并完成最终 v4.5 Windows 同源码全门禁 | PRE-001, PRE-002 |
| PRE-004 | P0 | 完成 | — | 固定附件并核验预览发布身份 | PRE-003 |
| R1-001 | P1 | 完成 | — | 完成全入口认证、恢复与执行时权限审计 | R0-002 |
| R2-001 | P1 | 完成 | — | 连接完整 Studio 原子控制、TAKE 和转场 | R1-001 |
| R2-002 | P1 | 待开始 | — | 补齐多场景嵌套、编辑和不限五路布局 | R2-001 |
| R2-003 | P1 | 完成 | — | 完成多轨音频适配、监听和电平 | R1-001 |
| R2-004 | P1 | 待开始 | — | 完成 Program 投影、多屏 DPI 和恢复 | R2-001 |
| R3-001 | P2 | 待开始 | — | 回接设备控制 PTZ、快照与对讲 | R1-001 |
| R3-002 | P2 | 待开始 | — | 回接输出、NVR、回放和证据 | R2-001, R2-003 |
| R3-003 | P2 | 待开始 | — | 回接事件、检测、go2rtc 与网站来源可选组件 | R1-001 |
| R3-004 | P2 | 待开始 | — | 回接远端、离线同步、问题中心和诊断 | R2-001 |
| R4-001 | P2 | 待开始 | — | 实现并验证旧完整产品数据迁移及回退 | R2-002, R2-003 |
| R4-002 | P2 | 待开始 | — | 完善原生托盘、后台任务、更新与失败恢复 | R4-001, R3-002 |
| R5-001 | P2 | 待开始 | — | 完成完整功能进程/安装成本与自动化长稳 | R2-002, R2-003, R2-004, R3-001, R3-002, R3-003, R3-004, R4-002 |
| R6-001 | P2 | 待开始 | — | 冻结完整 Release 候选与发布材料 | R5-001 |
| R7-001 | P2 | 阻塞 | — | 集中目标机真实五路、旧数据和 OBS 对照 | R6-001 |
| R7-002 | P2 | 待开始 | — | 按审查后的 v5.0 及后续完整版本流程完成稳定交付 | R7-001 |
| HOLD-001 | P2 | 暂停 | — | Android、容器及扩展平台后续交付 | — |
| V5-001 | P1 | 完成 | — | 登记完整版本从 v5.0 开始并建立隔离开发入口 | — |
| R2-005 | P1 | 完成 | — | 将原生快捷监看从固定五路扩展为有界可变路数 | PRE-003 |
| R1-002 | P1 | 完成 | — | 把管理目录权限收紧覆盖到所有原生宿主模式 | R0-002 |
| HANDOFF-001 | P1 | 完成 | — | 交接v5开发并记录用户v4.5实机反馈 | — |
| HERMES-001 | P1 | 完成 | — | 接入 Hermes 并验证跨用户协作文件权限 | — |
| HANDOFF-002 | P0 | 完成 | — | 核对最新开发并交接v5.0完整成品执行任务书 / hand off full v5.0 delivery | — |
| AUDIT-001 | P0 | 完成 | — | 核查rc.1发布证据及完整候选缺口 / audit rc.1 release and integration gaps | — |
| V51-001 | P0 | 完成 | — | 登记v5.1完整修复与正式交付目标 / record v5.1 full delivery target | — |
| FIX-001 | P0 | 完成 | — | 修复已复现迁移与原生更新缺陷 / fix migration and updater regressions | AUDIT-001 |
| V51-002 | P0 | 完成 | — | 接通v5.1构建与真实安装更新门禁 / wire v5.1 build and installed update gates | FIX-001 |
| HANDOFF-003 | P0 | 完成 | — | 交接v5.1接续开发与正式交付 / hand off v5.1 completion | — |
| HANDOFF-004 | P0 | 完成 | — | 编写 DeepSeek 的 v5.1 成品执行指南 / write the v5.1 completion guide | — |
| V51-004 | P1 | 完成 | — | 补齐 v5.1 稳定发布身份与 Tag／版本映射 / add v5.1 stable release identity and tag mapping | V51-002 |
| V51-005 | P1 | 进行中 | deepseek-v51-20261118-01 | 候选发布脚本改用统一 Tag 映射与 main 祖先校验 / use shared Tag mapping and main ancestry check in candidate publisher | — |
| V51-006 | P1 | 待开始 | — | 接通稳定打包身份与验收文件单一契约 / wire stable packaging identity with one acceptance-file contract | V51-004 |
| V51-007 | P1 | 进行中 | deepseek-v51-20261118-01 | 加固双目录加密备份的中间故障一致性与安全重试 / harden dual-directory backup swap consistency and safe retry | — |
| V51-008 | P1 | 进行中 | deepseek-v51-20261118-01 | 把 Program 合成输出验收落到用户实际收到的产物 / accept Program output from the delivered recording and stream | — |
| COORD-008 | P1 | 完成 | — | 记录 CI 下载临时目录约定 / document temporary directories for CI downloads | — |
| V51-009 | P0 | 待开始 | — | 接通原生产品真实 LAN/Web HTTPS 入口 / wire the real LAN HTTPS entry into the native product | — |
| V51-010 | P1 | 进行中 | deepseek-v51-20261118-01 | 修已安装 LAN 门禁的首账号流程与无私网地址诚实降级 / fix installed LAN gate first-account flow and honest no-private-address degradation | — |
| V51-011 | P1 | 进行中 | deepseek-v51-20261118-01 | 实现安装态长稳门禁并接入 soak_minutes / implement the installed soak gate behind soak_minutes | — |
| V51-012 | P1 | 进行中 | deepseek-v51-20261118-01 | 编写 v5.1 候选发布说明并更新功能矩阵证据 / write the v5.1 candidate release notes and update the parity matrix | — |
| V51-013 | P1 | 进行中 | deepseek-v51-20261118-01 | 用安装态门禁实跑 ONVIF 设备操作与权限拒绝 / exercise ONVIF device operations in the installed gate | — |
| V51-014 | P1 | 进行中 | deepseek-v51-20261118-01 | 在已安装完整产品上验收旧数据导入入口与保留 / qualify the shipped old-data import path in the installed product | R1-001, V51-002 |

## COORD-001 · 建立统一任务账本、开发日志、认领和交接机制

- 修改范围：`docs/coordination`, `scripts/agent-sync.py`, `tests/test_agent_sync.py`, `AGENTS.md`, `README.md`, `ROADMAP.md`, `docs/handover.md`, `docs/windows-native-feature-parity.md`, `docs/windows-obs-parity-execution.md`, `.gitignore`, `.github/workflows/agent-coordination.yaml`
- 验收：并发认领不覆盖他人任务；生成视图可校验，完成必须有本轮证据；入口文档指向同一当前进度
- 下一步：后续 Agent 阅读 AGENTS/STATUS/HANDOFF，按优先级认领 PRE-003 或 R0-002，先核对现有实际证据。
- 阻塞：无
- 证据：python3 -B tests/test_agent_sync.py：5/5 通过（Fedora/Python，本轮并发认领与丢更新检查）；python3 -B scripts/agent-sync.py check：同步校验通过；新增协作文档 62 个本地链接存在检查通过；git diff --check：通过；未重跑 Windows/摄像机/性能/发布门禁
- 最新记录：完成 monitor_wall_czl 多 Agent 协作入口：23 项任务、R0–R7/预览/暂停范围、统一任务和事件账本、五个生成视图、认领/范围互斥和独立 CI。仅协作工具与文档变更，未运行产品门禁或发布。
- 最近更新：2026-11-16T13:41:40+08:00

## R0-001 · 冻结本轮仓库基线和已知验证边界

- 修改范围：`docs/coordination/state.json`
- 验收：保留当前源码身份；区分代码修复、历史 CI、最终资格和发行状态
- 下一步：后续更新必须记录新的实际源码/证据身份。
- 阻塞：无
- 证据：基线提交 24fd012ea8ee130ffb9d42473c489d708c9326c3；AGENTS.md：2026-11-16 v4.5 预览决定；docs/windows-obs-parity-execution.md：末尾两次失败和修复记录
- 最新记录：导入已有文档/源码证据；本轮没有重跑历史产品门禁。
- 最近更新：2026-11-16T13:35:31+08:00

## R0-002 · 把功能迁移矩阵逐项更新到当前源码

- 修改范围：`docs/windows-native-feature-parity.md`
- 验收：AUTH–UPDATE 各项映射到真实入口；旧 dev.92/94 与后续修复证据分开；旧实现可用不等于原生完成
- 下一步：推进可独立开发的快捷墙可变布局；完整R1/R2 Studio链继续开放
- 阻塞：无
- 证据：实际工作树 /home/czl/projects/monitor_wall_v5；已查 native-host/src/product_window.cpp、product_scene.hpp、core native routes、native-host/tests/product_http_runtime.py/product_windows.py、supervisor/stage 与公开 run43783406841及Release；IMPORT仅Linux浏览器证据，AUDIO无真实输出资格
- 最新记录：24行能力矩阵逐项核对当前产品与v4.5最终证据，更新过期状态并保留完整功能缺口
- 最近更新：2026-11-16T13:53:48+08:00

## PRE-001 · 修复首用管理入口及包内 Web root 门禁接线

- 修改范围：`core/src/control_server.cpp`, `tests/account_proxy_runtime.py`
- 验收：两种明确管理入口映射正确 HTML；未登录 API 仍拒绝；Windows 检查使用包内 UI
- 下一步：最终 Windows 运行仍需包含此修复。
- 阻塞：无
- 证据：docs/windows-obs-parity-execution.md：v4.5 首用管理入口、Windows HTTP 门禁目录；提交 ecf6251、44273ff；记录中的 Linux 实际 HTTP/浏览器结果（历史证据）
- 最新记录：导入已有文档/源码证据；本轮没有重跑历史产品门禁。
- 最近更新：2026-11-16T13:35:31+08:00

## PRE-002 · 修正公开 NativePreview 目录的恢复测试夹具

- 修改范围：`native-host/tests`
- 验收：公开预览忽略内部测试覆盖值；夹具使用隔离 LOCALAPPDATA 实际目录；保留未保护正对照、认证前零 RTSP 和回收要求
- 下一步：在最终修复 SHA 上重跑，不沿用此前失败运行。
- 阻塞：无
- 证据：24fd012：修正恢复门禁目录；docs/windows-obs-parity-execution.md：v4.5 公开目录恢复测试（源码修复；最终 CI 未复核）
- 最新记录：导入已有文档/源码证据；本轮没有重跑历史产品门禁。
- 最近更新：2026-11-16T13:35:31+08:00

## PRE-003 · 核对并完成最终 v4.5 Windows 同源码全门禁

- 修改范围：`.github/workflows/windows-native-monitor-release.yaml`, `native-host/tests`
- 验收：查询最终修复 SHA 对应实际运行；便携/真实 NSIS/HTTP/恢复 I/O/重启均通过；回执绑定实际源码、版本、安装字节和摘要
- 下一步：核对已发布 v4.5 附件与预览身份
- 阻塞：无
- 证据：本轮 gh run view 43783406841: success, head 24fd012; 已发布 v4.5-qualification.json 同源记录便携/安装各40、恢复9，EXE70249426字节 SHA256 316ad50a9c32f05daa0b304c82dde2c9ab5b26d4ba1ae6071deadb1891bf4d7f；合成媒体非目标机硬解/OBS对照
- 最新记录：远端最终修复源码的完整 Windows 运行已成功
- 最近更新：2026-11-16T13:49:46+08:00

## PRE-004 · 固定附件并核验预览发布身份

- 修改范围：`docs/release-notes-v4.5.md`, `docs/windows-v4.5-quickstart.md`
- 验收：仅使用通过门禁的最终字节；prerelease、非 Latest、无稳定 updater feed；独立数据目录及未提供功能明确
- 下一步：完整融合版进入 v5.0 开发，R0-R7仍开放
- 阻塞：无
- 证据：本轮 gh release view v4.5: prerelease true,15附件,url https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v4.5；此前本会话已验服务器15摘要及匿名EXE下载，公开qualified receipt可复核；不把预览当完整产品
- 最新记录：v4.5 已发布为15附件 prerelease；保留历史版本与稳定源
- 最近更新：2026-11-16T13:49:46+08:00

## R1-001 · 完成全入口认证、恢复与执行时权限审计

- 修改范围：`native-host/src`, `core/src`, `cluster/cluster_service.py`
- 验收：恢复/编辑/输出旁路无越权媒体 I/O；账号身份/epoch/角色变化在执行时生效；真实服务和 Windows 产品验证覆盖
- 下一步：R2-001 已解锁；继续 R2-002/003/004 与 R3-R7，最终目标机验收另行登记。
- 阻塞：无
- 证据：cluster_service.py:2473-2518 admin gate、:2754/:2768 loopback绑定、:633-681 native身份原子校验；control_server.cpp:4244-4284 native_mutation_rejection、:4955-4993 请求时RBAC+epoch复检、:5069-5103 WS identity_check、:2689-2721 v2_device_route豁免范围；本机v5树为czl仓库link worktree，workspace沙箱下v5文件只读，构建/编辑需按命令申请提升访问；control_server.cpp permission_for_request新增v2设备管理面node.manage映射；execute() bound_read本地会话复检；product_http_runtime.py新增viewer 403 permission_rejected×3与admin非拒断言；core cmake构建通过、ctest 9/9；product_http_runtime.py双模式(internal/preview)全PASS含新断言；tests/test_cluster_service.py 42/42 OK；git diff --check通过；PR #58 https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/58（base dev, head codex/r1-001-auth-exec-audit@b23eec1）；本地回归core ctest 9/9、双模式HTTP全PASS、cluster 42/42；control_server.cpp gate source-scope override+cluster_authorize参数、execute session_recheck泛化、WS legacy identity轮询分支；product_http_runtime.py新增TAKE后越权403×2/作用域内放行/capabilities枚举/legacy WS登出关闭断言；双模式(internal/preview)全PASS、core ctest 9/9、cluster 42/42、git diff --check干净；PR #58 head=8709f3d；gh api job logs：AssertionError 139.45ms；本地 python3 tests/test_event_service.py OK（8 tests）；该测试上次改动为 7f8a0de 历史提交；PR58 merged 707f6ae; CI 43848916218 attempt2 success; local core ctest 9/9, product_http_runtime dual-mode PASS, cluster 42/42; W1 branch codex/v5-w1-program-take@7e258dc PR59；PR59 b4f9199/2f71970; PR60 ecbb01f; PR61; PR62; local core ctest 9/9, product_http_runtime dual-mode PASS, web typecheck/build PASS, complete supervisor/migration/updater/release-policy tests PASS；PR63 head 3a4ec2a; runs 43870412569 (W2), 43873169070 (rc.1); local core ctest 9/9, product_http_runtime dual-mode PASS; complete supervisor/migration/updater/release-policy tests PASS；head 0fdd0eb; local core ctest 9/9, product_http_runtime dual-mode PASS, web typecheck/build PASS, complete/migration/updater/manifest tests PASS；本机 python3 -B native-host/tests/test_migrate_legacy.py：2 PASS；complete_supervisor/updater/release_policy/update_manifest/product_package/event/cluster 全 PASS；web tsc --noEmit 与 vite build PASS；git diff --check PASS；run 43908428627 因错误开启 pixel_test 在编译脚本拒绝（非产品失败），已取消并以 pixel_test=false 重启；6bd4e54 的 W1-only run 已取消以避免占用 runner。；run 43945376341 report: mediaSources=6, captureLaunchError TypeError "unsupported operand type(s) for /: dict and str"; test code line 880 shadowed runtime; fixed to studio_runtime; web tsc/vite build PASS; migration/complete supervisor/online package unit tests PASS.；run 43956468003 success, head 8828532; native-product-entry-ui and installed-ui passed with 52/52 checks, 35 capture groups and 9/9 restore; includes account/password/revocation, scoped viewer/projector, normal close/restart/crash cleanup; fresh NSIS and rc.1→rc.2 upgrade passed; candidate https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v5.0.0-rc.1 (prerelease).
- 最新记录：R1-001 全入口认证、恢复与执行时权限审计已在同一 Windows 完整候选上完成产品验证，并通过同机安装/升级门禁。
- 最近更新：2026-11-17T06:07:37+08:00

## R2-001 · 连接完整 Studio 原子控制、TAKE 和转场

- 修改范围：`native-host/src`, `core/src`, `web/src`
- 验收：产品文档 revision 与 OBS frontend 执行一致；Preview 不隐式改变 Program；TAKE/转场实际最终像素通过
- 下一步：继续 R2-002 多场景编辑/嵌套、R2-003 多轨音频和 R2-004 目标机多屏/DPI。
- 阻塞：无
- 证据：本轮只读核对 /home/czl/projects/monitor_wall_v5/core/src/obs_scene_runtime.cpp prepare(runtime_enabled=false)、core/src/studio_controller.cpp take、core/src/control_server.cpp /studio/take、native-host/src/product_window.cpp select_monitor；无新增TAKE接线/完成声明；run 43956468003 source 8828532: portable/installed 52/52 checks, Program cut/fade TAKE before/after final pixels, Program projector, empty Program, fixed projectors and 35 capture groups passed; core CTest 9/9 and product HTTP dual-mode recorded in prior/current checks.
- 最新记录：真实原生 Program TAKE/转场、回执和 Program 最终像素已在完整候选门禁通过；完整编辑/冲突/业务来源仍由 R2-002/003/004 等承接。
- 最近更新：2026-11-17T06:07:40+08:00

## R2-002 · 补齐多场景嵌套、编辑和不限五路布局

- 修改范围：`native-host/src`, `web/src`
- 验收：层级/裁剪/锁定/嵌套/来源标识保留；保存/重开/冲突和远端一致；不同布局来源共享可解释
- 下一步：依据 STUDIO/LAYOUT 矩阵逐项接线，保留既有五路回归。
- 阻塞：无
- 证据：尚未提供
- 最新记录：协作基线登记；尚未执行本项。
- 最近更新：2026-11-16T13:35:31+08:00

## R2-003 · 完成多轨音频适配、监听和电平

- 修改范围：`native-host/src`, `web/src`
- 验收：空选择/缺失轨/非空逐轨语义正确；账号监听偏好与输出轨道分开；实际音频无重复输出
- 下一步：已由 #67 承接 Program 输出验收
- 阻塞：无
- 证据：https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44211809863；gh run view 44224335029 --log-failed：failurePhase=native-program-take，programApplyState=applied，programSceneId=fixture-alt，audioSources[0].sourceId=fixture-alt.fixture-alt-source，peakDbfs=-20.866，mixers=2，available=true；obs 日志显示 WebOBS audio mix fixture-1 断开后 2.3s 重连。；本机 python3 -B native-host/tests/test_build_contract.py 44/44 OK（两树）；native-host/tests/test_complete_supervisor.py PASS；test_product_package.py 6/6 OK；pixel_windows.tone_probe 实测 /tmp 合成双音轨文件返回 (2895.2,439.8)/(2887.5,879.8)，band_rms 混合样本 2620/1727、带外高通 20.9；py_compile 两个测试文件通过；git diff --check 通过。Windows rc.25 run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44236342016（head 98e1e99，当前步骤 11 编译 OBS 前端/插件）。；https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44236342016 steps 13-14 success；codex/v51-r3-output e20dd28 已推送；rc.31 run 44261174753 派发（rc.31 未被 Tag/Release 占用）；rc.27/rc.30 回执 recordingError=recording-start-failed 且 last_error 为空；rc.29 在 program-after-take 出现 window-identity 失效；PR #66 merged into dev (merge commit be9c231 'merge: 合并v5.1原生多轨音频混音与电平')；Windows run 44224335029 之后的 rc.32 run 44266163975 门禁内 programAudio mixers=2、peakDbfs=-20.02、programRecordingBandRms below600=1380.5/above660=908.8（多轨总线证据）
- 最新记录：多轨音频已双语合并进 dev（PR #66），本机与 Windows 门禁证据已在案
- 最近更新：2026-11-18T17:20:59+08:00

## R2-004 · 完成 Program 投影、多屏 DPI 和恢复

- 修改范围：`native-host/src`, `native-host/tests`, `native-host/CMakeLists.txt`, `docs/release-notes-v5.1.md`, `docs/windows-native-feature-parity.md`, `docs/windows-obs-parity-execution.md`
- 验收：Program 与固定 Scene 角色不混淆；多屏/DPI/全屏/重开和撤权覆盖；持久恢复不重复创建来源
- 下一步：串行释放范围回到实际Windows管线和更新故障；之后认领继续固定场景媒体恢复与DPI目标验证
- 阻塞：无
- 证据：run 43956468003: 52/52 checks, Program/fixed projector capture groups and normal close/restart passed; physical multi-monitor not tested.；v51树projector_placement.hpp、product_window.cpp与Qt回归/Windows移动保存重开断言；本机g++几何测试、product_window语法与44契约通过；历史Windows44050932022只含c689e1b不含此投影修改
- 最新记录：保留已提交窗口偏好子能力，完整任务仍开放；回到正在运行的Windows迁移/更新门禁处理，避免跨任务重叠修改脚本
- 最近更新：2026-11-17T17:08:54+08:00

## R3-001 · 回接设备控制 PTZ、快照与对讲

- 修改范围：`camera`, `native-host/src`
- 验收：实际产品入口可用；松键/断开/撤权及时停止；快照和对讲任务正确收尾
- 下一步：复用已有 camera 服务协议，不旁路 camera scope。
- 阻塞：无
- 证据：尚未提供
- 最新记录：协作基线登记；尚未执行本项。
- 最近更新：2026-11-16T13:35:31+08:00

## R3-002 · 回接输出、NVR、回放和证据

- 修改范围：`nvr`, `archive`, `recordings`, `native-host/src`
- 验收：单一媒体/输出所有者；计划/配额/掉盘/seek/导出可验；历史录像、权限和审计保留
- 下一步：目标机多卷/掉盘/配额、seek/导出 hash 和大文件回放。
- 阻塞：无
- 证据：run 43956468003: nvr-records-real-registry-camera-and-serves-authenticated-media; NVR config UI/storage entry; installed service default list.
- 最新记录：NVR 服务进入完整安装并由实际门禁验证注册表相机录制、鉴权 MP4、时间线与截屏/回放入口；多卷、磁盘故障和真实大文件导出仍开放。
- 最近更新：2026-11-17T06:08:15+08:00

## R3-003 · 回接事件、检测、go2rtc 与网站来源可选组件

- 修改范围：`events`, `analytics`, `go2rtc/online_source.py`, `native-host/src`
- 验收：按需进程与版本/摘要验证；事件/规则/通知实际接线；网站提取和媒体实播独立证明
- 下一步：真实网站/直播、检测 provider/叠层最终像素、MQTT/HA 通知与重启恢复。
- 阻塞：无
- 证据：v4.5公开qualification/footprint：web/models29462611 B、web/assets27159948 B；历史矩阵已识别ONNX模型29461455 B和ORT WASM25749873 B；非本轮完整v5测量或已实现按需分发；run 43956468003: events-persist-dedupe-and-route-to-durable-outbox; complete-online-source-extractors-and-node-runtime-self-test; go2rtc service running.
- 最新记录：events、go2rtc 与网站解析器已进入完整包；事件去重/outbox 和解析器自检通过；检测 provider 最终像素与真实站点实播仍待。
- 最近更新：2026-11-17T06:08:15+08:00

## R3-004 · 回接远端、离线同步、问题中心和诊断

- 修改范围：`v2`, `clients`, `web/src`, `native-host/src`
- 验收：远端输出 adapter 与权限一致；离线冲突不覆盖 Program；有界脱敏支持包可用
- 下一步：逐项关闭 REMOTE/OFFLINE/OPS，远端兼容不等于恢复 Android 发版。
- 阻塞：无
- 证据：尚未提供
- 最新记录：协作基线登记；尚未执行本项。
- 最近更新：2026-11-16T13:35:31+08:00

## R4-001 · 实现并验证旧完整产品数据迁移及回退

- 修改范围：`native-host/scripts`, `backup`, `cluster`
- 验收：账号/设备/场景/声音/录像完整保留；活跃 SQLite 一致性快照；失败恢复和幂等，默认不覆盖本人数据
- 下一步：在隔离 Windows 用户档案上执行真实旧→v5 迁移、回退和幂等复验。
- 阻塞：无
- 证据：test_migrate_legacy.py 2 PASS; release contains MIGRATE-LEGACY.cmd; native-product-nsis full data-retention gate; fullFeatureMigrationQualified still false.
- 最新记录：旧 WebOBS 4.x 与 v4.5 NativePreview 显式迁移代码、SQLite 一致性/工作区/拒绝覆盖单测通过；已接入安装快捷方式，但用户本人档案实际迁移尚未执行。
- 最近更新：2026-11-17T06:08:15+08:00

## R4-002 · 完善原生托盘、后台任务、更新与失败恢复

- 修改范围：`native-host/src`, `native-host/scripts`, `desktop/scripts`
- 验收：原生 updater 验摘要并用户确认安装；任务进行中更新和失败恢复；Unicode/非管理员/覆盖/卸载/崩溃实际 Windows 证据
- 下一步：目标机旧稳定→v5、断网/截断/失败恢复与后续版本 feed 验证。
- 阻塞：无
- 证据：run 43956468003: rc.1→rc.2 same-machine upgrade, fresh NSIS, normal close/restart/launcher crash; latest.yml byte-bound.
- 最新记录：原生更新器、SHA-512/size、确认安装、NSIS 覆盖升级、卸载保留和正常/崩溃收束已验证；稳定 feed 与旧稳定实机升级仍开放。
- 最近更新：2026-11-17T06:08:15+08:00

## R5-001 · 完成完整功能进程/安装成本与自动化长稳

- 修改范围：`native-host/qualification`, `native-host/tests`, `docs/performance-and-hardware.md`
- 验收：区分 setup、logical、allocated 和用户数据；统计所有产品所属进程及功能增量；合成媒体长稳/故障注入有同源码证据
- 下一步：目标机长稳、逐路解码/GPU/全进程和同条件 OBS 对照。
- 阻塞：无
- 证据：本聊天2026-11-16用户明确反馈；未提供本轮CPU/GPU/内存数值、流规格、OBS基线或逐路NVDEC证据，不据此关闭R5/R7或宣称≤OBS；run 43956468003 native-product-nsis footprint; no target CPU/GPU/long-run/OBS comparison.
- 最新记录：完整候选首启安装树实测 794551075 logical/806587720 allocation B、6972 files；尚未做目标机逐路硬解、两小时长稳和 OBS 同条件 A-B。
- 最近更新：2026-11-17T06:08:15+08:00

## R6-001 · 冻结完整 Release 候选与发布材料

- 修改范围：`.github/workflows`, `native-host/scripts`, `docs/release-flow.md`
- 验收：完整安装和功能范围闭合；依赖/源码/SBOM/许可证与二进制一致；双语说明及最终实机清单明确
- 下一步：集中目标机验收后用审查发布流程完成正式 v5.0。
- 阻塞：无
- 证据：https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v5.0.0-rc.1; run 43956468003; installer sha256 3d16014d...
- 最新记录：已冻结并发布 v5.0.0-rc.1 完整候选（prerelease，13 assets），包含安装器/更新元数据/校验和/验收摘要/来源清单/候选 SBOM/回执；目标机最终验收未完成，故 R6/R7 不关闭。
- 最近更新：2026-11-17T06:08:15+08:00

## R7-001 · 集中目标机真实五路、旧数据和 OBS 对照

- 修改范围：`docs/performance-and-hardware.md`, `docs/windows-native-feature-parity.md`
- 验收：真实五路/个人数据升级和至少两小时显示稳定性；逐路硬解/全进程/同条件 OBS A-B；缺陷修复后针对性复验及最终身份一致
- 下一步：准备目标机集中验收：安装候选、迁移本人旧数据、真实五路/多屏/音频/长稳及 OBS A-B。
- 阻塞：完整 v5 候选已发布，但目标机真实五路/逐路硬解、物理多屏/DPI、音频设备、两小时长稳和 OBS 同条件性能尚无设备证据。
- 证据：本轮用户v4.5正向反馈，无新的v5完整候选或定量报告；v5.0.0-rc.1 prerelease; 52/52 portable + 52/52 installed + 9/9 restore; no target-device evidence.
- 最新记录：集中验收候选已可通过 GitHub Release 下载；等待目标机与真实相机/旧档案。
- 最近更新：2026-11-17T06:08:15+08:00

## R7-002 · 按审查后的 v5.0 及后续完整版本流程完成稳定交付

- 修改范围：`docs/release-flow.md`, `docs/release-notes-v5.0.md`
- 验收：通过最终验收后执行版本化 dev→main 流程；重建时重验二进制/安装身份；稳定附件/feed 与已验收范围对应
- 下一步：继承已有分支和发布约定，不因本任务表出现而自动推送或发布。
- 阻塞：无
- 证据：尚未提供
- 最新记录：协作基线登记；尚未执行本项。
- 最近更新：2026-11-16T14:35:45+08:00

## HOLD-001 · Android、容器及扩展平台后续交付

- 修改范围：`android`, `docker`, `compose.yaml`
- 验收：保留既有资产/源码兼容；共享安全检查按相关改动运行；恢复交付范围需用户明确决定
- 下一步：保持暂停；不作为当前 Windows 预览发布阻塞项。
- 阻塞：既有用户决定暂停 Android/容器候选同步与发布；扩展原生平台按主要版本节点安排。
- 证据：尚未提供
- 最新记录：协作基线登记；尚未执行本项。
- 最近更新：2026-11-16T13:35:31+08:00

## V5-001 · 登记完整版本从 v5.0 开始并建立隔离开发入口

- 修改范围：`AGENTS.md`, `docs/coordination/DECISIONS.md`, `docs/coordination/state.json`, `docs/windows-desktop.md`, `docs/release-notes-v5.0.md`
- 验收：v4.5保留为历史预览，完整版本从v5.0开始；不扩大暂停平台范围，不提前开放完整稳定发布
- 下一步：R2-005/R1-002继续最终Windows验证，完整Studio等依既有任务推进
- 阻塞：无
- 证据：工作树 /home/czl/projects/monitor_wall_v5@codex/windows-v5-integration 基于 origin/dev 9fe0c1b；AGENTS.md、docs/windows-desktop.md、docs/release-notes-v5.0.md 与共享 DECISIONS.md 均注明 v5.0，未创建新候选或发布；使用agent-sync.py的locked/validate/atomic_write/render维护state与事件序列；五视图不独立手改；仍不授权未合格稳定发行
- 最新记录：v5.0决定、全局优先级与R7-002完整发行版本指向已同步；历史基线/事件保留
- 最近更新：2026-11-16T14:35:45+08:00

## R2-005 · 将原生快捷监看从固定五路扩展为有界可变路数

- 修改范围：`native-host/src/product_window.cpp`, `native-host/src/layout.hpp`, `native-host/CMakeLists.txt`, `native-host/tests/layout_test.cpp`, `native-host/tests/pixel-pattern.cjs`, `native-host/tests/product-ui.ps1`, `native-host/tests/product_scene_libobs_test.cpp`, `native-host/tests/product_windows.py`, `docs/windows-native-feature-parity.md`, `docs/qualification/windows-v5-quick-wall-2026-11-16.json`
- 验收：1至64路快捷布局，默认五路兼容已发布预览的持久选择；同源复用、授权前置、注销退休及Preview/Program分离保留；真实布局与产品验证区分本地和Windows结果
- 下一步：继续R1-001全入口执行审计，随后推进真实Studio/TAKE；完整编辑/嵌套/音轨仍开放
- 阻塞：无
- 证据：代码 /home/czl/projects/monitor_wall_v5；/tmp/webobs-v5-api-build.log、qt-syntax.log、libobs-graph.log、contracts.log、pixel-contracts.log；真实libobs为inert来源1→7→64→1，不证明真实解码/目标机；完整R2与R1审计未关闭；实际代码工作树 /home/czl/projects/monitor_wall_v5；branch codex/windows-v5-integration@d127283；https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/43815686047；https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/57；本机公开审计1168路径通过，无上游修改；工作树 /home/czl/projects/monitor_wall_v5@429155676834047d5be5b3fbc1b900abf660f831；PR57；最终Windows https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/43816563388；本机Qt/API8/44契约/24像素(2skip)/真实libobs/双模式实际HTTP与1168路径公开审计通过；本轮gh run view43816563388: Exercise actual integrated launcher...已成功，active Verify pre-authentication restore I/O；无failed steps；不是目标机/硬解/完整产品资格；run43816563388@4291556 success；entry-ui43、installed-ui43、restore9；内部模式没有预览专属默认目录检查，故不是44；NSIS publicationForbidden=true；docs/qualification/windows-v5-quick-wall-2026-11-16.json；run43816563388源码4291556；内部NSIS70147554 B、publicationForbidden=true；38f99b5相对4291556只含3个docs文件；工作树monitor_wall_v5；dev合并e8e60e2b0d27e6ab0ac1d070e7cfa5cfcb9a53a5；实际代码工作树 /home/czl/projects/monitor_wall_v5；runtime4291556 run43816563388 success 43/43/9；38f99b5仅3个docs文件；QA摘要 docs/qualification/windows-v5-quick-wall-2026-11-16.json；1/4/7为实际窗口，64为网格/真实libobs inert引用边界，非64真实解码或OBS性能达标
- 最新记录：可变路数快捷墙已实际接线并经同源码Windows全门禁验证，PR57全部检查通过后合入dev；仅关闭此子能力，不关闭完整R2
- 最近更新：2026-11-16T15:28:08+08:00

## R1-002 · 把管理目录权限收紧覆盖到所有原生宿主模式

- 修改范围：`core/src/control_server.cpp`, `native-host/tests/product_http_runtime.py`, `docs/release-notes-v5.0.md`
- 验收：预览与内部原生模式普通配置目录均需device.manage；普通viewer仍可通过原生API读取有权摄像机，不向其暴露完整配置目录；非原生旧HTTP兼容行为保持，真实HTTP双模式与Windows候选通过
- 下一步：R1-001仍需全入口编辑/恢复/输出执行栅栏审计，不以本修复替代整体验收
- 阻塞：无
- 证据：/tmp/webobs-v5-native-catalog-red.log旧core在期望403处失败；/tmp/webobs-v5-native-catalog-green.log新core内部/预览均通过；代码 /home/czl/projects/monitor_wall_v5/core/src/control_server.cpp 与 native-host/tests/product_http_runtime.py；/tmp/webobs-v5-native-catalog-green.log；run43816563388；source4291556；未新建公开Release或修改v4.5；Windows run43816563388@4291556，Build and stage integrated control/services与实际入口步骤成功；保留最终整轮边界；run43816563388 success；source4291556；原始回执hash在QA摘要；43/43/9仅当前范围，非完整融合/性能资格；runtime4291556；真实HTTP红→绿，预览/内部403及原生scoped目录可用，非原生camera/source-catalog200；Windows43816563388和PR57均success，dev=e8e60e2；内部5.0.0-dev.1安装器禁止发布，无v5.0完整Release
- 最新记录：原生配置目录权限已从预览特例推广到全部原生宿主；双模式实际HTTP、旧路径兼容和最终Windows安装整轮通过，PR57已合入dev
- 最近更新：2026-11-16T15:28:08+08:00

## HANDOFF-001 · 交接v5开发并记录用户v4.5实机反馈

- 修改范围：`docs/coordination/NEXT-AGENT-HANDOFF-2026-11-16.md`, `docs/coordination/DECISIONS.md`, `docs/windows-obs-parity-execution.md`
- 验收：交接含真实工作树/分支/源码、已完和待做、实际证据及下一认领命令；保留根checkout既有未提交改动，未占用开发任务，记录反馈但不冒称OBS量化达标
- 下一步：下一Agent读取交接文件和AGENTS，检查两个工作树，以新唯一ID认领R1-001继续完整v5开发；保留根目录既有未提交协作改动
- 阻塞：无
- 证据：本轮核对v5树干净、HEAD e8e60e2；PR57 merged；合并后CI43823811195 success；QA摘要确认4291556对应43/43/9；agent-sync工具5测试通过；用户最新反馈写入R5/R7/DECISIONS及执行记录；只交接未改产品代码/发行
- 最新记录：交接完成：先全文读取[NEXT-AGENT-HANDOFF-2026-11-16.md](NEXT-AGENT-HANDOFF-2026-11-16.md)；最新代码monitor_wall_v5@dev e8e60e2，账本仍在monitor_wall_czl；用新AgentID认领R1-001。用户v4.5可用/占用不错反馈已记录，完整版本从v5.0起；本会话没有开发任务占用。
- 最近更新：2026-11-16T15:51:37+08:00

## HERMES-001 · 接入 Hermes 并验证跨用户协作文件权限

- 修改范围：`scripts/agent-sync.py`, `tests/test_agent_sync.py`, `docs/coordination/PLAYBOOK.md`
- 验收：T3 Hermes default ACP 就绪，实际模型回复和文件工具验证通过；共享协作账本的原子替换保留访问模式，claude/czl 均可继续读写；接入和权限备份位置记录在本机安装说明
- 下一步：在 T3 模型选择器选 Hermes - default；新项目/工作树需要配置对应共享权限。跨用户协作继续使用现有统一台账和唯一 Agent ID。
- 阻塞：无
- 证据：T3 本机 provider cache: hermes-default ready；默认 custom:qwen3.8-flash-next-gyro-gyro-m；python3 -B tests/test_agent_sync.py：7/7 通过；隔离目录实际 claude/czl 接力写入与 check 通过；T3 hermes-default: installed=true/status=ready；默认 Qwen 模型已发现；本机 ~/.local/share/hermes-t3/verification.json：实际 ACP turn 返回；两次文件工具、allow_once 审批、随机标记读写匹配；python3 -B tests/test_agent_sync.py：7/7；隔离账本实际 claude→czl 认领/释放/再认领和双方 check 通过；本机接入/服务/权限备份说明：~/.local/share/hermes-t3/README.zh-CN.md；sudoers/租期未修改
- 最新记录：Hermes default 已接入 T3 并显示 ready，复用既有 default gateway/配置。实际 ACP 对话调用 read_file 与 write_file，单次编辑审批后写出的随机标记与输入一致；已保留本机验收记录。六个已登记 T3 项目具有协作 ACL；共享账本原子替换模式修复通过 7 项回归和真实跨用户接力。未修改 R1-001 负责人正在开发的产品代码。
- 最近更新：2026-11-16T20:08:59+08:00

## HANDOFF-002 · 核对最新开发并交接v5.0完整成品执行任务书 / hand off full v5.0 delivery

- 修改范围：`docs/coordination/V5-CURRENT-HANDOFF-2026-11-16.md`, `docs/coordination/V5-FULL-RELEASE-AGENT-TASKBOOK-2026-11-16.md`, `docs/coordination/NEXT-AGENT-HANDOFF-2026-11-16.md`, `docs/coordination/DECISIONS.md`
- 验收：核验实际工作树、PR58和CI最新状态，保留R1现负责人；交接提供成品关键路径、真实入口与安装验收、最终集中测试和发布边界
- 下一步：从最新两文件接手，核对原R1会话后按PLAYBOOK转交/认领；处理PR58失败job与实际审计，再依次交付W1原生工作台、W2业务、W3迁移更新、W4完整候选及最终集中验收/发布
- 阻塞：无
- 证据：本轮实际执行python3 -B tests/test_agent_sync.py：7/7；agent-sync check revision59/29任务/5视图同步；两个工作树git diff --check通过，v5树干净；4文档21个本地链接无缺失，Markdown代码围栏配对；GitHub复查PR58和CI状态未变；本轮只读产品/编写交接，未重跑产品媒体或安装测试；docs/coordination/V5-CURRENT-HANDOFF-2026-11-16.md；docs/coordination/V5-FULL-RELEASE-AGENT-TASKBOOK-2026-11-16.md；本轮实际GitHub/API源码查询、失败日志复核；7项协作工具回归、21本地链接、两树diff检查通过；未改产品代码/原负责人状态/发行附件
- 最新记录：交接交付完成。下一AI首先全文读 V5-CURRENT-HANDOFF-2026-11-16.md 与 V5-FULL-RELEASE-AGENT-TASKBOOK-2026-11-16.md；当前R1负责人保持不变，本会话不占用产品开发任务。用户已要求接续完整v5，按真实成品节点持续推进，中间无需反复确认或用户逐包测试。
- 最近更新：2026-11-16T20:32:32+08:00

## AUDIT-001 · 核查rc.1发布证据及完整候选缺口 / audit rc.1 release and integration gaps

- 修改范围：`docs/qualification/v5-rc1-independent-review-2026-11-17.md`
- 验收：核对公开资产/源码/Windows门禁，独立检查迁移与更新实现，区分未实现和仅待实机；不改产品/公开Release
- 下一步：开发者优先修迁移路径和更新完整性/版本比较，做真实payload升级与迁移回归；补音频/合成输出/远端离线等未接线及长稳后再交最终完整候选
- 阻塞：无
- 证据：docs/qualification/v5-rc1-independent-review-2026-11-17.md；11/13匿名下载资产size/hash对GitHub一致；52/52/9和35captures回执同8828532；本轮旧迁移/更新测试通过但独立负向反例复现；所有安装命令mock，没有执行EXE或触碰本人数据；docs/qualification/v5-rc1-independent-review-2026-11-17.md；本轮匿名完整包212117618B SHA256=3d16014dab7700e6bc4f73c5c0bfba5700382c78fb3f24041589b58a4e67016c，SHA512同feed；迁移真实路径漏拷、缓存15B替换放行至mock安装命令、rc.2/rc.10反序复现；agent-sync check和git diff --check通过；未改产品代码/发行/用户数据
- 最新记录：rc.1独立审查已完成，报告定位3项可复现缺陷及未闭合产品范围；仅关闭审查任务，不关闭R2–R7、性能或迁移验收。公开包与回执真实；建议继续修复/补功能后给用户最终完整候选，不把开发缺口转为实机待验。
- 最近更新：2026-11-17T16:06:12+08:00

## V51-001 · 登记v5.1完整修复与正式交付目标 / record v5.1 full delivery target

- 修改范围：`AGENTS.md`, `docs/coordination/DECISIONS.md`, `docs/release-notes-v5.1.md`
- 验收：记录用户最新版本和验证安排，保留rc.1/v4.5不可变与暂停平台；继续原任务范围，不把未接线或未测项当完成
- 下一步：认领FIX-001，先修迁移工作区/执行前摘要/预发布排序并增加能捕获原缺陷的回归
- 阻塞：无
- 证据：AGENTS/DECISIONS及v51树docs/release-notes-v5.1.md；新树codex/v51-hardening基于2258a37，旧三树未切换/重置；账本全局决定通过脚本锁/验证和原子生成写入
- 最新记录：已登记v5.1交付目标和用户主要验证安排，建立隔离新工作树；立即进入缺陷修复，不把版本变更当完整验收。
- 最近更新：2026-11-17T16:42:50+08:00

## FIX-001 · 修复已复现迁移与原生更新缺陷 / fix migration and updater regressions

- 修改范围：`native-host/scripts/migrate_legacy.py`, `native-host/scripts/native_updater.py`, `native-host/tests/test_migrate_legacy.py`, `native-host/tests/test_native_updater.py`, `docs/release-notes-v5.1.md`, `docs/windows-native-feature-parity.md`, `docs/windows-obs-parity-execution.md`
- 验收：真实OBS插件路径迁移并可回读，失败不留半成品；安装前重新验证缓存size/SHA512；版本比较拒绝回退；负向回归及现有场景通过，不冒称完整R4
- 下一步：V51-002增加v5.1精确候选构建、真实payload更新和安装后迁移回归，再继续完整功能
- 阻塞：无
- 证据：v51树native-host/scripts/migrate_legacy.py和native_updater.py，相关真实文件/SQLite/HTTP回归通过；尚未运行新Windows安装，安装执行器mock隔离；source cd33809；v51树migrate_legacy/native_updater及新增负向回归；python3 -B test_migrate_legacy.py、test_native_updater.py、test_build_contract.py 44/44、git diff --check通过；不修改历史Release或稳定feed
- 最新记录：已接线并提交首批审查缺陷修复，源码cd33809已推送codex/v51-hardening；本机迁移3组/HTTP缓存负向及44构建契约通过。仅关闭源码回归子任务，新的Windows安装与完整R4仍未关闭，接续管线实测。
- 最近更新：2026-11-17T16:49:18+08:00

## V51-002 · 接通v5.1构建与真实安装更新门禁 / wire v5.1 build and installed update gates

- 修改范围：`native-host/scripts`, `native-host/tests`, `native-host/src/product_window.cpp`, `desktop/scripts/build-obs-native.ps1`, `desktop/scripts/test-native-product-install.ps1`, `desktop/scripts/publish-native-candidate.ps1`, `.github/workflows/windows-obs-native-host.yaml`, `docs/release-notes-v5.1.md`, `docs/windows-native-feature-parity.md`, `docs/windows-obs-parity-execution.md`
- 验收：v5.1候选身份与内部/稳定区分；Windows新payload通过真正更新器校验/安装/启动，实际preview档案由新宿主登录恢复；回执绑定实际源码，不称全功能或性能合格
- 下一步：合并PR65到dev后继续R2-003多轨声音、R3-002合成录像/推流、R3-004远端/离线及R4完整迁移/生命周期；最终从新的完整源码重建并走v5.1正式发布流程。
- 阻塞：无
- 证据：source c689e1bab3c63bdd2b90046dacaf5c0fb4f106f7；run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44050932022；本机版本/元数据、独立payload/防改写、supervisor和6包测试、44构建契约通过；PR65公共CI与整轮Windows继续观察；PR65 source8e18590；native_updater/maintenance/cmd/restore实际接线；本机迁移、HTTP+缓存、独立维护工具隔离/清理及3项加密备份回归通过；Qt投影源码003a583已提交且只本机验证，新的Windows仍待结果；gh run view确认旧actual integrated launcher步骤conclusion=success；gh run cancel44050932022；新run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44055841340 @8e185901e1895c29ccd58438c927000c6d4fded7；不从取消run发布安装包；PR65 statusCheckRollup已核对10SUCCESS/1SKIPPED；最新完整Windows https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44057420866 @8e185901e1895c29ccd58438c927000c6d4fded7，当前queued；旧c689e1b portable步骤success仅为历史局部证据；本机7项协作测试/check/diff通过，v51树干净；失败日志定位test_native_updater.py:219 origin read_text()断言；source2f676e9仅2行测试修复，无运行时代码变化；本机test_native_updater.py通过；新Windowsrun待最新ID登记；https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44057825506；head2f676e93853c672dfa273320dbbb6db81adbe407；Windows Verify process accounting logic and actual Windows query APIs=success，Compile pinned OBS frontend and product plugin=running；本地迁移/更新维护、加密备份、Qt几何/语法和44契约通过；无正式Tag/Release/feed变更；codex/v51-hardening@5add246679c5ee22b6bf338e4601ffe81a5633fd；PR #65已推送；Windows run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44081218082 in_progress；本机 test_build_contract 44/44、test_product_package 6/6、test_upgrade_runtime 1、test_migrate_legacy 3、test_native_updater 2 PASS；投影工作区helper样例PASS；未把该run当已通过；run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44081218082；failurePhase=fixed-scene-projectors；lastCheckpoint=pixels-continuous-reordered-captured；projectorCount=1；首个工作区修复已使后续studio/README检查通过；未把本轮当通过；codex/v51-hardening@6834994bd80e040558ea9f3f308f3c2a645907c3；product_window语法检查通过；test_build_contract 44/44、complete supervisor、product package 6/6、upgrade runtime PASS；run44085990284 https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44085990284 in_progress；codex/v51-hardening@afc76537fcc78ec12059f3b3ffba456243db314d；run44089178485 in_progress；rc.4 run44085990284回执显示projectorPreferenceRoles=[fixed-1]、几何已保存；test_build_contract 44/44、Python编译与diff检查PASS；codex/v51-hardening@b1681d4402fea4901b8b6fb24877889a186d61eb；run44093199118 in_progress；rc.5回执projectorPlacement=968x689旧值、重开实际784x461；test_build_contract 44/44与Python编译PASS；codex/v51-hardening@4dc97e5693be7d2064d148d5e15f1db44716b062；rc.6 run44093199118实际UI 55项/安装态UI 55项通过，setup 212107604B；失败phase=same-machine-upgrade，备份restore子进程exit1；本地test_native_updater、encrypted_backup、product_package、release_policy PASS；codex/v51-hardening@57ea2cf9e38e80908f00c562d43a6ebb05abaca4；rc.7实际UI通过55项，安装态UI在projector-close ui-timeout；产品状态projectorCount=0；test_build_contract 44/44与Python编译PASS；codex/v51-hardening@ffb1d83a272d039a6268c68f459a2ed36a84e07f；rc.8 run44114909394 failurePhase=complete-business-management-entries、code=find-webobsManageAudio；test_build_contract 44/44 PASS；diagnostic run44141423769: installed native_updater restore stderr="backup paths must be absolute"; run44130563613 actual UI/installed UI pass, failurePhase=same-machine-upgrade; local test_native_updater now 3 PASS incl absolute backup root; source codex/v51-hardening@ea2b8b1；codex/v51-hardening@6aa8602；rc.11 run44143228832实际UI 55/55、安装态UI通过、restore 9/9、NSIS首装setup 212123898B；失败Assertion installed manifest rc.11 != rc.12；本地test_native_updater 3 PASS、build contracts 44/44；run44165531375 failurePhase=same-machine-upgrade-profile-fingerprint，updater/registeredVersion通过；本地web typecheck/build、dependency-security 7/7、desktop test 60/60、audit(ignore GHSA-fc5q-39xc-vjpf)、test_native_updater 3/3、test_build_contract 44/44、encrypted_backup 3/3、git diff --check通过；run44176217763 artifacts rc.14：native-product-updater passed=true；native-product-nsis sameMachineUpgradeQualified=true, registeredVersion=5.1.0-rc.15, profileFingerprint 30/30；upgraded-ui failurePhase=native-program-take lastCheckpoint=program-cleared-put；product_window Qt syntax、product_windows py_compile、build contracts 44/44、diff check通过；run44188738414: source20696af, entry-ui checks44 then failure normal-close, exit0, normalCloseAlivePids=2, state locked/media0; new source472f3fe, py_compile/diff check; run44194328169 identity；run https://github.com/LiaoYK001/Web-Camera-Monitor-Web-Camera-Monitor-Wall/actions/runs/44194328169 (actual URL https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44194328169); source472f3fe; setup 212162215 B sha256 12039948205f915de180eb0a84f74d0b51ef3fd737a30234851305dbe4242dbd; footprint 794579783 logical/806620488 allocation/6972 files; docs/qualification/windows-v51-update-gates-2026-11-18.json; docs/release-notes-v5.1.md; docs/windows-native-feature-parity.md; docs/windows-obs-parity-execution.md; public run44194330290 success; test_build_contract 44/44; agent-sync check/diff check通过
- 最新记录：Windows v5.1更新/迁移门禁已完成：run44194328169/source472f3fe/rc.16成功，便携/安装态/升级后各55项，恢复9/9，真实rc.16→rc.17更新器下载/缓存拒绝/维护运行时/加密备份/NSIS/恢复通过，profile指纹30/30一致；资格摘要和矩阵/执行记录已提交。
- 最近更新：2026-11-18T07:57:24+08:00

## HANDOFF-003 · 交接v5.1接续开发与正式交付 / hand off v5.1 completion

- 修改范围：`docs/coordination/V51-NEXT-AGENT-HANDOFF-2026-11-17.md`, `docs/coordination/DECISIONS.md`, `docs/coordination/V5-CURRENT-HANDOFF-2026-11-16.md`, `docs/coordination/V5-FULL-RELEASE-AGENT-TASKBOOK-2026-11-16.md`
- 验收：单文件含最新代码/PR/运行身份、已改/未做/风险、认领命令和v5.1完整发布任务；释放本会话V51-002便于下一Agent接手；不修改产品或发布
- 下一步：下一Agent先读新交接/AGENTS/账本，以新ID认领已释放V51-002，查询44057825506、修复并收束PR65；持续完成R2–R7并以v5.1完整Windows包交付用户主要验证，不重做旧预览
- 阻塞：无
- 证据：docs/coordination/V51-NEXT-AGENT-HANDOFF-2026-11-17.md；本轮7项协作测试通过，4文档31本地链接存在/围栏配对通过，root和v51两树diff检查通过，v51干净；PR65 OPEN@2f676e9、dev2258a37，Windows预检查/OBSQt/业务构建success、actual UI运行中；未改产品或发布
- 最新记录：交接完成：请全文读取V51-NEXT-AGENT-HANDOFF-2026-11-17.md。已释放V51-002给新唯一Agent ID，保留最新v51代码/PR65和root未提交协作文件；单文件含已做/未做、具体接线位置、测试与失败历史、任务顺序和v5.1正式交付条件。最后复查44057825506已进入实际产品UI，尚无整轮结论。
- 最近更新：2026-11-17T18:09:15+08:00

## HANDOFF-004 · 编写 DeepSeek 的 v5.1 成品执行指南 / write the v5.1 completion guide

- 修改范围：`docs/coordination/V51-DEEPSEEK-COMPLETION-GUIDE-2026-11-18.md`
- 验收：核对最新源码、PR 和 Windows 失败回执，给出可执行定位、分支顺序、完整功能与发布验收，不接管进行中开发
- 下一步：由用户转发单文件给 DeepSeek，原负责人优先修 rc.23 来源断言并跑同源码 Windows 证据，再按指南完成 #67、剩余业务和正式 v5.1。
- 阻塞：无
- 证据：rc.23 @44ce627 报告 Program=applied、-20.87 dBFS、sourceId=fixture-alt.fixture-alt-source。离线重算显示原短 ID 导致等待为假，完整 ID 条件为真。#67 AAC/Opus encoder 创建均选总线索引0，具体验证建议在指南，未声称已复现输出静音。指南链接与围栏核对、7项协作测试及三树 diff 检查均通过。
- 最新记录：DeepSeek 的最新执行入口为 docs/coordination/V51-DEEPSEEK-COMPLETION-GUIDE-2026-11-18.md。优先修 #66 的 rc.23 运行态来源 ID 断言，再验证双轨与 Program 产物；#67 rc.24 产品 UI 已失败，独立恢复仍在运行。继续任务以指南和当前账本的证据为准，R2-003 原 owner 保留。
- 最近更新：2026-11-18T11:06:44+08:00

## V51-004 · 补齐 v5.1 稳定发布身份与 Tag／版本映射 / add v5.1 stable release identity and tag mapping

- 修改范围：`native-host/scripts/release_policy.py`, `native-host/tests/test_stable_release_identity.py`, `docs/release-flow.md`, `docs/versioning-and-branches.md`
- 验收：release_policy 能区分 rc 候选与稳定成品身份，稳定身份只有在升级与迁移合格并有回执引用时成立；tag_for_version 按仓库规则映射（5.1.0→v5.1、5.1.2→v5.1.2、5.1.0-rc.N→v5.1.0-rc.N、dev 不可发布），本机测试通过并更新发布文档；不创建 Tag/Release/feed 变更。
- 下一步：本机实现策略与映射测试，随后在输出分支把 publish_candidate.py 接到共享映射并强制 --final 校验已审查 main 提交
- 阻塞：无
- 证据：PR #68; .worktrees/v51-release@f176fba; python3 -B native-host/tests/test_stable_release_identity.py PASS；PR #68; test_stable_release_identity PASS; test_build_contract 44/44 in .worktrees/v51-release; docs/release-flow.md §4.1 与 versioning Tag 映射已更新
- 最新记录：稳定身份与 Tag 映射已实现并本机验证，提交 codex/v51-release-identity@f176fba，PR #68 待合并到 dev；合并前 dev 仍不含该实现，后续接线与真实发行分别由 V51-005/V51-006 跟踪。
- 最近更新：2026-11-18T12:37:17+08:00

## V51-005 · 候选发布脚本改用统一 Tag 映射与 main 祖先校验 / use shared Tag mapping and main ancestry check in candidate publisher

- 修改范围：`native-host/scripts/publish_candidate.py`, `native-host/tests/test_candidate_publish.py`, `native-host/scripts/release_policy.py`, `native-host/scripts/stage.py`, `native-host/scripts/update_manifest.py`, `native-host/tests/test_stable_packaging.py`, `native-host/tests/test_update_manifest.py`
- 验收：候选与正式版 Tag 一律来自 release_policy.tag_for_version；--final 必须提供已登记验收并从已审查 main 可达的提交，否则拒绝；不覆盖已存在 Tag/Release；本机测试覆盖正反对照，不发生真实网络调用。
- 下一步：#67 合入 dev 后 rebase 到 dev（publish_candidate.py 为 add/add，保留 #69 的超集实现），再复跑发布链测试；发布链先验证到待发布状态，不自动发布
- 阻塞：无
- 证据：分支 codex/v51-publish-chain 基于 codex/v51-release-identity@f176fba；PR #69 (draft); .worktrees/v51-publish@6301ae7; test_candidate_publish.py PASS; test_stable_release_identity/test_complete_release_policy/test_preview_release PASS; test_build_contract 43/44（本树未初始化 obs 子模块）；本机 PASS：test_stable_packaging/test_candidate_publish/test_update_manifest/test_stable_release_identity/test_complete_release_policy/test_preview_release；test_build_contract 43/44（本树未初始化 obs 子模块）；PR #69 head a0a6ae6; 本机 release-chain 测试 6 个 PASS；test_build_contract 43/44（本树未初始化 obs 子模块）；https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44240683072；.worktrees/v51-publish@99f8f30；本机 test_candidate_publish/test_stable_packaging PASS；.worktrees/v51-publish@dc6d1b4；native-host/tests/test_build_contract.py 44 tests OK；test_candidate_publish/test_stable_packaging/test_update_manifest/test_stable_release_identity PASS；PR #69 全部 checks SUCCESS（含 windows-native-control-contracts、windows-update-contracts、offline staging）；native-host/tests/test_candidate_publish、test_stable_packaging、test_update_manifest、test_stable_release_identity、test_build_contract(44)、test_complete_release_policy 全 PASS；/tmp/v51chain 场景 A-H、F1/F2 实际输出；同一 /tmp/v51chain 场景 A-H、F1/F2 的实际命令输出；cmake -S native-host/tests/control-auth + ctest：18/18 通过（Linux, Ninja, Release）；cmake -S native-host -DWEBOBS_NATIVE_BUILD_TESTS=ON + ctest：8/8 通过；固定 OBS 32.1.2 构建 libobs（98/98）并导出 SDK，native-host/tests/real-loader ctest 1/1 通过（本机无 Xvfb 也能跑，标签 no-gpu/no-media）；本机 release 测试全 PASS：test_candidate_publish、test_stable_packaging、test_update_manifest、test_stable_release_identity、test_complete_release_policy、test_preview_release；test_build_contract 44 OK；control-auth CTest 18/18；native-host graph CTest 8/8；固定 OBS 32.1.2 libobs 构建 98/98 + real-loader CTest 1/1；codex/v51-publish-chain head 0b0c7cc；test_candidate_publish/test_stable_packaging/test_update_manifest 本机全部 PASS（Tag v5.1 ↔ 版本 5.1.0 映射由共享策略给出）；native-host/tests/test_candidate_publish.py PASS；test_stable_packaging.py PASS（v5.1↔5.1.0 与 rc Tag 映射）；gh pr 69 head=codex/v51-publish-chain@21b0d00；#69 head 21b0d00 已含 dev tip 4b4e512（#68 已合并）且 origin/dev 为其祖先；OBS 子模块固定 fb4d98bf(32.1.2)、go2rtc b5948cfb(v1.9.14) 已初始化；补跑 native-host/tests/test_build_contract.py 44 OK、test_complete_release_policy.py PASS、test_stable_release_identity.py PASS、test_preview_release.py 4 OK、test_component_size_report.py PASS、test_compare_runtime_sizes.py OK、tests/test-immutable-release-assets.sh PASS、test_candidate_publish.py/test_stable_packaging.py/test_update_manifest.py/test_release_identity.py(8, skip4) 全绿；python3 native-host/tests/test_candidate_publish.py PASS；test_stable_packaging.py PASS(5.1.0→v5.1 / rc 候选独立)；test_update_manifest.py PASS；tests/test_release_identity.py 8 OK(4 skip)
- 最新记录：#69 分支本地复跑发布链：候选 Tag 取自共享策略、稳定发布需验收 JSON 与 main 祖先、pending/verify-only 不写任何内容；安装包与 latest.yml 大小/SHA-512 一致。待 #67 合入 dev 后 rebase（publish_candidate.py add/add，保留 #69 超集）。
- 最近更新：2026-11-18T23:21:25+08:00

## V51-006 · 接通稳定打包身份与验收文件单一契约 / wire stable packaging identity with one acceptance-file contract

- 修改范围：`native-host/scripts/stage.py`, `native-host/scripts/update_manifest.py`, `native-host/scripts/release_policy.py`, `native-host/tests/test_stable_packaging.py`, `native-host/tests/test_update_manifest.py`
- 验收：stage --stable 与 update_manifest 稳定版本都要求仓库外验收 JSON（四项验收为 true 且有界回执位置），Tag 一律来自 tag_for_version；候选路径行为不变；本机正反对照测试通过。
- 下一步：合入 #67/#68 后 rebase 本分支并转正式审查；真实 latest.yml 上传与集中验收回执仍待执行
- 阻塞：无
- 证据：尚未提供
- 最新记录：正式打包链缺稳定模式：stage.py 只接受 dev/preview/candidate，update_manifest.py 只接受 rc 版本，二者都没有验收门槛。
- 最近更新：2026-11-18T12:36:57+08:00

## V51-007 · 加固双目录加密备份的中间故障一致性与安全重试 / harden dual-directory backup swap consistency and safe retry

- 修改范围：`backup/encrypted_backup.py`, `tests/test_encrypted_backup.py`, `native-host/scripts/native_updater.py`, `native-host/tests/test_native_updater.py`, `native-host/scripts/product_supervisor.py`, `native-host/tests/test_complete_supervisor.py`, `native-host/tests/backup_restore_windows.py`
- 验收：两目录交换的崩溃/失败后要么完全旧状态要么完全新状态；中断日志可被下次 restore 自动收敛或明确拒绝；失败不残留 activated 目录；native 存档必须成对恢复；config-only 旧存档仍可用；本机 unittest 覆盖中间失败与崩溃恢复。
- 下一步：#67 合入 dev 后把 #70 base 改为 dev 并派发带 backup_restore_windows 门禁的 Windows 运行。
- 阻塞：无
- 证据：分支 codex/v51-r4-backup-consistency 基于 codex/v51-r3-output@ae4fce7；本机 tests/test_encrypted_backup.py 10 tests OK（libsodium 可用）；native-host/tests/test_native_updater.py 与 test_migrate_legacy.py PASS；本机 tests/test_encrypted_backup.py 10 OK；native-host/tests/test_native_updater.py PASS（含新增错误码映射断言）；PR #70 checks 进行中；python3 -B native-host/tests/test_complete_supervisor.py PASS（含中断交换收敛契约）；python3 -B tests/test_encrypted_backup.py 10/10；python3 -B native-host/tests/test_native_updater.py 3 项 PASS；本任务书 Windows 门禁待 CI 回执；.worktrees/v51-backup@7a7d64d；native-host/tests/test_complete_supervisor.py PASS；tests/test_encrypted_backup.py 10/10；native-host/tests/test_native_updater.py 3 PASS；PR #70 checks 将随 force-push 重跑；.worktrees/v51-backup@4664251；test_complete_supervisor PASS、test_encrypted_backup 10/10、test_native_updater 3 PASS；codex/v51-r4-backup-consistency@d0b9506：prepare() 顺序为独占锁 → protect → recover_interrupted_restore() → 目录创建/ini；Linux 侧 test_complete_supervisor.py 中断交换契约 PASS；Windows 安装态门禁（两次目录交换之间终止恢复进程 → 从已安装入口再启动 → 成对恢复/可重试/仅含 config 的旧归档保留原生档案）尚未有 CI 回执，不写成通过；本机 python3 -B tests/test_encrypted_backup.py 10 OK；native-host/tests/test_complete_supervisor.py PASS；test_build_contract.py 44 OK（本工作树已初始化 obs/obs-studio 子模块）；backup_restore_windows.py ast 语法校验通过（需 Windows 已安装运行时才能执行）；.worktrees/v51-combined 试合并后 test_complete_supervisor.py PASS（含 'converged the interrupted restore as completed'）、tests/test_encrypted_backup.py 10 OK、native-host/tests/test_native_updater.py 4 PASS；rebase 后 PR #70 head 4d60479（base #67 535a9af），native-host/tests/backup_restore_windows.py 由 workflow 步骤执行，证据待 rc.41 run 44291812392；git rebase a4d2512 clean；codex/v51-r4-backup-consistency=77958c3；gh pr 70 base=codex/v51-r3-output；PR#70 rebase 到新 #67 head（770b0e1，4 个自有提交无冲突）；tests/test_encrypted_backup.py 10 OK；native-host/tests/test_complete_supervisor.py PASS（含 'converged the interrupted restore as completed' 与二次 prepare 不被中断日志拒绝、无 run/restore-recovery.json）；复核 product_supervisor.prepare() 顺序：独占锁+protect 之后、创建 config/native-profile 目录与读取 user.ini 之前调用 recover_interrupted_restore()；commit be25901 on codex/v51-r4-backup-consistency; python3 tests/test_encrypted_backup.py 12 OK; same file against HEAD~1 service = 2 errors (falsifiable); test_complete_supervisor/test_native_updater/test_build_contract OK; run 44349201714 in_progress；307910f/2560a52/4a487d1 pushed; suites re-run green；#70 head 9d00b7f 已 rebase 到 #67 2004cf3；本机 test_complete_supervisor.py PASS。
- 最新记录：收窄 V51-007 范围：#70 的恢复门禁与其安装脚本/工作流接线均已提交（03f877c、9d00b7f），本任务剩余工作只在备份/恢复模块；把 desktop/scripts/test-native-product-install.ps1、.github/workflows/windows-obs-native-host.yaml 与 docs/windows-native-feature-parity.md 三条路径交还给协调，由 V51-014 在同一 Agent 内做旧数据导入接线，避免同一文件两个进行中声明。
- 最近更新：2026-11-19T02:05:57+08:00

## V51-008 · 把 Program 合成输出验收落到用户实际收到的产物 / accept Program output from the delivered recording and stream

- 修改范围：`native-host/src/product_output.cpp`, `native-host/src/product_window.cpp`, `native-host/src/product_scene.hpp`, `native-host/tests/product_windows.py`, `native-host/tests/pixel_windows.py`
- 验收：安装后应用里两路不同频率音调在录制文件与回环 WHIP 流中可解码：选中总线有预期音调、未选总线无串音、视频帧持续推进；逐轨静音/增益/偏移生效并如实区分配置到达与声学实测；录像目录失败与 WHIP 断线给出有界错误并回收编码器、服务与 MediaMTX；纯 RTSP 监看时不启动 Program 输出子进程；回执绑定源码 SHA 与安装包。
- 下一步：rc.52 结果决定下一步：若停滞输入名与逐路包数证明回环仍流动而 Program 专用输入零帧，则需在宿主做有界媒体重开；否则按 #67→#70→#71→#74 顺序合并并复跑 rc.53。
- 阻塞：无
- 证据：PR #67 head de8eebe（base dev）；rc.26 失败原因 MSVC C2664（QString→const char*）已用具名 QByteArray 修复；rc.28 失败原因 product_output.cpp(412) C2664（三目临时量绑到 QString&）已修复；https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44255084712；head 32e8d18；rc.30 run https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44255867749；本机 /tmp/tonecheck 双轨与单轨文件解码对照；rc.32 run 44266163975 failurePhase=program-recording-default-bus；此前 program-recording-decodes-both-fixture-pitches 通过（below600=1380.5/above660=908.8, mask=2）；本机 Qt6 + 固定 libobs 32.1.2 SDK + 固定 obs-frontend-api.h：product_window/product_output/product_scene/product_media -fsyntax-only 全部 exit=0；run 44271844168 = 5.1.0-rc.33 @ 0b6edc2 in_progress（product_mode/complete）；codex/v51-r3-output@a16f1f9 = run 44275460558 (rc.34)；@867c11b = run 44276526382 (rc.35)；Qt6 + libobs 32.1.2 SDK -fsyntax-only product_window.cpp exit=0；test_build_contract.py 44 OK；rc.33 失败断言 program-recording-default-bus 已由 a16f1f9（读 GET /api/v1/studio/runtime 回执）与 867c11b（瞬时 apply 有限重试 4 次）覆盖；两个运行均为 product_mode/complete；rc.34 run 44275460558 failurePhase=program-recording-default-bus, failureDetail=KeyError: 'programDefaultBusApplyAttempt'（lastCheckpoint=program-recording-audio-decoded，说明双音轨录像解码已通过）；修复提交 1be9c2f 已推送，rc.36 run 44280347568 在其上派发；run 44280347568; branch codex/v51-docs@f967634; commit 296f2bc；run 44280347568 failed; commit c250c85; runs 44285491534/44285510872；535a9af（PR #67）新增 lastLock/lockCode/renewTransient 分类，门禁在像素采集前直接报告撤销类别；Windows rc.40 run 44291675017 已派发在 codex/v51-r3-output 验证；gh run 44296843744 回执 native-product-entry-ui.json：failurePhase=program-recording-default-bus、programRecordingDefaultBus={below600Hz:0,above660Hz:0,audioTrackMask:1}、obsDiagnosticLines 显示 12:00:14.215 开始写文件、12:00:17.321 MP: Failed to open media、12:00:19.594 Reconnected；revert a4d2512（videoInputs.serial 帧计数门槛在 Windows 上 30s 全部走平而像素阶段本身通过，rc.44 因此误判停滞；像素内容仍是连续性证据）b447c48；23886e4 首次录像与 WHIP 开播前也调用 wait_program_mix_audible；python3 -B 语法 AST OK；rc.46 run 44308229704 @23886e4 product_mode=true complete=true 已派发，旧 head 的 44307720185 已取消以保证被测头与合并头一致；rc.46(23886e4,run 44308229704)两个 Program 像素阶段首次通过、两次录像首次解出双音调（programRecordingBandRms 1387.9/912.4 mask2；programRecordingDefaultBus 1381.6/910.1 mask1；programMixLeadIn 47ms/7328ms/15ms 已披露）；随后停在 program-streaming：programOutput streaming=false、mediaMtxRunning=false、streamPublishUrl 与 streamError 同时为空。定位为私有中继把 WHIP/WebRTC 写死 8889（产品分发网关 MediaMTX 也绑 8889，且 Windows 预留动态端口段可使固定端口在无人监听时不可绑定），拒绝只回给按钮文案，可观察状态看起来像空闲且无失败；rc.46(5dfcde8,run 44314586162)失败在 program-after-take：Frozen final pixels on slot 5（8 个样本槽位5计数恒为1，temporalProgress=false）；诊断显示 5 个推流全 alive、5 条 RTSP 路径全部 flowing、stalledPaths 为空、宿主对 6 个输入全部 stalledMs=0、wallItems=5/programItems=2、fixture-5 槽位 uuid serial=1037 而同批其他输入 1140-1148。同一 head 的上一次运行(23886e4)同一阶段通过（slot5 计数 5,5,16,16,16,27,27,1），因此这是间歇性且当时无法判定成因；rc.46 artifact receipt(run 44323126258): lastCheckpoint=pixels-program-after-take-captured, progressError=Frozen final pixels on slot 2, inputSerialDelta 6/6 advanced, stalledMsAfterCapture 0, publishers alive, stalledPaths empty；rc.48 receipt artifact(sha 9a694ce,version 5.1.0-rc.46): lastCheckpoint=pixels-program-before-take-observed, programPixelInputWait=null；rc.47(447dbba) 同阶段同症状；重基后本机 test_build_contract/test_product_lan/test_encrypted_backup/test_complete_supervisor/test_native_updater/test_compare_runtime_sizes/test_complete_release_policy 全部 OK；新 run 44339344891 @4f38150 product_mode+complete+measure_obs_baseline+upgrade_previous, soak_minutes=0；run 44339344891 receipt native-product-entry-ui.json; commit a92d11b; run 44349201714；commit 4adff47 (PR #67); receipt /tmp/rc51.NjL1/native-product-entry-ui.json lastCheckpoint pixels-program-before-take-observed programPixelInputWait waitedMs 30077 windows 12 countedInputs 5；python3 -m py_compile native-host/tests/product_windows.py；native-host/tests/test_build_contract.py 45 OK；native-host/tests/test_complete_supervisor.py PASS；分支链已 rebase 并强推：#67 39c43fd → #70 84c9302 → #71 89ec20a → #74 b03008d → #75 c19bcda；见上一条 revision 216 日志；python3 -m py_compile native-host/tests/product_windows.py；native-host/tests/test_build_contract.py 45 OK；native-host/tests/test_complete_supervisor.py PASS；run 44356064395 receipts /tmp/rc52.Vf3r；本地 MediaMTX 1.18.2 验证：活路径 oldestPts 3600→14791 flowing=true，杀发布进程后 packets=[0,0] flowing=false；py_compile 通过；native-host/tests/test_build_contract.py 45 OK；run 44364213218 编译日志 11_Compile…txt 第 2914/2918 行 C2039；本机 python3 -m py_compile 通过；rc.54 run 44366334192 已取消（含不可靠的 pts 规则）；栈头 8b09fa3/7169e21/985226a/5b8a9ac/f78e76e/bc7dc97。
- 最新记录：rc.53（run 44364213218）未到达 UI 门禁：MSVC C2039 指出投影聚合循环把 std::unique_ptr<ProjectorView> 当作值使用（view.graph）。修复为 view->graph（提交 a33b267）。同时撤销我上一版把回环 flow 改为“最旧 pts 前进”的规则（提交 8b09fa3）：fixture 用 -re -stream_loop -1 -c copy，循环处时间戳会回绕，且 MediaMTX 会向新读者吐出环形缓冲，健康路径同样可能给出不变或负的时间戳；若据此重启健康的发布进程，产品会重连并重新出帧，可能掩盖真实解码停滞。现在只有“两次新读取都为空”才算发布方故障（本机 MediaMTX 1.18.2 实验证实杀进程后 [0,0]），包数与最新时间戳仅作证据。派发 rc.55（run 44366851677，soak 分支 5b8a9ac）。
- 最近更新：2026-11-19T02:11:41+08:00

## COORD-008 · 记录 CI 下载临时目录约定 / document temporary directories for CI downloads

- 修改范围：`AGENTS.md`
- 验收：AGENTS.md 指定每次 CI 下载使用 mktemp -d 和带引号的下载路径，不清空旧目录或改变 Codex 审批配置
- 下一步：后续 CI 下载与重试各自新建空目录
- 阻塞：无
- 证据：AGENTS.md:42；Bash 使用 gh 替身验证两次执行得到不同空目录，带空格的产物名和目录值保持为独立参数；git diff --check 通过
- 最新记录：已在 AGENTS.md 写入中英双语 CI 下载目录规则和 Bash 示例
- 最近更新：2026-11-18T15:41:30+08:00

## V51-009 · 接通原生产品真实 LAN/Web HTTPS 入口 / wire the real LAN HTTPS entry into the native product

- 修改范围：`native-host/scripts`, `native-host/tests`
- 验收：supervisor 读取持久化 LAN 开关、私有 IPv4 与端口，生成来源允许列表与 Caddy 配置并作为受管子进程运行；状态回执给出 https URL、证书路径与仅展示的防火墙命令；Linux 单元校验配置/来源/JSON，Windows 安装态验证真实局域网访问
- 下一步：#67 合入后 rebase 到 dev 并补原生窗口开关；随后随完整候选派发一次带该门禁的 Windows 运行
- 阻塞：无
- 证据：codex/v51-r3-004-lan@13bc640 已推送；native-host/tests/test_product_lan.py 24 项通过；test_build_contract.py 44 项通过（已在该工作树初始化 obs/obs-studio 与 go2rtc/go2rtc 子模块）；test_complete_supervisor.py PASS；git diff --check 通过；codex/v51-r3-004-lan@97b4efe 已推送；test_product_lan 24 PASS、test_product_package OK、test_build_contract 44 OK、test_complete_supervisor PASS、test_native_updater/test_migrate_legacy PASS
- 最新记录：新增已安装态局域网入口门禁 lan_entry_windows.py 并接入 NSIS 完整候选验收与内部回执上传：已验证 TLS 健康检查、外来 Origin 拒绝、LAN 与回环两客户端独立会话/退出、禁用后重启不再监听、退出无残留进程。本机全部相关测试再次通过。
- 最近更新：2026-11-18T16:02:14+08:00

## V51-010 · 修已安装 LAN 门禁的首账号流程与无私网地址诚实降级 / fix installed LAN gate first-account flow and honest no-private-address degradation

- 修改范围：`native-host/tests/lan_entry_windows.py`
- 验收：门禁按真实产品流程先经回环 /api/v1/auth/setup 创建首账号（201）并证明重复注册 409，之后 LAN 与回环用同一账号建立独立会话；无私有 IPv4 的运行器记录 lanHttpsQualified=false + skipReason，且仍证明不启动监听、无 URL、本机消费端可用；安装脚本复制回执真实值而非写死 true；不把未实测的第二设备/交换机/Caddy 目标机安装写成通过
- 下一步：随完整候选（含 #71）派发带 native-product-lan.json 的 Windows 运行；真实第二台设备验收仍待用户目标机
- 阻塞：无
- 证据：python3 -B native-host/tests/test_product_lan.py 24 OK；test_build_contract.py 44 OK；lan_entry_windows.py 本机仅 ast 语法校验（需 Windows 已安装运行时）；PR #71 描述已更新；desktop/scripts/test-native-product-install.ps1 改为 report.lanEntryQualified/lanEntrySkipReason 取自回执真实值（该文件在 V51-007 声明范围内，一并在此记录）；test_product_lan.py 24 OK（含新的 busy-port 用例断言本机回环 Origin 保持、不写 Caddy 文档、failure_reason 仍为空）；test_complete_supervisor.py PASS；02b3ff2；容器内 Qt 6.11 下 native-product-lan-switch-test PASS；test_product_lan.py 24 项 OK；gh run 44300526460 conclusion=success；podman v51qt 容器内 Qt6.11 offscreen 运行 product_lan_switch_test 通过；g++ -fsyntax-only -DWEBOBS_NATIVE_PRODUCT_MODE product_window.cpp 无错误；PR#71 rebase 至 3161e9a（11 个自有提交）；python3 -B native-host/tests/test_product_lan.py 24 OK；rc.47 run 44307757343 在旧 head fabec5d 上仍在跑（同一 product_mode+complete 门禁），最终 dev 候选会再次覆盖
- 最新记录：rebase 时误用 --onto <upstream>=自身导致分支短暂指向父 head，已用 77958c3..15b1fd1 的 11 个提交恢复完整历史
- 最近更新：2026-11-18T20:54:19+08:00

## V51-011 · 实现安装态长稳门禁并接入 soak_minutes / implement the installed soak gate behind soak_minutes

- 修改范围：`native-host/tests,desktop/scripts`
- 验收：已安装产品在五路监看持续期间每分钟重新询问逐路停滞检测；进程树 CPU/私有内存/句柄/子进程集合有同源码回执；停滞、进程增减、内存或句柄增长超限即失败
- 下一步：等 #67 合入 dev 后把 f0eb858 迁到 codex/v51-r5-soak 并转 dev 开 PR，随后随完整候选派发 soak_minutes=120 的运行
- 阻塞：无
- 证据：试合并工作树 .worktrees/v51-combined 提交 f0eb858：py_compile 通过、test_build_contract.py 44 OK；codex/v51-r5-soak head f741497（3 个提交 rebase 无冲突）；native-host/tests 全部本机可跑项通过，仅两个需要 --probe 的 Windows 探针脚本按要求跳过
- 最新记录：#74 长稳分支已同步到 #67 的 535a9af 并推送；R5-001 认领被依赖未完成阻挡，本轮先在自有任务记录进度
- 最近更新：2026-11-18T19:17:39+08:00

## V51-012 · 编写 v5.1 候选发布说明并更新功能矩阵证据 / write the v5.1 candidate release notes and update the parity matrix

- 修改范围：`docs/release-notes-v5.1.md、docs/windows-native-feature-parity.md、docs/windows-component-size-split.md 的证据与缺口陈述 / release notes, parity matrix and size-split evidence statements`
- 验收：发布说明绑定实际候选版本、源码 SHA、安装器字节与摘要；矩阵按实际合入更新 OUTPUT/REMOTE/AUDIO/BACKUP/OPS 行，并把未接线与未实测项写具体缺口 / notes bind the real candidate identity and matrix rows state concrete gaps
- 下一步：候选 run 结束后填入实际摘要并开 docs PR / fill real receipts after the candidate run and open the docs PR
- 阻塞：无
- 证据：docs/release-notes-v5.1.md 候选身份表仍标记待绑定，绑定值将在最终候选 run 与安装包校验后写入
- 最新记录：#72 组件体积拆分已合入 dev（tip 4b4e512），发布说明与矩阵将引用同一次候选运行的 native-product-size-split.json；#73 文档分支已 rebase 到新 dev tip 以免显示为删除 #72 文件
- 最近更新：2026-11-18T19:17:40+08:00

## V51-013 · 用安装态门禁实跑 ONVIF 设备操作与权限拒绝 / exercise ONVIF device operations in the installed gate

- 修改范围：`tests/onvif_device_emulator.py`, `tests/test_camera_registry.py`
- 验收：安装后的 Windows 产品通过自身鉴权 API 完成 ONVIF probe/创建/sync/预置位/云台（设备侧 Timeout 与自动 Stop 到达设备）/抓拍，scoped viewer 的云台与抓拍请求 403 且设备侧不增长动作与字节读取；合成 SOAP 设备不得写成真机验收。
- 下一步：rc.52 绿并合并 #67/#70/#71/#74 进 dev 后，用一次带 #75 的完整候选运行验证设备操作阶段，再双语合并 #75。
- 阻塞：无
- 证据：PR #75 (codex/v51-r3-005-devices 35134da, base codex/v51-r5-soak); python3 tests/test_camera_registry.py 58 OK; smoke run of probe/sync/presets/ptz/autostop/snapshot green locally；python3 tests/test_camera_registry.py 58 OK；合成设备冒烟：三个 profile(含 snapshot)、sync、presets [preset-1]、moved state accepted/autoStopMs 350/deviceTimeoutMs 350、ptz_moves PT0.350S、自动停止到达设备、preset-created、goto accepted、快照 image/jpeg；Windows 安装态证据待后续 rc 运行；合成 SOAP 设备不等于真机验收；PR #75 head c19bcda
- 最新记录：协调后调整声明范围：native-host/tests/product_windows.py 的门禁改动归同一 Agent 的 V51-008 持有，本任务声明合成设备与相机注册表测试文件；实现同在一个 PR。
- 最近更新：2026-11-19T01:23:04+08:00

## V51-014 · 在已安装完整产品上验收旧数据导入入口与保留 / qualify the shipped old-data import path in the installed product

- 修改范围：`native-host/tests/legacy_import_windows.py`, `docs/native-legacy-import.md`, `desktop/scripts/test-native-product-install.ps1`, `.github/workflows/windows-obs-native-host.yaml`
- 验收：已安装入口先建立旧账号/设备/事件，再用包内 migrate_legacy.py 导入到新档案；导入后旧账号可登录、首次建档关闭、设备与事件保留、DPAPI 备份密钥可解密、旧会话失效；源目录逐文件哈希不变、重复导入被拒绝、结束后无残留进程；回执区分配置导入合格与 fullFeatureMigrationQualified 仍为 false，不夸大
- 下一步：本机语法与 Linux 契约复跑后，随下一次完整候选在 Windows 安装态产出 native-product-legacy-import.json；用户本人旧档案迁移留待目标机。
- 阻塞：无
- 证据：test_migrate_legacy.py 本地 PASS；安装包文件清单含 MIGRATE-LEGACY.cmd；尚无安装态导入回执。；基线 codex/v51-r3-005-devices @ 427cde6；rc.53 run 44364213218 正在验证解码计数修复。；本机：python3 -m py_compile 通过；workflow YAML 解析通过且回执清单含 native-product-legacy-import.json；无 pwsh 本机，PowerShell 接线需在 Windows 运行验证；门禁尚未执行，未记为通过。
- 最新记录：新增安装态门禁 native-host/tests/legacy_import_windows.py 并接线 NSIS 安装门禁 installed-legacy-import + 回执上传，提交 d9c8c0f 已开 PR #76（基线 #75 427cde6）。门禁把“包内 importer=受审脚本”“MIGRATE-LEGACY.cmd 指向产品数据根”“旧安装→导入→新安装登录/保留/拒绝覆盖/会话失效/进程回收”写成可证伪断言。
- 最近更新：2026-11-19T02:07:03+08:00

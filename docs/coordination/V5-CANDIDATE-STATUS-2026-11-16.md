# v5.0 完整候选：当前实现与验收状态

快照：2026-11-16 21:13（Asia/Shanghai）。本文不是完成声明；以实际 CI/Release 回执为准。

## 分支 / PR

- 集成分支 `codex/v5-integration`，PR [#63](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/63)，目标 `dev`。
- 堆叠来源：[#59](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/59) W1、[#60](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/60) W2、[#61](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/61) W3、[#62](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/62) W4；集成 PR 含全部提交，合并后这些堆叠 PR 以 superseded 关闭。
- 实际产品工作树：`/home/czl/projects/monitor_wall_czl/.worktrees/v5-w2`（集成），`/home/czl/projects/monitor_wall_v5`（W1）。共享账本入口仍是 `/home/czl/projects/monitor_wall_czl`。

## 已接入的实际产品路径

1. **原生 Studio**：`/api/v1/native/studio` 读取 Program 目标与 transition；宿主解析/授权后通过 OBS frontend 执行 cut/fade，回读当前 Program source；`/api/v1/native/studio/program` 回报 applied/failed；管理页 `/api/v1/studio/runtime` 等待回执。新增 Program 投影（StudioProgram）与注销/失败时锁定 Program。
2. **完整业务服务**：`-Complete` 构建暂存 events、NVR、v2、go2rtc、backup、锁定的 FFmpeg/内嵌 Python 包；supervisor 在同一 Job 内启动。数据根 `%LOCALAPPDATA%\WebOBS\Native`，录像沿用 `%USERPROFILE%\Videos\WebOBS`（可迁移到旧录制目录）。MediaMTX/合成/转码默认不启动。
3. **迁移/恢复**：`migrate_legacy.py` 显式旧 `%LOCALAPPDATA%\WebOBS\config`，SQLite backup API、私密目录、场景/Studio/密钥/录制目录；拒绝覆盖、未确认停机和非法 JSON；旧数据只读保留。`RESTORE-BACKUP.cmd` 恢复加密 `.wobk`。
4. **原生更新**：固定 GitHub Release HTTPS 源，semver、大小、SHA-512、显式确认，更新前配置备份，失败保留当前版本；`latest.yml` 由实际安装包生成。
5. **安装/升级**：完整 NSIS `COMPLETE` 分支支持覆盖升级，卸载保留数据；Start Menu 提供导入/更新/恢复入口；安装测试增加同机 rc→rc 覆盖升级与数据指纹检查。

## 当前证据（滚动更新）

- W1 服务端：本机 core CTest 9/9；`product_http_runtime.py` 双模式 PASS（含 Program 回执）。
- Web：`pnpm typecheck` / `pnpm build` PASS。
- 完整 supervisor/迁移/更新/候选身份：本机单元 PASS；Windows 门禁见下一次运行。
- Windows 完整候选：`43873169070`（rc.1，集成 `944e2f9`）正在运行；此前的失败是 Windows 路径断言、`std::string::isEmpty` 与测试 SQLite 句柄，已修复。
- v4.5 保持只读；未创建 v5 tag/Release，未开放稳定 feed。

## 明确开放缺口

- 目标机真实五路、本人旧数据、物理多屏/DPI/音频设备、逐路硬解与 OBS 同条件三对六轮性能；这些只能最终集中验收。
- LAN/Caddy 远端、MediaMTX 合成输出、检测 provider、部分 OBS 录制/推流业务输出尚未接入默认完整入口；不得用本候选宣称 24 项全部通过。
- 更新入口要求固定 feed；当前候选未随包写入公共 feed，正式更新链需在发布流程中绑定并实测 rc→rc 下载安装。
- 旧 DPAPI 备份密钥迁移为尽力而为；旧数据迁移要求先退出旧版且新配置为空。
- 安装包未签名。

## 下一条动作

1. 等 `43873169070`/后续最终 head 运行结果；失败按阶段日志修复。
2. 通过后下载安装包与 `latest.yml`，核验 SHA-256/SHA-512/size，发布 `v5.0.0-rc.1` prerelease（非 Latest）。
3. 合并 PR63 到 `dev`，关闭 #59–#62 superseded，更新账本 R1/R2/R4/R6 证据。
4. 最终集中验收只要求用户安装冻结候选、验证本人旧数据/真实五路/日常操作/硬解性能；发现阻塞再修。

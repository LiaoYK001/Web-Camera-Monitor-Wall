# v5.1 Windows 完整修复版 / Windows integration hardening

状态：开发中，未构建完整候选、未发布。用户2026-11-17要求以v5.1正式交付为目标，并在其Windows上主要验证v5.1。

优先修复rc.1审查确认的v4.5工作区迁移路径、缓存安装包执行前完整性校验和预发布版本比较。继续现有R2–R7的完整声音、OBS合成输出、远端/离线、迁移/更新、后台任务、体积性能及稳定性工作；不能把未接线项归为仅待实机。

保留v4.5与v5.0.0-rc.1的公开字节。开发只面向dev，正式发布按指定版本审查流程，Windows x64之外的暂停交付范围不变。最终说明必须绑定实际源码、安装包、回执及剩余目标机未测项。

已接入首批修复：v4.5工作区读取真实OBS插件配置路径，并与账号配置一起提交到新profile；提交失败恢复原空目标，允许重试。更新执行前对缓存EXE重新核对实际大小/SHA-512，并在备份后再次核对；拒绝无更新/回退及缺少必要备份材料。预发布版本按数字标识比较，支持rc.9→rc.10与忽略build metadata。

本机SQLite/文件迁移与故障注入、HTTP更新下载和缓存损坏负向回归通过；安装执行器在这些本机测试中为隔离mock，不能当作新Windows安装/个人旧档案验证。完整声音、输出、远端/离线及性能资格仍未完成。

In development, not a qualified candidate or a published release. The requested v5.1 delivery hardens migration and updates and completes outstanding product integration. Published v4.5/rc.1 bytes remain immutable; no unmeasured target-device or OBS-parity claim is implied.

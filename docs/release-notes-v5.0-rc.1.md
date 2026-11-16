# WebOBS Wall v5.0.0-rc.1 完整候选 / Complete Windows candidate

状态：**预发布候选，待目标机集中验收**。不是稳定版，不进入 Latest，不打开稳定更新 feed，不改变 v4.5 已发布附件。
Status: **pre-release candidate pending concentrated target-machine acceptance**. It is not a stable release, does not become Latest, does not open the stable updater feed and does not change published v4.5 assets.

## 交付内容 / What is included

- 单一 `WebOBS Wall` 安装入口，Windows x64，未签名 NSIS；数据在 `%LOCALAPPDATA%\WebOBS\Native`，卸载保留。
- 原生 OBS/Qt 媒体宿主：认证监看、1–64 路有界快捷墙、已保存 Studio 场景、Preview/Program、真实 cut/fade TAKE、Program 回执与 Program 投影。
- 完整构建暂存并启动 events、NVR、v2 客户端、go2rtc、backup 与内嵌依赖；默认不启动 MediaMTX、合成或转码。
- 旧版配置显式迁移：SQLite backup API、账号/相机/场景/密钥/录制目录，拒绝覆盖和未确认停机。
- 原生 `latest.yml` 更新检查/下载/大小与 SHA-512 校验/用户确认安装；覆盖升级和卸载保留数据。
- Start Menu 入口：主程序、导入旧版数据、检查更新、恢复备份。

A single unsigned Windows x64 `WebOBS Wall` installer with native OBS/Qt monitoring, bounded 1–64 wall, saved Studio scenes, real Preview/Program TAKE and Program projector; complete business-service staging and supervision; explicit legacy migration; native update verification and confirmed installation; and Start Menu entries for import, update and restore. Data and uninstall retention are outside the install directory.

## 验证 / Verification

- Windows 完整候选 run: <!-- RUN_URL -->
- 源码/构建身份: <!-- SOURCE_REVISION -->
- 安装包: <!-- INSTALLER_NAME -->, <!-- INSTALLER_BYTES --> bytes, SHA-256 `<!-- SHA256 -->`, SHA-512 `<!-- SHA512 -->`.
- 门禁: <!-- CHECKS -->

## 已知边界 / Known limits

- 目标机真实五路、本人旧数据、物理多屏/DPI/音频设备、实际硬解与 OBS 同条件性能仍需最终集中验收。
- 旧–>新迁移要求先退出旧版；目标配置必须为空。旧 DPAPI 备份密钥迁移为尽力而为。
- 更新入口是安装后的“检查更新”快捷方式，不是应用内后台自动更新；候选不提供稳定 feed。
- LAN/Caddy 远端、MediaMTX 合成输出、检测 provider 与部分 OBS 业务输出仍未完成；本候选不伪称全部 24 项已验收。
- 未签名包；不宣称 Authenticode 发布者身份。

## 安装与升级 / Install and upgrade

1. 关闭旧版 WebOBS 和任何 WebOBS Wall 进程。
2. 运行完整安装包；首次启动前可用“导入旧版 WebOBS 数据”快捷方式迁移，旧数据只读保留。
3. 登录原账号；在 Studio/设备页检查场景与相机。
4. 后续候选可用“检查 WebOBS 更新”验证下载和覆盖升级；更新前先备份配置。
5. 卸载保留 `%LOCALAPPDATA%\WebOBS\Native` 与录像；需要彻底删除时由用户手动处理。

Do not delete the old installation or its data before verifying the migrated account, scenes and recordings. Uninstall intentionally retains the new private profile and recordings.

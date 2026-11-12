# WebOBS 4.1.0-dev.40 原生监看原型 / Native monitor prototype

**Windows x64、未签名、独立 OBS/Qt 原型、Pre-release；不是稳定版，不进入 stable 更新源，也不替换 Latest。**

Windows x64, unsigned, independent OBS/Qt prototype, development prerelease only. This is not a stable release, does not enter the stable update feed and does not replace Latest.

## 固定构建 / Frozen build

- 源码 / Source: `3c916db18de59e86dfbd14f39ea53cef1f564005`.
- 成功构建 / Successful build: https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41228010208 （完整产品构建与原生宿主安装验证通过 / complete product build and native-host installer verification passed）.
- 不可变构建 artifact: `13052358847`, `123,286,064` 字节, 摘要 `sha256:0f338160fc3ef8fcd64a2d02977884513440029467dfbcd4277c168fc60fdd3d`.
- 附件直接复制该构建字节，不重新打包、不替换 DLL。发布前在本机重新下载 artifact 并核对摘要与附件哈希；上传后 GitHub 记录的摘要与本地哈希一致。
- The attached bytes are copied from that build without repacking or replacing DLLs. The artifact was re-downloaded and its digest checked locally before upload; GitHub's stored asset digests match the local hashes.

## 附件 / Assets

| 文件 / File | 字节 / Bytes | SHA-256 |
| --- | ---: | --- |
| `WebOBS-OBS-native-4.1.0-dev.40-windows-x64-PROTOTYPE.zip` | 78,029,241 | `634af4be2fd9b7a0709a29a87ad67e8b3a0662fcaf54043205c1cdf21402ab18` |
| `WebOBS-OBS-native-4.1.0-dev.40-windows-x64-SETUP.exe` | 45,250,255 | `7cc5724c0aee941802bdc9f8ed71b7547d1b3d73631170e003c5a03d7bb2a54d` |
| `SHA256SUMS.txt` | — | 校验上两项 / checksums of both files |

## 本构建新增 / What this build adds

- 每用户 NSIS 安装包原型：静默安装到 `%LOCALAPPDATA%\WebOBS Native Prototype`，仅写 HKCU 卸载信息、不注册服务；安装包不含 `config/`，重装覆盖程序文件而不触碰现有 `config/`，静默卸载删除程序文件但逐字节保留 `config/`（RTSP 凭据与五格墙）并清理注册表。安装器 45,250,255 字节，安装 1,579 个文件后双启动烟测通过；重装前后 `config/obs-studio` 逐文件哈希一致。
- A per-user NSIS installer prototype: silent install under `%LOCALAPPDATA%\WebOBS Native Prototype`, only HKCU uninstall metadata, no service; the package carries no `config/`, reinstall leaves an existing `config/` untouched, and silent uninstall removes program files while preserving `config/` byte for byte (RTSP credentials and the five-tile wall) and cleaning the registry. The installer is 45,250,255 bytes; the silent install of 1,579 files passed the two-launch smoke, and per-file `config/obs-studio` hashes were identical across a reinstall.
- 同一冻结 runtime 的 ZIP 可直接解压为便携目录；`runtime/` 与校验回执仅在构建 artifact 中，不随发布附件分发。
- The same frozen runtime ZIP can be extracted as a portable directory; the `runtime/` tree and verification receipts stay in the build artifact and are not attached.

## 已知限制 / Known limits

- 未签名、无自动更新、无跨版本安装器升级/数据迁移；不是产品安装器，不替换默认 Electron 产品。
- Unsigned, no auto-update, no cross-version installer upgrade or data migration; not the product installer and does not replace the default Electron product.
- 像素门槛仍为 GitHub 托管 Windows Server 2022（Microsoft Basic Render Driver 软件 D3D11）+ 合成 RTSP 输入：九阶段（含全屏投影与跨断流恢复）通过，但不证明目标 i9-13900HX/RTX 4090 Laptop、真实五路 H.265、硬件解码、低延迟、功耗或与 OBS 同机对照。
- The pixel gate still runs on GitHub-hosted Windows Server 2022 (Microsoft Basic Render Driver, software D3D11) with synthetic RTSP inputs: nine phases (including fullscreen projector and recovery across a stream interruption) pass, but this does not qualify the target i9-13900HX/RTX 4090 Laptop, five real H.265 cameras, hardware decoding, latency, power or same-machine OBS comparison.
- P1 显示缺口（DPI 缩放、多显示器、保存场景重启）、P3 能力迁移与 P5 目标机性能/体积门槛保持未通过；本开发包发布不代表这些目标达成。

## 测试与反馈 / Testing and feedback

请在保存既有配置的独立 Windows 测试环境中使用，先核对 `SHA256SUMS.txt`，再确认五路完整可见且时间持续推进；分别记录首次打开、关闭/重开、TAKE、全屏/DPI/多显示器与断线恢复。公开反馈仅提交匿名来源编号、时间与不含私密内容的结果；不公开相机地址、口令、token、配置、完整日志或真实画面。

Use a separate Windows test environment that already has the configuration you want to keep. Verify `SHA256SUMS.txt`, then confirm all five cameras are fully visible and advancing; record first open, close/reopen, TAKE, fullscreen/DPI/multi-monitor and reconnect behaviour. Public feedback should contain only anonymous source index, time and non-private results; never publish camera URLs, credentials, tokens, configuration, full logs or real frames.

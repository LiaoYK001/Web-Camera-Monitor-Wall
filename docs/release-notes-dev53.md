# WebOBS 4.1.0-dev.53 原生监看原型 / Native monitor prototype

**Windows x64、未签名、独立 OBS/Qt 原型、Pre-release；不是稳定版，不进入 stable 更新源，也不替换 Latest。**

Windows x64, unsigned, independent OBS/Qt prototype, development prerelease only. This is not a stable release, does not enter the stable update feed and does not replace Latest.

## 固定构建 / Frozen build

- 源码 / Source: `b77f9160385ad6370a0587ea448942c0250f1dcc`.
- 成功构建 / Successful build: https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41250011450 （完整构建、十阶段像素回归 run 41250018069 与全部原生宿主烟测通过 / complete build, ten-phase pixel run 41250018069 and all native-host smokes passed）.
- 不可变构建 artifact: `13060374195`, `68,909,368` 字节, 摘要 `sha256:08ee3b052b0a8abfb851d2d4db5cee7b162b40d719f128f93cd4608788c4f806`.
- 附件直接复制该构建字节，不重新打包、不替换 DLL。发布前在本机重新下载 artifact 并核对摘要与附件哈希；上传后 GitHub 记录的摘要与本地哈希一致。
- The attached bytes are copied from that build without repacking or replacing DLLs. The artifact was re-downloaded and its digest checked locally before upload; GitHub's stored asset digests match the local hashes.

## 附件 / Assets

| 文件 / File | 字节 / Bytes | SHA-256 |
| --- | ---: | --- |
| `WebOBS-OBS-native-4.1.0-dev.53-windows-x64-PROTOTYPE.zip` | 41,484,488 | `2d065e4671357d54e7d29983918baf8040260a5c5f65b276181bf79b5df9c3e8` |
| `WebOBS-OBS-native-4.1.0-dev.53-windows-x64-SETUP.exe` | 27,408,522 | `3c7f58466600982ae13bbab98d67ef2dd8edc9f2623bbf1b0f8eedbf7694caab` |
| `SHA256SUMS.txt` | — | 校验上两项 / checksums of both files |

## 本构建新增 / What this build adds

- P4 构建符号剥离：生成清单前删除运行时 34 个 PDB（144,351,232 B），断言零残留，NSIS 拒绝含 PDB 的安装树。运行时解包 243,502,095 → 99,168,288 B，SETUP 45,172,904 → 27,408,522 B，附件总字节减少 44.1%。
- P4 build-symbol pruning: 34 runtime PDBs (144,351,232 B) are removed before the manifest and zero survivors are asserted; NSIS rejects a PDB-bearing install tree. Runtime unpacked size drops from 243,502,095 to 99,168,288 B and SETUP from 45,172,904 to 27,408,522 B, a 44.1% reduction in attached bytes.
- 十阶段像素门槛（相对 dev.40 的九阶段新增保存场景重启）：已知颜色、五种编码、预览不 TAKE、显式 TAKE、Program 重开、RTSP 回环、断流恢复、全屏投影、全屏跨断流恢复、重启后保存场景五格墙重建，全部通过。
- Ten-phase pixel gate (saved-scene restart is new since dev.40's nine): known colours, five codecs, preview without TAKE, explicit TAKE, Program reopen, RTSP loopback, recovery across an interruption, fullscreen projector, fullscreen across an interruption, and the saved five-tile wall rebuilt after a restart — all pass.
- 生命周期烟测：正常退出后无残留进程/服务监听，故意终止真实 OBS 宿主后无残留，第二个启动在创建运行时前被单实例锁拒绝，已发布的 dev.40 安装包可就地升级到本版本且 `config/` 逐文件哈希不变、卸载保留私密配置并清理注册表。
- Lifecycle smokes: normal exit leaves no surviving processes or service listeners; a deliberate kill of the real OBS host leaves none; a second launch is refused by the single-instance lock before it can create a runtime; the published dev.40 installer upgrades in place to this build with per-file `config/` hashes unchanged, and uninstall preserves the private profile and cleans the registry.

## 已知限制 / Known limits

- 未签名、无自动更新、无降级保护；不是产品安装器，不替换默认 Electron 产品。
- Unsigned, no auto-update, no downgrade protection; not the product installer and does not replace the default Electron product.
- 像素门槛仍为 GitHub 托管 Windows Server 2022（Microsoft Basic Render Driver 软件 D3D11）+ 合成 RTSP 输入 + 固定 960×540；不证明目标 i9-13900HX/RTX 4090 Laptop、真实五路 H.265、硬件解码、DPI/多显示器、延迟、功耗或与 OBS 同机对照。
- The pixel gate still runs on GitHub-hosted Windows Server 2022 (Microsoft Basic Render Driver, software D3D11) with synthetic RTSP inputs at a fixed 960×540; it does not qualify the target i9-13900HX/RTX 4090 Laptop, five real H.265 cameras, hardware decoding, DPI/multi-monitor, latency, power or same-machine OBS comparison.
- P1 真实输入/显示缺口、P3 能力迁移、P4 插件/资源清理与 SBOM、P5 目标机性能/体积门槛保持未通过；本开发包发布不代表这些目标达成。
- P1 real-input/display gaps, P3 capability migration, P4 plug-in/resource cleanup and SBOM, and the P5 target-machine performance/size gates remain open; this prerelease does not claim them.

## 测试与反馈 / Testing and feedback

请在保存既有配置的独立 Windows 测试环境中使用，先核对 `SHA256SUMS.txt`，再确认五路完整可见且时间持续推进；分别记录首次打开、关闭/重开、TAKE、全屏/DPI/多显示器与断线恢复。公开反馈仅提交匿名来源编号、时间与不含私密内容的结果；不公开相机地址、口令、token、配置、完整日志或真实画面。

Use a separate Windows test environment that already has the configuration you want to keep. Verify `SHA256SUMS.txt`, then confirm all five cameras are fully visible and advancing; record first open, close/reopen, TAKE, fullscreen/DPI/multi-monitor and reconnect behaviour. Public feedback should contain only anonymous source index, time and non-private results; never publish camera URLs, credentials, tokens, configuration, full logs or real frames.

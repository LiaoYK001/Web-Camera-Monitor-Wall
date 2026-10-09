# v4 网站与 RTSP 接入验收 / Website and RTSP validation

2026-10-09 在 Windows 原生完整服务上实测，不以支持网站列表或流名出现作为播放成功。当前改动属于 `dev`，未发布正式补丁，原 v4.0 安装包未改变。

These checks exercised complete native Windows services on 2026-10-09. A listed website or saved stream name alone is not playback qualification. Fixes remain on `dev`; no stable patch or replacement v4.0 asset is announced here.

## 实测结果 / Actual results

| 来源 / Source | 解析 / Engine | 冷导入、轨道、MSE、场景 / Cold import, tracks, MSE, Studio | 实际画面 / Decoded size | 整应用重启后保留 / Restart persistence |
| --- | --- | --- | --- | --- |
| [DW News 公开直播](https://www.youtube.com/@DWNews/live) | 自动 → yt-dlp | 通过 / Passed，完整单路步骤 29 s | 1280×720 | 流、设备、场景 / Stream, device, scene |
| [Al Jazeera English 公开直播](https://www.youtube.com/@AlJazeeraEnglish/live) | 自动 → yt-dlp | 通过 / Passed，26 s | 1280×720 | 流、设备、场景 / Stream, device, scene |
| DW News 同一直播 / Same live page | Streamlink | 通过 / Passed，22 s | 1280×720 | 流、设备、场景 / Stream, device, scene |
| 独立回环 RTSP，随机密码含 URL 保留字符 / Isolated RTSP with encoded reserved characters in a random password | 自动 → 直接 / Automatic → direct | 通过 / Passed，11 s | 160×90 合成画面 / Synthetic | 流、设备、场景 / Stream, device, scene |

公开直播的严格回执时间为 `2026-10-09T11:10:43.531Z`。原生后端来自已通过完整 Windows 构建的 `4.0.1-dev.3`，提交 `02d0f5a288724ea5e5d6d8d24b3f5582e98ecd6d`，全部运行文件通过 manifest 校验；前端使用本次修复的本机生产构建，入口 SHA-256 为 `d804671e114e3809590e6cc2bae25a510a43582bed29f4385d73a2a0f76f6d34`。测试替换静态前端响应，认证、配置、媒体、设备和 Studio API 全部使用真实原生服务。这是开发组合实测，不等于包含新 UI 的 NSIS 已通过；新安装候选须重新完成构建门禁。

The public-source receipt was completed at the timestamp above. Its manifest-verified backend is dev.3 at the specified commit; its frontend is the current local production build, identified by the entry hash. Only static frontend files were supplied locally: authentication, configuration, media, camera and Studio APIs used actual services. This development combination does not qualify an installer containing the new UI; that candidate needs a fresh full build.

三个公开来源另外各通过两次真实 RTSP 连接与 FFmpeg 解码，覆盖断开后的重新解析/重连；消费者关闭后按需生产者停止。早期试跑有一次未分类解码失败，未保留足够诊断，不能断言其根因已修复；随后增加脱敏诊断的媒体测试、独立 UI 冷启动测试均通过。站点、CDN、地域和网络状态会变化，正式候选仍需复验，失败应保留私密诊断，不以无解释复跑覆盖失败记录。

Each public route also passed two actual RTSP connections and FFmpeg decoding, followed by on-demand producer shutdown. One early decoding failure lacked sufficient diagnostics to establish its cause. Subsequent media tests with redacted diagnostics and independent cold UI tests passed; this does not establish that every transient network or site failure is fixed. Recheck the final candidate and retain private failure evidence.

## 固定构建门禁 / Deterministic build gate

`desktop/tests/run-online-source-native.mjs` 使用独立临时账号与数据目录。默认启动带随机认证信息的本地合成 RTSP 服务，不连接公网，不改变现有产品安装。实际流程为：

1. UI 默认自动识别 RTSP，保存命名流并重载 go2rtc。
2. 不预先播放，直接点击“检测并添加设备”；要求真实轨道 `probeState=ready` 且分辨率有效。
3. 认证 MSE 解码，要求视频尺寸有效且播放时间持续推进。
4. UI 创建 Studio 场景并保存；检查后端设备身份引用和刷新后保留。
5. 正常停止并重启完整产品；重新登录，核对命名流、设备身份和场景。

补充主页检查：保存 Studio 后执行 `TAKE`，在“监看 Monitor”要求真实视频尺寸有效且时间推进；整产品重启后再次检查当前 Program 的主页解码。公开 DW / Al Jazeera 的三个解析路径及带认证 RTSP 已通过 Take 后主页检查，随后把重启后主页恢复加入固定门禁。Studio 保存本身只保存 Preview，仍需 Take 才进入 Program。

The extended gate performs Take, verifies actual advancing video on Monitor, then verifies the active Program again after full-product restart. All three public routes and authenticated RTSP passed the initial monitor-wall checks before adding restart playback to the deterministic gate. Saving Studio preserves Preview; Take selects Program.

The default gate uses an isolated authenticated synthetic RTSP server, actual UI actions and native services. It requires ready tracks, advancing decoded video, persisted Studio references and full-product restart persistence. It never modifies an existing installation. Failures retain the private temporary profile for diagnosis; successful runs clean it after Electron exits. Do not attach private profiles/configuration/logs to a public release.

```powershell
node desktop/tests/run-online-source-native.mjs --runtime <完整运行时绝对路径> --receipt <回执路径>
```

完整 Windows 构建在打包前自动运行此门禁，使用锁定 Playwright 的 Chromium；通过回执进入 `desktop/out/<版本>/windows-source-ui.json`。现有七次配置重载、Electron、完整打包和 NSIS 安装/卸载门禁继续执行。

The full Windows build runs this gate before packaging with Chromium from the locked Playwright dependency. Its receipt accompanies the candidate. Existing reload, Electron, packaged-runtime and NSIS installation/uninstallation checks still apply.

## 发布前公开来源复验 / Public-source recheck

显式准备仓库外 JSON 数组，每项包含 `name`、`address` 和 `engine`，仅选择公开、可访问且当时在线的来源，例如 `{"name":"dw-live","address":"https://www.youtube.com/@DWNews/live","engine":"auto"}`。然后运行：

```powershell
node desktop/tests/run-online-source-native.mjs --runtime <最终候选运行时> --sources <公开来源清单.json> --receipt <公开来源回执.json>
```

Supply an explicit JSON array of currently available public sources. The same cold import, decoded-video, Studio and restart checks run. Omit `--frontend` for final-candidate qualification; that option is only for a documented local frontend/backend development combination.

本轮未验收真摄像机、ARM 设备、音频硬件、干净 Windows 安装或生产安装包升级；本机公网成功不代表 GitHub runner、其他地区或需登录网站可用。不得把本表改写为所有 YouTube 直播保证可用。

Physical cameras, ARM, audio hardware, clean-machine installation and production-package upgrades are separate qualifications. Results do not guarantee every YouTube live stream, region, network or authenticated site.

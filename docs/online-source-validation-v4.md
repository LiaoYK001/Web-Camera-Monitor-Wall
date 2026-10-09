# v4 网站与 RTSP 接入验收 / Website and RTSP validation

2026-10-09 在 Windows 原生完整服务上实测，不以支持网站列表或流名出现作为播放成功。当前改动属于 `dev`，未发布正式补丁，原 v4.0 安装包未改变。

These checks exercised complete native Windows services on 2026-10-09. A listed website or saved stream name alone is not playback qualification. Fixes remain on `dev`; no stable patch or replacement v4.0 asset is announced here.

## 最终开发候选实测 / Final development-candidate results

[`4.0.1-dev.5` 完整 Windows 构建](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/37925142592) 与[同提交常规 CI](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/37925141245) 全部通过。候选提交为 `7001bae07760b37b446f33728a0df3196d7f2f20`。本机公开直播复验于 `2026-10-09T12:03:57.030Z` 完成，直接使用候选运行时和内置前端，未替换静态资源（`frontendOverride=false`）；全部运行文件通过 manifest 校验，前端入口 SHA-256 为 `be2c988e9a325d2acd007cc0202d3f80c8744056355bf7f0b8e6507dc0b757eb`。

Both the full Windows candidate build and same-commit public CI passed. Public live-source qualification used the candidate's own manifest-verified runtime and frontend with no static override. The timestamp, revision and entry hash identify this check. This is a development candidate, not a published stable patch.


| 来源 / Source | 解析 / Engine | 冷导入、轨道、MSE、场景 / Cold import, tracks, MSE, Studio | 实际画面 / Decoded size | 整应用重启后保留 / Restart persistence |
| --- | --- | --- | --- | --- |
| [DW News 公开直播](https://www.youtube.com/@DWNews/live) | 自动 → yt-dlp | 通过 / Passed，含 Take 后主页播放 34 s | 1280×720 | 流、设备、场景 / Stream, device, scene |
| [Al Jazeera English 公开直播](https://www.youtube.com/@AlJazeeraEnglish/live) | 自动 → yt-dlp | 通过 / Passed，含主页播放 35 s | 1280×720 | 流、设备、场景 / Stream, device, scene |
| DW News 同一直播 / Same live page | Streamlink | 通过 / Passed，含主页播放 27 s | 1280×720 | 流、设备、场景 / Stream, device, scene |
| 独立回环 RTSP，随机密码含 URL 保留字符 / Isolated RTSP with encoded reserved characters in a random password | 自动 → 直接 / Automatic → direct | 通过 / Passed，候选 CI 含主页播放 19 s | 160×90 合成画面 / Synthetic | 流、设备、场景 / Stream, device, scene |

此前开发组合的回执时间为 `2026-10-09T11:10:43.531Z`：后端来自 `4.0.1-dev.3`，提交 `02d0f5a288724ea5e5d6d8d24b3f5582e98ecd6d`，前端为本机生产构建，入口 SHA-256 为 `d804671e114e3809590e6cc2bae25a510a43582bed29f4385d73a2a0f76f6d34`。该轮只替换静态前端，API 全部使用真实服务，是开发组合证据；现在上表由 dev.5 候选自身的复验补齐，不能混淆两轮的提交和摘要。

The earlier dev.3 backend plus local-frontend check is historical development evidence. Its revision and entry hash differ from the final dev.5 recheck above. All three final public routes passed actual monitor-wall playback after Take; the active Program (DW/Streamlink) also decoded again after full-product restart. Candidate CI independently passed the same restart playback check with authenticated synthetic RTSP.

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

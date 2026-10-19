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

## v4.1 后续验收（2026-10-14） / Subsequent v4.1 qualification

Windows `4.1.0-dev.8` / `0468c0217b533e617ccbd29f2d4f2371592ff946` 的完整 CI 已通过。新增本机验收使用全部 manifest 校验后的候选自身前端（入口 SHA-256 `be74993a577dbee54dac99809ae76ae932059b5c63dc2c35659c1b76a4beeac0`，无前端替换）：私密随机认证 RTSP → 冷建档/轨道探测 → MSE → Studio/TAKE → 主页可见帧；在播放中通过认证产品 API 重启 go2rtc，不刷新页面、不重启应用，等待超过短 RTC 缓冲后要求新的呈现帧与时间推进。设备 ID 保持不变，随后整产品重启及主页恢复也通过。

Dev.8 passed its complete Windows CI. The additional local gate used its manifest-verified bundled frontend and an authenticated synthetic RTSP source. Monitor recovered new presented frames after a go2rtc-only restart, without page reload or full-app restart, then also passed full-product restart recovery. This does not qualify changing codecs under an existing stream name, public-site network faults or physical cameras.

固定来源门禁现加入 go2rtc-only 重启恢复，回执字段为 `go2rtcRestartFramePresented`。Windows CI 的 dev.8 构建快照早于此新增断言，不能声称该 CI 已运行这一新增检查；上述结果来自随后本机使用该候选的独立实测。[完整 v4.1 范围与待完成项](release-notes-v4.1.md)。The new assertion is an additional local check against the candidate, not a retroactive claim about its earlier CI snapshot.

后续同址编码切换检查在 dev.8 **失败**：私密 RTSP 测试源保持 URI/认证/设备 ID/B 帧数量不变，从 H.264 160×90 改为 HEVC 320×180，主页没有自行恢复，目录 codec 仍为旧值。新固定门禁加入该切换，要求无需手动探测/页面刷新即可更新轨道并呈现 320×180 新帧，然后再验证 go2rtc-only 和完整产品重启。修复源码已通过 Linux 核心与实际 Electron 的旧 codec 提示/新编码流验证；包含修复的 Windows 候选仍需运行这条完整新门禁，不能将 dev.8 原通过结果扩展到本场景。

Dev.8 failed the subsequent same-URL H264-to-HEVC switch without manual intervention. The strengthened synthetic gate now requires automatic track refresh and new-resolution presentation before its restart checks. Linux-core/Electron recovery passed after the source fix; complete new Windows qualification is still pending.

2026-10-19 更新：包含该修复及新增断言的 `4.1.0-dev.9` / `358dafc` [完整 Windows CI](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/38499041402)已成功，构建脚本在打包前执行固定来源门禁；[同提交完整容器预检](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/38499044749)也成功。此结果补上 Windows 合成来源编码切换验收，不扩大为公网一小时、网络故障或物理摄像机验收。先前 dev.8 一小时公网尝试缺少完成回执，仍待补测。

Dev.9's complete Windows CI passed with the codec-change fix and strengthened source gate executed before packaging; the same-source full container preflight also passed. This qualifies the synthetic Windows codec-switch case, separately from one-hour public-site, network-fault and physical-camera checks. An earlier interrupted dev.8 one-hour public attempt has no completion receipt and remains unqualified.

新增监看页实时占用栏后，固定 Windows 门禁还会展开该栏、等待真实进程采样、核对播放器 DOM 节点未替换，收起后要求新的呈现帧；回执使用 `liveProcessReadout`。此断言晚于 dev.10，须由后续完整候选执行；不能追溯扩展旧 CI 的覆盖范围。来源门禁使用锁定 Playwright Chromium 的页面视口与实际媒体合成回调；它与前述实际可见 Electron 五路性能测试分别记录，不宣称是同一个渲染器测试。

The subsequent Windows gate opens the live process readout, waits for real CPU samples, verifies the player element is retained and requires another presented frame after collapse. Its `liveProcessReadout` receipt must come from a candidate after dev.10. This source gate uses locked Playwright Chromium's viewport/compositor; it is recorded separately from the actual visible Electron five-stream performance run.

## 双路公开源一小时与故障恢复（2026-10-19） / Paired public-source hour and recovery

使用 `4.1.0-dev.10` / `32f6ccb8ce9eff964849f90d81d28028e6c78668` 的完整 manifest 校验运行时与捆绑前端，无静态替换，入口 SHA-256 为 `55b24910a42a0a692018ecc6c2b61f9904cce8d113542e55a0a938c9dc96b16e`。两路同时进入同一 Program，通过锁定 Playwright Chromium（headless、页面 visible、画面完整位于视口）的真实呈现回调与非丢弃帧增长检查；不是实际 Electron 窗口的性能测试。完成回执为 `2026-10-19T06:47:32.797Z`。

The manifest-verified dev.10 candidate used its bundled frontend without override. Both sources played simultaneously in one Program, with viewport bounds, visible document state, real video frame callbacks and non-dropped progress checked in locked headless Playwright Chromium. This is distinct from actual Electron-window performance qualification.

| 来源 / Source | 测试开始时状态 / Initial status | 同时监看 / Paired duration | 总帧 / Total | 丢弃 / Dropped | 非丢弃平均 FPS / Non-dropped FPS |
| --- | --- | --- | --- | --- | --- |
| [用户指定来源 / Reported source](https://www.youtube.com/watch?v=eYDDvvGbhp8) | 已结束直播的回放 / Replay (`was_live`) | 3601 s | 107965 | 147 (0.14%) | 29.94 |
| [DW News](https://www.youtube.com/@DWNews/live) | 直播 / Live (`LuKwFajn37U`, `is_live`) | 3601 s | 196417 | 20916 (10.65%) | 48.74 |

每路均通过 UI 冷保存/导入、真实轨道探测、MSE、Studio/TAKE、主页播放及独立 go2rtc 重启。小时检查取得 645 次双路增长采样。随后专用回环 CONNECT 夹具只中断本次后端访问公网的连接 40 秒，确认缓冲耗尽后两路停止增长；恢复后不刷新页面，两路均再次呈现并推进。之后双路 go2rtc 重启、完整产品正常重启、流/设备身份/场景保留及重启后双路主页呈现均通过。

Each source passed cold UI import, track probing, MSE, Studio/TAKE and individual go2rtc restart. The hour produced 645 paired progress samples. An owned loopback CONNECT fixture then interrupted only this backend's external connections for 40 seconds, verified both buffers stopped advancing, and required new presented frames after restoration without page reload. A subsequent paired go2rtc restart and full normal product restart also passed, preserving streams, device identities and Studio with both Monitor videos presenting again.

**这是持续播放与恢复通过，不是零掉帧或流畅度达标。** DW 的浏览器丢弃比例约 10.65%，需进一步区分来源/网络、接收与渲染因素；本轮未采集足以确定掉帧根因的 RTC 解码统计。未据此承诺所有地区、站点、摄像机、音频硬件或用户笔记本均稳定。早前 dev.8 中断的一小时尝试仍不计通过；新断网夹具初次认证/传输超时及视口错误的失败回执也保留，修正夹具后才执行本轮长测，未放宽产品预算。

**Continuous playback and recovery passed, not zero-drop or smoothness qualification.** DW's 10.65% browser drops remain an investigation item; this run did not capture enough RTC decoder statistics to establish their cause. Earlier interrupted dev.8 and initial fixture failures remain retained. Fixture authentication/transfer/viewport corrections did not relax product deadlines. No physical-camera, audio-hardware, region-wide or user-laptop guarantee follows from this result.

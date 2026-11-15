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

此前开发组合的回执时间为 `2026-10-09T11:10:43.531Z`：后端来自 `4.0.1-dev.3`，提交 `02d0f5a288724ea5e5d6d8d24b3f5582e98ecd6d`，前端为本机生产构建，入口 SHA-256 为 `d804671e114e3809590e6cc2bae25a510a43582bed29f4385d73a2a0f76f6d34`。该轮只替换初始页面的静态前端，API 全部使用真实服务；后续管理页与重启页实际使用捆绑前端，因此不能把入口摘要扩展为全流程前端身份，是有限的开发组合证据；现在上表由 dev.5 候选自身的复验补齐，不能混淆两轮的提交和摘要。

The earlier dev.3 backend plus local-frontend check is historical development evidence: only its initial page used the override; management and restart pages used bundled assets, so the entry hash does not identify their frontend. Its revision and entry hash differ from the final dev.5 recheck above. All three final public routes passed actual monitor-wall playback after Take; the active Program (DW/Streamlink) also decoded again after full-product restart. Candidate CI independently passed the same restart playback check with authenticated synthetic RTSP.

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


## 前端身份检查补强（2026-10-19） / Frontend identity checks

默认候选仍使用完整捆绑前端，不授予额外浏览器权限。开发用 `--frontend` 现应用于整个浏览器 context（含管理页和重启后的新 context），只拦截列明的静态路径；管理页与重启页的实际 HTML 响应分别校验入口 SHA-256，回执新增 `frontendDocumentsVerified`。旧的仅初始页面替换结果不追溯扩大；`frontendOverride=false` 的候选结果不受此缺口影响。

Bundled candidates keep their own frontend and receive no additional browser permission. Development overrides now cover all pages and the restored context, intercept only explicit static paths and hash actual management/restart HTML responses. Historical initial-page-only overrides do not establish full-flow frontend identity; bundled candidate results are unaffected.

Chromium 对测试中由路由直接返回的 HTML 曾报 `ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS`，WebSocket 尚未握手便失败。仅开发替换模式对本次自建 `127.0.0.1` origin 授予 `local-network-access`，回执明确记录权限范围；不更改产品权限或关闭浏览器安全检查。[Playwright 权限接口](https://playwright.dev/docs/api/class-browsercontext#browser-context-grant-permissions)与 [Chrome 本地网络访问说明](https://developer.chrome.com/blog/local-network-access)。The override-only permission is restricted to the owned loopback origin and explicitly recorded; normal candidate qualification grants none.

对完整 manifest 校验的 dev.12 / `d6387db`，捆绑模式和本机构建替换模式分别通过：每轮实际 HTML 校验 2 次，CPU 栏节点保留、编码切换、go2rtc 与完整重启均通过。捆绑入口摘要为 `a40ccf21d36e8e3e67c36781e4086342aa6319f7ba17a9851e2686680d74e4a7`；替换入口为 `0a0950fc676d56e01cd60c5dda0743626b0ae50180aa1ee44bfa1917bf6bb30e`。先前矩阵包装器的替换轮在 initialization 阶段失败，缺少足够诊断，仍保留并标为根因未明；后续独立通过不证明该次失败已修复。新增身份断言晚于 dev.12 CI，不能追溯声称该 CI 已运行。

Both bundled and local-override runs against manifest-verified dev.12 passed two actual-document hashes and the CPU/media/restart checks. A prior matrix-wrapper initialization failure remains retained without an established cause. Independent passing receipts do not resolve that failure or retroactively extend dev.12 CI coverage. The overridden run remains a development combination, not a release candidate.


## MSE 长停顿定位与修复验证（2026-10-19） / MSE stall investigation

在 manifest 校验后的 dev.12 上，使用实际可见 Electron、同一 DW 直播生产者及两个同时可见的最小 VideoRTC 播放器；只对一侧播放器模块做私密诊断替换，并校验实际加载的实现。不是完整新候选、CPU 基准或 WHEP 主监看页验收。两个播放器使用相同源分辨率与编码，不降低源 FPS。

The controlled diagnostic used manifest-verified dev.12 and the actual visible Electron renderer, with two minimal same-source VideoRTC players. One module was explicitly overridden and its loaded implementation checked. This is development evidence, not complete-candidate, CPU or Monitor-WHEP qualification.

先比较原始速率与 1.00–1.05 限幅：187.804 秒内两侧仍有约 10.5 秒停顿，限幅侧呈现回调反而更少，**未采用此策略**。独立 90 秒观察取得两侧完全相同的 9074 条二进制消息、14577146 字节，最长到达间隔约 0.578 秒。首轮因模块缓存导致实验实现未加载的结果、后续夹具重复播放器失败均保留，不计为有效对照。

Rate limiting alone failed to remove the stalls and was rejected. A separate 90-second observation received identical binary messages/bytes on both sides, with maximum arrival gaps around 0.578 seconds. An earlier unloaded-override attempt and a duplicate-player fixture failure remain excluded from the comparison.

随后只改变历史保留范围，原始播放速率及落后超过 5 秒的追赶条件保持不变。预热后 36 次同步采样、199.145 秒结果：

| 策略 / Policy | 新呈现回调 / New frame callbacks | 新 waiting 事件 / New waiting events | 新增 >250ms 回调间隔 / New callback gaps |
| --- | --- | --- | --- |
| 原始 5 秒历史 / Original five-second history | 1356 | 65 | 25 |
| 30 秒历史、原追赶条件 / Thirty-second history, same live-edge condition | 12047 | 0 | 0 |

250ms 是本次自定义回调间隔阈值，不是 RTC 标准 freezeCount。原始侧全程最长间隔约 10.529 秒；修复侧最长约 0.462 秒发生在预热阶段，测量段没有新增超过 250ms 的间隔。另一个 90 秒删除观察中，原始侧 19/19 次清理把实际保留起点推进到播放位置之后，修复侧 0/23 次；实际删除边界会推进到后续关键帧，与 [MSE 编码帧删除算法](https://www.w3.org/TR/media-source-1/#sourcebuffer-coded-frame-removal)一致。这是此 MSE 场景的因果证据，不能解释或宣称修复全部 WHEP/网站冻结。

The 250ms threshold is a custom callback-gap metric, not RTC freezeCount. A separate removal observation found the playing position outside the retained range after 19/19 original removals, versus 0/23 adapted removals, consistent with MSE's random-access/dependency removal rules. This establishes the MSE case separately from unresolved WHEP freezes.

本地无公网合成源（160×90、30fps、H.264、零 B 帧、300 帧/10 秒 GOP）再对照 61.604 秒：原始侧新增 118 次呈现回调、12 次 waiting、6 次 >250ms 间隔，最长约 9.836 秒；修复侧 1852 次呈现回调、0 waiting、0 新增 >250ms 间隔。该轮使用实际生成的播放器副本。资源回归另外执行真实播放器方法，覆盖 5/10 秒 GOP 删除依赖、30 秒历史边界、原 5 秒追赶与异常上游拒绝。

An offline synthetic long-GOP source reproduced the same problem and the generated player adaptation restored sustained presentation. Asset regressions exercise the actual player method and fail closed for unexpected/already-adapted upstream input. The Windows fixed gate now includes forty seconds of authenticated long-GOP MSE frame progress; a newly built complete candidate must run it before this source change is qualified for distribution.


新固定门禁在 dev.12 运行时加生成 MSE 文件替换的开发组合上通过：42 秒、8 次长 GOP 帧增长/真实呈现检查，随后冷建档、Studio/TAKE、占用栏节点保留、同址编码切换、go2rtc 与整产品重启全部通过，实际 HTML 身份校验 2 次，无额外浏览器权限。回执显式标记 `mediaAssetOverride=true`，不能当作 dev.12 原包或新完整候选通过。此前不完整首帧尝试及私密诊断包装器异常均保留并排除；成功结果同时核验进程退出码、采样次数与完整后续检查。

The complete strengthened local gate passed with the generated MSE file explicitly overlaid on dev.12: eight presented-frame samples over 42 seconds, then all existing import/Monitor/CPU/codec/restart checks and two document hashes. This media override remains development evidence; the new complete candidate is pending. Incomplete first-frame attempts and a private diagnostic-wrapper failure are retained and excluded.


## WHEP 接收缓冲对照（2026-10-19） / WHEP receive-buffer comparison

为进一步区分 WHEP 冻结原因，使用 dev.12 自身前端、同一 DW 流/设备/Program、两个实际可见 Electron 顶层 Monitor 窗口。仅实验侧拦截 `jitterBufferTarget` 设置为 800ms；原侧保留当前自适应策略（本轮活动目标 120ms）。核验活动连接，预热 30 秒后进行 36 次同步采样，共 183.643 秒；两侧始终为 1280×720。该实验有额外延迟，不是 CPU、OBS 或真实摄像机基准。

The same-source/Program comparison used two visible top-level Electron Monitor windows and bundled frontend. Only the experimental receiver target was forced to 800ms; the control kept the existing policy. Active-peer identity, dimensions and viewport were checked. This is a latency experiment, not CPU/OBS or physical-camera qualification.

| 指标 / Measured delta | 原策略 / Existing policy | 固定 800ms / Fixed target |
| --- | --- | --- |
| RTC freezeCount | 31 | 36 |
| RTC totalFreezesDuration | 34.664 s | 43.788 s |
| 本地 RTP packetsLost / Local RTP loss | 0 | 0 |
| 呈现回调 / Presented callbacks | 8617 | 8104 |
| 实际平均 jitter-buffer delay / Measured average | 823.90 ms | 922.40 ms |

**不采用固定 800ms 策略。** 本轮冻结与呈现结果均未改善；设置目标不等于实际平均缓冲时长，本地零丢包也不能排除上游或时间戳因素。此结果不将 MSE 历史修复扩展为 WHEP 修复。此前防嵌入拦截、首页查询参数 404、诊断误读已关闭连接的夹具失败均保留且未计入有效对照；没有关闭 CSP 或修改产品鉴权。

**The fixed target was rejected.** It increased measured buffering and did not improve freezing/presentation in this run. A target is not the measured mean, and zero reported local loss does not rule out upstream/timestamp causes. Earlier framing, root-query and closed-peer fixture failures are retained and excluded; product CSP/authentication stayed intact.


## dev.13 候选与本机公网复验（2026-10-20） / Candidate and external recheck

已核验 `4.1.0-dev.13` / `1728381b2876fe06783b9529ccd89006a6f40ba9` 的 7886 个运行文件，实际 MSE 文件与生成副本逐字节摘要一致。候选 CI 回执为长 GOP 41 秒、8 次呈现采样、2 次实际 HTML 身份检查、无前端替换或额外浏览器权限；完整 Windows 与同提交容器工作流均通过。候选前端入口 SHA-256 为 `30a6ae542e22bfca4cbfccce4487b4e7feba89ce3a50aa96812acce30427135e`。

All 7,886 runtime files and the generated MSE asset were verified. The candidate's own CI receipt records eight long-GOP samples over 41 seconds and two actual document hashes, without override/additional permission. This complements its successful complete Windows/container workflows.

用户指定回放 `eYDDvvGbhp8` 使用候选自身前端与独立账号，冷保存/建档、轨道探测、MSE 启动、Studio/TAKE、实时占用栏节点保留、主页 120 秒、go2rtc 及完整产品重启恢复均通过。23 次增长检查，3311 总帧、69 丢弃、3242 非丢弃帧，平均 26.99fps；仍不是零丢帧或稳定满 30fps。元数据确认当时是 `was_live` 回放，不能称为正在直播。

The exact reported replay passed the bundled candidate through 120 seconds of Monitor playback and both restarts, with 3,242 non-dropped frames (26.99fps average), not zero-drop/full-30fps qualification. Metadata identified a replay rather than a current live broadcast.

**本轮 DW 直播冷导入失败，不计通过。** 元数据确认 `LuKwFajn37U` 当时为公开 `is_live`，但未取得格式；产品冷导入 38 秒后失败。进一步诊断捕获直播 m3u8 下载的 TLS `UNEXPECTED_EOF_WHILE_READING`；普通 YouTube 首页可验证 TLS 并返回 200，`manifest.googlevideo.com` 在本次未配置显式 HTTP 代理的进程环境下，独立 Python TLS、Chrome/Safari 指纹和 TLS 1.2 探测均失败。Al Jazeera 元数据也出现无格式，该默认路径下尚未完成其产品全流程。该问题出现在独立传输探测中，不能直接归因为新 MSE 代码，也不能据此确认究竟是本机路由、网络设备还是远端拒绝；没有关闭证书验证或替换失败回执。

**DW default-route cold import failed and remains unqualified.** It was public/live, but manifest TLS failed before formats were available. Independent verified-TLS probes reproduced the manifest-host failure while the normal YouTube page worked. Al Jazeera metadata also had no formats; its product flow was not locally qualified. These observations do not prove a particular network cause or extend the successful replay result to live sites.

新增只读参考环境复验入口：现有 `release-image.yaml` 的手动 `public_sources` 模式调用固定网站验收，不构建或发布镜像。只能选取本仓库受保护 dev 历史中的成功 Windows 构建，核验不可变 artifact 身份与完整运行文件，再使用候选提交自身的锁定测试器逐条创建临时账号、播放 120 秒并完整重启。仅上传脱敏 JSON，私密配置、截图、日志和媒体均不上传；参考环境结果也不能替代用户笔记本、摄像机或 Android/ARM。

```powershell
gh workflow run release-image.yaml --ref dev -f public_sources=true -f container_candidate=false -f candidate_run=39249967602 -f candidate_version=4.1.0-dev.13
```

The manual reference check consumes an existing successful immutable Windows candidate, uses its own locked harness and fresh per-source accounts, and uploads only redacted receipts. It neither builds nor publishes packages and does not qualify physical hardware or actual Electron performance. Its independent network result must be recorded rather than assuming another runner will succeed.


首轮[独立 Windows 参考复验](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/39287575164)失败，已保留脱敏回执：候选身份、下载摘要、完整运行文件与工具安装通过，普通 YouTube 为 200、清单主机为已验证 TLS 的 404，故未复现本机 TLS 握手失败。但三条来源均未取得格式（直播状态也未取得），分别在冷导入阶段失败，不能认为该参考环境通过或把问题确定为与本机相同。首轮固定标签不足以识别认证/反自动化/挑战失败的细分原因，随后 `689bfe6` 只增加脱敏分类和可用性字段，产品候选不变、断言不放宽；第二轮结果见下，首轮失败不得由随后成功覆盖。

The first independent Windows run failed after successful artifact/runtime checks. TLS worked there, but all three sources lacked formats and failed cold import, unlike the passing local replay. The original bounded tags did not establish a more specific extraction cause. A diagnostic-only code change adds fixed warning categories/availability without changing the candidate or relaxing media assertions; its subsequently completed instrumented recheck is recorded below with the first failure retained.


### 独立参考环境与本机域名路径诊断（2026-10-20） / Independent runner and local host-route diagnosis

[带分类诊断的第二轮 Windows 参考复验](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/39288854910)同样失败。TLS 仍可验证，三条来源的固定警告标签均包含 `authentication`、`bot-check`、`cookies`、`format`，均无视频格式。该结果支持本轮参考网络受到网站登录/反自动化检查限制；没有使用 Cookie、关闭 TLS 验证或放宽成功条件。它不是本机直播清单 TLS EOF 的复现，也不证明所有提取失败具有同一原因。两轮失败均保留。`689bfe6` 的 push/PR 公开 CI 与五类 CodeQL 已通过；公网来源复验失败与这些代码检查分开记录。

The instrumented reference rerun failed with fixed authentication/bot-check/cookie/format labels for all three sources despite working verified TLS. This supports a website access challenge on that runner, separately from the local manifest TLS failure. Both failed runs remain retained; no cookies, TLS bypass or relaxed gates were used. Public CI and all five CodeQL analyses passed for `689bfe6`.

本机另检查域名路径：系统将直播清单主机解析到 `198.18.0.0/15` 虚拟映射地址，而通过 HTTPS DNS 查询取得的公网地址，使用原主机 SNI 和正常 CA 验证可以建立 TLS 1.3。由此确认本轮系统解析/透明网络路径与可验证公网路径的行为不同；不据此判定具体代理软件、网络设备或所有历史故障原因。没有修改系统 DNS、VPN、代理设置、证书信任或产品代码。

The system-resolved manifest route used a virtual mapping address, while an HTTPS-DNS public address completed verified TLS 1.3 using the original hostname/SNI. This isolates a route-dependent difference without identifying a particular proxy/device or explaining every historical failure. Global DNS, VPN/proxy settings, trust stores and product code stayed unchanged.


### 隔离网络下的 dev.13 直播复验 / Dev.13 live recheck on an isolated route

使用临时的已认证回环 HTTP CONNECT 测试服务，仅为本轮子进程将直播清单主机连接到上述已验证公网地址；端到端 TLS、原 SNI/主机名验证保持不变，没有拦截 TLS，也没有修改系统网络。该路径下三条来源均可提取视频格式，DW 和 Al Jazeera 均为公开 `is_live`；元数据可用仅是实际媒体验收的前提。

DW 使用原 dev.13 运行文件、候选自身前端和独立账号，通过冷保存/建档/轨道探测、MSE 启动、Studio/TAKE、实时占用栏保持播放节点、120 秒 Monitor 帧增长、go2rtc 重启不刷新恢复，以及完整产品重启后的配置/设备身份/Program 新帧。两次文档摘要一致，无前端/媒体替换或额外浏览器权限。该媒体门禁使用锁定的 headless Chromium，不是可见 Electron 性能测试。1280×720，23 次增长检查，6324 总帧、842 丢弃（13.31%）、5482 非丢弃帧，平均 45.62fps。通过恢复不等于掉帧/流畅度达标，也不将测试路径通过改写为默认网络恢复。私密材料未提交或上传；成功账号的独立配置按测试器流程清理，诊断回执与日志仅保留本机，DW 本轮测试服务已关闭。

The owned per-process CONNECT fixture changes only the manifest host's connection destination, preserving end-to-end TLS and original SNI/hostname verification. No global network or product changes were made. All three sources yielded video formats, with DW/Al Jazeera live. DW then passed the original bundled dev.13 cold-import, 120-second Monitor, node-preserving CPU readout and both restart gates, with two matching document hashes and no override/additional permissions. The locked headless-Chromium flow recorded 5,482 non-dropped frames at 45.62fps and 13.31% drops; it is neither smoothness nor visible-Electron performance qualification. Default-route failures remain retained separately.


参考复验版本选择还修正了未转义的正则点号：原式会接受 `4x1x0`；新增反例在修复前失败，修复后 6 项来源验收测试、18 项发布策略测试通过，实际 PowerShell/.NET 的合法/非法版本断言与脚本语法解析也通过。这是验收入口校验修复，不改变 dev.13 产品附件。

The reference-workflow version guard now treats dots literally. A regression reproduced acceptance of `4x1x0` before the fix; six qualification tests, eighteen release-policy tests and actual PowerShell/.NET syntax/version checks passed afterward. The original candidate binaries remain unchanged.


随后 Al Jazeera 以另一独立账号、同一原始候选和同样的临时域名路径完成相同全流程：两次文档摘要、冷导入/轨道、Studio/Monitor、实时占用栏、go2rtc 与整产品重启后的新帧均通过。120 秒、23 次增长检查，3609 总帧、36 丢弃、3573 非丢弃帧，平均 29.68fps。测试器和回环 CONNECT 服务正常退出；没有修改已有产品配置或系统网络。其默认路径仅保留此前元数据失败，不声称已有默认网络的完整媒体对照。

Al Jazeera subsequently passed the same full bundled-candidate flow using a separate account and isolated route: 120 seconds, 23 growth checks, 3,573 non-dropped frames at 29.68fps, 36/3,609 drops. Both owned test/proxy processes exited normally without changing existing product data or global networking. Its prior default-route metadata failure remains separate; a default-route full-media comparison was not run.

| 来源 / Source | 本轮路径 / Route | 120 秒非丢弃帧 / Presented | 丢弃 / Drops | 平均呈现 FPS / Mean | 两种重启 / Both restarts |
| --- | --- | ---: | ---: | ---: | --- |
| 指定回放 / Reported replay | 默认 / Default | 3242 | 69/3311（2.08%） | 26.99 | 通过 / Passed |
| DW 直播 / DW live | 进程隔离 / Isolated process | 5482 | 842/6324（13.31%） | 45.62 | 通过 / Passed |
| Al Jazeera 直播 / Al Jazeera live | 进程隔离 / Isolated process | 3573 | 36/3609（1.00%） | 29.68 | 通过 / Passed |

三次是不同时间/来源的短时功能验收，不是同条件性能排名，也不能替代一小时、用户五路摄像机/OBS 或可见 Electron 流畅度测试。固定域名连接地址仅用于本轮诊断，未写入产品配置；没有把隔离路径通过当作产品网络修复。

These are separate short functional runs at different times/sources, not controlled performance rankings or substitutes for hour-long, five-camera/OBS or visible-Electron qualification. The diagnostic destination was never added to product configuration, and isolated-route success is not a product network fix.

# 反馈5：原始五路真实相机验收的未关闭项——详细报告（供开发者审阅）/ Feedback 5: open item in the original five-camera acceptance - detailed report for developer review

日期 / Date：2026-09-20。被测提交 / Reviewed commits：`2c8c7b0`（控制面修复）、`f7f039d`（判定器与验收驱动）。

结论一句话 / One-line summary：**软件链路与验收工具已无剩余缺口；唯一未通过的判据是 back_3 这一路相机的首帧 23945 ms（预算 20000 ms）。这是来源侧问题，需要设备侧决策，本报告不改动任何设备。**

---

## 0. 摘要（给决策者）/ Executive summary

| 项目 | 状态 |
|---|---|
| 受控五路 Direct/Hybrid 1800 秒（合成 720p25） | **12/12 通过** |
| 原始五路 Direct/Hybrid 1800 秒（真实相机） | **8/9 通过** |
| 原始 1920×1080 Composite 1800 秒（真实相机） | **13/13 通过** |
| 真实来源单路故障注入（30 秒断开/恢复） | **通过**（其余四路不受影响） |
| **唯一未通过项** | **back_3 首帧 23945 ms > 20000 ms** |

同一 1800 秒运行中，五路的**帧率**与**停顿**两类门槛全部通过（帧率 0.928–0.999 倍目标；最大停顿 1058–2377 ms；目标 3000 ms），因此缺口是**冷启动速度**，不是持续播放质量。

**English.** The software link and the acceptance tooling have no remaining gap. The only failing criterion is the first frame of one camera (back_3) at 23945 ms against a 20000 ms budget; frame rate and stalls pass on all five in the same run. The report documents the evidence, what is and is not established, and the options that require a device-side decision. No device or configuration was changed.

---

## 1. 验收口径与判据 / Acceptance criteria

- 驱动：`web/tests/local-runtime/browser-soak.spec.ts`（真实产品页面 + Chrome 153 + 产品自身配对流程）。
- 判定器：`tests/soak-verdict.mjs`（纯模块，驱动与派生工具共用）。
- 判据：有效观测 ≥1800 秒、预期来源齐全、每路目标有效、观测完整；**首帧 ≤20000 ms**；**无 >3000 ms 的非预期停顿**（含“最后一帧之后再无帧”的进行中年龄）；**解码帧率 ≥ 目标 90%**；presented 帧率单列报告。
- 首帧的定义：从**安装观察器（点击模式切换之前）**到该路第一帧被呈现，覆盖计划、排队、激活、上游 WHEP 信令、ICE 与播放等待。

**English.** The soak drives the real product page and hands everything to a pure verdict module. A formal result needs 1800 s of complete observation plus first frame <=20 s, no unexpected stall beyond 3 s (including the in-progress age when a frame never returns) and a decoded frame rate of at least 90% of each target. First frame is measured from before the mode switch, so it covers plan, queue, activation, upstream WHEP, ICE and play.

---

## 2. 现象 / The symptom

运行 `tests/artifacts/browser-soak/2026-09-20T13-03-54-051Z-direct`（1800.2 秒有效观测，真实五路，逐路目标按相机标称帧率）：

| 场景来源 | 相机 | 目标 fps | 首帧 ms | 解码 fps | 比值 | 最大停顿 ms | 判定 |
|---|---|---|---|---|---|---|---|
| camera-mu2uub8u | back_3 | 20 | **23945** | 19.96 | 0.998 | 1923 | **首帧 FAIL** |
| camera-mu2uuez4 | front_3 | 20 | 11326 | 19.95 | 0.998 | 1058 | 首帧 PASS |
| camera-mu2ux4qk | hik_ch1_main | 25 | 10832 | 23.21 | 0.928 | 1959 | 首帧 PASS |
| camera-mu2ux73u | overview_c4 | 15 | 18737 | 14.99 | 0.999 | 2377 | 首帧 PASS |
| camera-mu2ux99i | hik_ch2_main | 25 | 12829 | 23.23 | 0.929 | 2013 | 首帧 PASS |

观察 / Observations：
1. 五路首帧落在 **10.8–23.9 秒**，只有 back_3 越过 20 秒线约 4 秒；五路是**并发激活**的（控制面串行化已修复，见 §5），所以这不是排队造成的。
2. 帧率与停顿全部通过：back_3 在**持续拉流**状态下达到 19.96 fps（其标称 20），说明它并非“只能出 10 fps”。
3. overview_c4 首帧 18.7 秒但帧率 0.999，说明首帧慢与帧率不足是两件不完全相同的事，见 §3 的两组测量差异。

**English.** Across the run five first frames landed between 10.8 s and 23.9 s and only back_3 crossed the 20 s line; the five activations are concurrent, so this is not queueing. Frame rate and stalls pass everywhere, and back_3 itself reached 19.96 fps once it was streaming continuously, so it is not a 10 fps camera.

---

## 3. 来源测量（低竞争、单读者、只读）/ Source measurement (low contention, single reader, read-only)

方法 / Method：工具 `build/scratch/real-source-measure.sh`。对每一路**逐路串行**执行，显式 `-rtsp_transport tcp`，20 秒窗口，`ffprobe -count_frames` 统计真实解码帧数，另用 `-show_entries frame=key_frame` 统计关键帧间隔；**只读**，不写入任何设备。

| 相机 | 编码 | 分辨率 | 元数据标称 | 20 秒实收帧数 | 实测 fps | 关键帧间隔 | 解码告警 |
|---|---|---|---|---|---|---|---|
| back_3 | HEVC Main | 2960×1666 | 20 | 201 | **10.05** | 每 60 帧 | `Could not find ref with POC` ×2 |
| front_3 | HEVC Main | 2960×1666 | 20 | 296 | **14.80** | 每 60 帧 | `Could not find ref with POC` ×2 |
| hik_ch1_main | HEVC Main | 2560×1440 | 25 | 500 | 25.00 | 每 50 帧 | POC ×1、`PPS id out of range` ×1 |
| hik_ch2_main | HEVC Main | 2560×1440 | 25 | 500 | 25.00 | 每 50 帧 | POC ×1、`PPS id out of range` ×1 |
| overview_c4 | HEVC Main | 3200×1800 | 15 | 305 | 15.25 | 每 45 帧 | POC ×1 |

要点 / Key points：
- 五路中**三路达到元数据标称帧率**（25.00/25.00/15.25），两路明显不足。
- 两路不足的正是分辨率 2960×1666 那两路，并且都出现 `Could not find ref with POC`（参考帧缺失）。三路健康的里只有零星 1 次同类告警，且出现在抓取起始处，属可预期的会话边缘现象。
- 关键帧间隔按**已收到的帧**计是 45–60 帧；两路弱来源在单位时间内收到的帧更少，这意味着它们的 GOP 在墙钟时间上被拉长。**我们只能观测到接收侧的行为，不能据此判断相机内部的 GOP 配置**（我们没有登录相机）。

**必须说明的测量边界 / Measurement caveat（重要）**：上面的 20 秒窗口是**短时、冷启动、一次性**测量。应用侧**持续拉流**时 back_3 能到 19.96 fps。两次测量的差异可能来自：相机的短时启动行为、每次重新建立 RTSP 会话的代价、探测期间的网络抖动，或相机在不同负载/会话下的自适应。**因此不能**用 10.05 fps 断言“该相机能力只有 10 fps”；能稳健复现的症状是**首帧慢**（§2）与**流最弱**（本节的相对排序）。

**English.** Each camera was probed alone over a 20 s TCP window. Three of five reach their nominal rate; the two 2960x1666 streams do not and are the only ones with repeated missing-reference warnings. Important caveat: this is a short, cold, one-shot probe, while the application's continuous pull showed back_3 at 19.96 fps, so the 10.05 fps figure must not be read as the camera's capability; the robust symptoms are the slow first frame and the relative weakness of that stream.

---

## 4. 已经排除的环节 / Ruled out

| 环节 | 结论 | 证据 |
|---|---|---|
| 验收判定器 | 已修复，不会漏判尾部断流/提前结束/缺流/播放器替换 | `tests/test-soak-verdict.mjs` 20/20（§测试） |
| 控制面串行激活 | 已修复（唯一 io_context 线程 + 全局路由锁） | 受控慢来源下状态查询 >1 s 的采样由 16/102 降为 **0/248**，五路 WHEP 由 10.2–20.4 s 降为健康四路 0.157–0.382 s |
| 网关（MediaMTX 直通） | 不增加损失 | back_3 经直通路由 15 秒窗口 151 帧 ≈ 10.07 fps，与直连 10.05 fps 一致（窗口长度不同，属指示性对照而非严格 A/B） |
| 编码器 slice thread | 已修复，且覆盖真实相机的 Hybrid 链路 | back_3 经真实 `transcode-on-demand.sh`（HEVC→H264）后 WHEP 解码 14.28 fps、`packetsLost=0`、`nackCount=0`（缺陷仍在时只应剩约 60%） |
| 浏览器解码能力 | 不是瓶颈 | 同一浏览器本地文件 720p25 = 25.00 fps、1080p30 = 30.13 fps（`web/tests/local-play-probe.mjs`） |
| 软件链路整体上限 | 受控五路 1800 秒 12/12 通过（解码 25.00 fps ×5、首帧 6.3–6.7 s、最大间隔 ≤133 ms） | 运行 `2026-09-20T13-41-33-419Z-direct` |

**English.** The oracle, the control-plane serialisation, the gateway passthrough, the encoder slice-thread defect, the browser decode capability and the software link as a whole are all excluded by measurement, each with its own evidence path.

---

## 5. 归因与假设 / Attribution and hypotheses

**已确立（有证据）**：缺口位于**相机→网关这一段的上游**。理由：(a) 同一软件/机器/网络下三路达标称；(b) 网关直通不增损失；(c) 首帧在修复串行激活后从 31.7–74.4 秒降到 10.8–23.9 秒，剩余差异与各路来源强弱一致。

**未确立（仅为假设，需设备侧信息确认）**：
1. **上行带宽/链路丢包**：两路弱来源都是 2960×1666，码率需求高于三路 2560×1440/3200×1800 中达标的那几路（尤其 3200×1800 的 overview_c4 也达标，说明“分辨率大”本身不是决定因素，**该路链路质量更值得怀疑**）。`Could not find ref with POC` 与丢包/数据不完整一致。
2. **相机编码器负载**：若相机在满分辨率下编码能力不足，会表现为出帧速率下降与参考帧缺失。
3. **短时启动行为**：冷启动（首次建立 RTSP 会话 + 等待首个 IDR）可能是 23.9 秒首帧的直接来源；对照：健康三路首帧 10.8–18.7 秒，说明冷启动本身就要十秒级，back_3 额外慢了约 5–13 秒。

**未做的测量（供审阅者判断是否需要补）**：相机端编码参数（GOP/码率/CBR-VBR）无法从流内可靠读取；未做低带宽/高丢包链路的分层定位（交换机/AP 端口统计、`ping`/`iperf`、RTSP over UDP 对照）；未在**同一时钟**下对齐“继电器断开时刻”与“首帧呈现时刻”（§7 的故障注入同样受 15 秒采样粒度限制）。

**English.** What is established is that the gap is upstream of the gateway (three streams nominal on the same software, machine and network, the gateway adds no loss, and the control-plane fix already removed the 31.7-74.4 s queueing). What is not established is the mechanism inside the camera or its link: bandwidth/loss, encoder load and cold-start behaviour are hypotheses. Missing measurements are listed for the reviewer.

---

## 6. 可选方案与影响 / Options and impact

| # | 方案 | 预期收益 | 成本/风险 | 需谁决定 |
|---|---|---|---|---|
| A | 提高 back_3（必要时 front_3）的码率上限 | 可能同时改善首帧与帧率余量 | 改相机/NVR 配置；占用更多上行带宽 | 设备负责人 |
| B | 该路改用较低分辨率或子码流 | 降低编码与带宽压力，首帧更快 | 画面细节下降；需确认应用侧取流档位 | 设备负责人 + 产品 |
| C | 排查该路链路（交换机/AP 端口、丢包、抖动、必要时换线/换口） | 直接消除 `POC` 类告警的根因 | 需要现场与网络侧配合 | 网络/现场负责人 |
| D | 转码链路增加缩放（例如缩到 1080p） | 降低浏览器解码与带宽（当前单路 2960×1666 ≈9.2 Mbps，五路约 45 Mbps） | **产品行为变更**（画面细节变化），需明确需求 | 产品负责人 |
| E | 单独为 back_3 放宽首帧预算（如 25 s） | 立即让真实五路验收全绿 | **属于放宽验收门槛**，必须显式记录，不能静默进行 | 需求/验收负责人 |
| F | 维持现状，把该路记录为已知来源限制 | 不改动任何设备 | 原始部署的该项验收保持未关闭 | 已由本报告默认执行 |

推荐顺序：**C → A → B → D**；E 只有在业务上确认「该路冷启动慢可接受」时才考虑，并应与 F 一起在文档中显式声明。

**English.** Six options with benefit, cost and the owner who must decide: link investigation, bitrate ceiling, sub/lower resolution, transcode scaling (a product change), relaxing the budget for that one camera (an explicit threshold change), or accepting and documenting the limit. Suggested order: C, A, B, D; E only if the slow cold start is acceptable in product terms, and then it must be declared together with F.

---

## 7. 复现方法（供审阅者独立验证）/ How to reproduce

```bash
# 1) 来源单读者测量（只读；逐路串行、TCP、20 秒窗口）
bash build/scratch/real-source-measure.sh 20

# 2) 同一输入经网关（直通）与经 HEVC->H264 转码后的对照
bash build/scratch/real-hybrid-e2e.sh

# 3) 1800 秒真实五路 Direct/Hybrid 验收（Direct-only 栈，不并发合成负载）
bash build/scratch/run-direct-only.sh                 # 等待 WEBOBS_DEV_READY
#   然后在 web/ 目录下用 Playwright 驱动（PowerShell 设置环境变量）：
#   $env:WEBOBS_SOAK=1; $env:WEBOBS_SOAK_MODE='direct'; $env:WEBOBS_SOAK_PAIR=1
#   $env:WEBOBS_SOAK_SECONDS=1800; $env:WEBOBS_SOAK_SOURCE_TYPE='real'
#   $env:WEBOBS_SOAK_TARGET_FPS_MAP='{"camera-mu2uub8u":20,"camera-mu2uuez4":20,"camera-mu2ux4qk":25,"camera-mu2ux73u":15,"camera-mu2ux99i":25}'
#   node node_modules/@playwright/test/cli.js test -c .playwright-temp.config.ts --project=chrome -g "feedback-5 soak"

# 4) 判定器回归（无需设备）
node --test tests/test-soak-verdict.mjs
```

说明：`build/scratch/*` 为本地复现工具（未纳入版本库）；`web/.playwright-temp.config.ts` 为本地运行配置（复用已在运行的 Vite）。

**English.** The four commands above reproduce the source measurement, the gateway/transcode comparison, the 1800 s real five-camera acceptance and the oracle regression suite. The `build/scratch` helpers are local-only (not committed); `.playwright-temp.config.ts` reuses an already running Vite server.

---

## 8. 若采纳设备侧改动后的验证要求 / Verification required after any device change

1. 重跑来源单读者测量（`real-source-measure.sh`），确认该路实测帧率接近标称且 `POC` 告警消失或显著减少。
2. 重跑**真实五路 1800 秒**验收（`2c8c7b0` 之后的提交），要求 9/9 通过；若首帧仍超预算，用同一探针确认是冷启动而非持续性能。
3. 若改动影响到 Composite（同一批来源），按顺序重跑**原始 Composite 1800 秒**，确认 13/13 仍通过。
4. 任何门槛调整（方案 E）必须同时更新验收文档与阈值常量，并保留调整前后的原始数据。

**English.** After any device-side change: re-measure the source, re-run the real five-camera 1800 s acceptance expecting 9/9, re-run the composite 1800 s if the same sources are affected, and record any threshold change with its before/after data.

---

## 9. 证据索引 / Evidence index

| 内容 | 位置 |
|---|---|
| 真实五路 1800 秒（8/9，唯一失败为首帧） | `tests/artifacts/browser-soak/2026-09-20T13-03-54-051Z-direct/` |
| 受控五路 1800 秒（12/12） | `tests/artifacts/browser-soak/2026-09-20T13-41-33-419Z-direct/` |
| 原始 Composite 1800 秒（13/13） | `tests/artifacts/browser-soak/2026-09-20T14-16-38-047Z-composite/` |
| Composite 服务端采样 | `tests/artifacts/soak/2026-09-20T14-16-32-052Z-composite-1080p-fixed-f7f039d/` |
| 故障注入（30.0 秒注入，SMOKE_PASS） | `tests/artifacts/browser-soak/2026-09-20T14-52-02-172Z-direct/`；继电器时间戳 `PAUSE-BEGIN 1789916144.366` → `PAUSE-END 1789916174.373` |
| 判定器与回归 | `tests/soak-verdict.mjs`、`tests/test-soak-verdict.mjs`（20 条） |
| 来源与对照工具 | `build/scratch/real-source-measure.sh`、`build/scratch/real-hybrid-e2e.sh`、`build/scratch/rtsp-relay.py` |
| 报告主体 | `docs/feedback-5-acceptance.md`（§0、§4.2.2、§4.3.7、§4.3.8、§4.3.9、§4.3.10、§6.1） |

**English.** All evidence paths are listed above; the main acceptance report is `docs/feedback-5-acceptance.md` and the checkpoint is `docs/feedback-5-progress.md`.

---

## 10. 一句话总结给审阅者 / For the reviewer

请评估三件事：(1) 是否需要先做链路排查（方案 C）再动相机参数；(2) 是否接受“该路冷启动慢”并显式调整预算（方案 E），还是维持未关闭状态（方案 F）；(3) 是否需要产品侧增加转码缩放（方案 D），因为当前单路 2960×1666 ≈9.2 Mbps、五路约 45 Mbps 进入浏览器。**在收到决定之前，代码与环境保持不变。**

**English.** Three questions for the reviewer: whether to investigate the link first, whether to accept and explicitly adjust the budget for that camera or leave the item open, and whether a transcode-scaling product change is wanted (currently about 9.2 Mbps per tile, roughly 45 Mbps for five). Code and environment stay unchanged until a decision is made.

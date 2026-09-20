# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-20（证据复核第 3 轮 / evidence-review round 3）

## 当前代码 / Current code

- 提交 `2c8c7b0`（控制面串行激活修复）之上，本轮未改产品代码：完成**真实来源证据**与**真实五路 1800 秒长稳**。
- 报告新增 4.3.7（真实五路 1800 秒 + 低竞争来源实测 + 经网关/Hybrid 对照），F5-06 行与第 0 节同步更新。

## 本轮完成 / Completed this round

**真实五路 1800 秒验收**（`tests/artifacts/browser-soak/2026-09-20T13-03-54-051Z-direct`，Direct-only 栈，真实产品页面）：**9 项判据 8 项通过**。

| 判据 | 结果 |
|---|---|
| 来源齐全 / 目标 / 采样先于启动 / 模式切换 / 观测完整 / 时长 1800.2 s | PASS |
| 解码帧率（目标 20/20/25/15/25） | **PASS** 0.998 / 0.998 / 0.928 / 0.999 / 0.929 |
| 无 >3 s 非预期停顿 | **PASS** 1058–2377 ms |
| 首帧 ≤20 s | **FAIL** 23945 / 11326 / 10832 / 18737 / 12829 ms |

**低竞争来源实测（只读，TCP，20 s/路）**：hik_ch1 25.00、hik_ch2 25.00、overview_c4 15.25 达标称；back_3 10.05、front_3 14.80 明显不足且伴随 `Could not find ref with POC`。关键帧间隔 2–3 s。

**经网关对照**：back_3 经 MediaMTX 直通 10.07 fps（与直连一致，网关不增损失）；经真实 `transcode-on-demand.sh` HEVC→H264 后 WHEP 解码 14.28 fps、`packetsLost=0`、`nackCount=0` —— 真实相机所走的 Hybrid 链路**确实覆盖** slice-thread 修复；转码保持 2960×1666、单路约 9.2 Mbps。

## 下一条具体动作 / Next concrete steps

1. 受控五路 1800 秒（合成源，软件链路对照）：需要合成 fixture + 临时换 `cameras.db`，测后还原校验。
2. 原始 Composite 1800 秒（`--composite` 栈，逐来源帧龄/重启）。
3. 真实来源单路故障注入（测试代理，其余四路不受影响，恢复 ≤15 s）。
4. 把 back_3/front_3 的来源限制整理成设备参数建议供用户决定（不擅自修改相机配置）。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-02 干净画面 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-03 硬件加速 | 渲染 D3D12 已验证；NVENC 吞吐低于 x264 已回退；NVENC/VA-API 转码分支 slice 行为未验证 | 报告第 2、4.4.2 节 |
| F5-04 本地合成 | 历史 30 分钟按修复后判定器为 INCOMPLETE；修复后 1800 秒待重跑 | 报告 4.2.1、4.3.7 |
| F5-05 音频管理 | 批次 A/B/C 已提交并有单测；音频回归三项全绿；视频位移与客户端侧相对偏移实测通过 | 报告第 5 节 |
| F5-06 播放稳定 | **真实五路 1800 秒 8/9 通过**（帧率与停顿全过，仅 back_3 首帧 23.9 s）；受控 1800 秒与故障注入待执行 | 报告 4.3.7、6.1 |

## 环境与阻塞 / Environment and blockers

- 开发栈以 Direct-only 方式运行（本轮长稳用），Vite 运行中；`cameras.db`/`scene.json`/`studio.json` 均为**用户原始状态**（真实相机），长稳用的是真实来源。
- 收尾需停止开发栈与 Vite，并核对 `cameras.db` sha256 `ac028d59…`、`scene.json` sha256 `87fcca32…`、`studio.json` 5 来源 5 项。

# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-20（证据复核第 6 轮 / evidence-review round 6，本计划执行完毕）

## 当前代码 / Current code

- 提交 `31edefd` 之上：本轮完成**真实来源单路故障注入**（测试代理 30 秒断开/恢复，其余四路不受影响），并补上来源限制的设备侧建议（4.3.10，仅供用户决定，未做任何修改）。
- 计划 §5 的四项验收**全部执行完毕**。

## 本计划四项验收结果 / The four acceptance runs

| 项目 | 结果 | 证据 |
|---|---|---|
| 受控五路 Direct/Hybrid 1800 秒 | **12/12 PASS**（解码 25.00 fps ×5） | `.../2026-09-20T13-41-33-419Z-direct/`（4.3.8） |
| 真实五路 Direct/Hybrid 1800 秒 | **8/9**（帧率 0.928–0.999、停顿 ≤2377 ms 通过；back_3 首帧 23945 ms 未过） | `.../2026-09-20T13-03-54-051Z-direct/`（4.3.7） |
| 原始 Composite 1800 秒 | **13/13 PASS**（解码 30.00 fps、逐输入 healthy） | `.../2026-09-20T14-16-38-047Z-composite/`（4.2.2） |
| 真实来源单路故障注入 | **SMOKE_PASS**，注入 30.0 秒，其余四路增量不变，被注入一路自行恢复 | `.../2026-09-20T14-52-02-172Z-direct/`（4.3.9） |

## 六项状态 / Status

| 项目 | 状态 |
|---|---|
| F5-01 画面填充 | 已实现并自动化验证（22/22） |
| F5-02 干净画面 | 已实现并自动化验证（22/22） |
| F5-03 硬件加速 | 渲染 D3D12 与 OBS 编码已取证；NVENC 吞吐低于 x264 已按实测回退；NVENC/VA-API 转码分支 slice 行为未验证 |
| F5-04 本地合成 | **原始 1920×1080 规格 1800 秒 13/13 PASS** |
| F5-05 音频管理 | 批次 A/B/C 已提交并有单测；音频回归三项全绿；视频位移与客户端侧相对偏移实测通过 |
| F5-06 播放稳定 | 受控 12/12、Composite 13/13、真实 8/9、故障注入通过 |

## 仍未关闭 / Still open（唯一一项）

- **真实五路中的 back_3 首帧 23945 ms**（预算 20000 ms），来源侧冷启动；同一批测量显示 back_3 单读者 10.05 fps 且伴随参考帧丢失，front_3 14.80 fps，其余三路 25.00/25.00/15.25 达标称。设备侧建议见 4.3.10，**需用户确认后才可调整，未擅自修改任何相机/NVR 配置**。

## 环境与数据 / Environment and data

- 开发栈、fixture、测试代理、Vite 全部停止，端口全关；用户数据已还原校验：`cameras.db` sha256 `ac028d59…`、`scene.json` sha256 `87fcca32…`、`studio.json` 5 来源 5 项。
- 复现工具：`tests/test-soak-verdict.mjs`（判定器回归）、`web/tests/whep-rate-probe.mjs`、`web/tests/local-play-probe.mjs`、`build/scratch/real-source-measure.sh`、`build/scratch/real-hybrid-e2e.sh`、`build/scratch/rtsp-relay.py`（故障注入代理）。

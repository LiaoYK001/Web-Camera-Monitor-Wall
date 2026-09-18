# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-19

## 当前代码 / Current code

- HEAD：批次A提交（见 `git log -1`），其上为 `e105deb`（重复增益与首轨静音修复）、`1cf1053`（回归记录）。
- 工作区：批次A已提交；未跟踪文件保持原样。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | monitor-view / wall-controls 规格 |
| F5-02 干净画面 | 已实现并自动化验证 | wall-controls 规格 |
| F5-03 硬件加速 | 分能力探测已实现；OBS NVENC 受 ffnvcodec 缺失阻塞 | 报告 + 启动器日志 |
| F5-04 本地合成 | 端到端已实测（降负载）；启动器 --soak 与阶段错误码已加 | a57bd3b 等 |
| F5-05 音频管理 | 批次A完成；批次B/C 未做 | 本提交 + e105deb |
| F5-06 播放稳定 | 状态机已实现；浏览器30分钟与1080p未验收 | 待 GPU/WSLg |

## 刚完成 / Just completed

- 批次A：`audio_inputs_explicit` 存在性标记（显式空表=无声；缺省=回退首条输入轨）；`audioTrack` 保持输出总线 1–6，前端不再改写；OBS mixer 位按 audioTrack 计算；引擎只在显式非空时建混音路由，无音轨来源视频不受影响。
- 验证：增量构建通过、`webobs-unit-tests` 全绿（含 legacy 与显式空表断言）。

## 下一条命令 / Next

1. `web` 下 `tsc --noEmit` 与 `audio-tracks.spec.ts`（已断言不改写 audioTrack）。
2. 批次B：混音源复用与所有权（先备后切、失败保留旧节目）。
3. 批次C：有符号偏移归一化与音频序号端到端核验。
4. 批次D：`-Soak` 转发、可重复音频回归与采样脚本；Direct/Hybrid 与 Composite 各 30 分钟（需 GPU/WSLg）。

## 局部阻塞 / Blockers

- 原始 1080p 与浏览器 30 分钟验收需要 WSLg/GPU 桌面会话。
- OBS NVENC 需要 ffnvcodec；当前 Composite 用 x264，界面须显示软件编码。

# 目标机 Windows 实机验收运行手册 / Target-machine qualification runbook

状态：**准备工具**。本手册规定如何在目标机（i9-13900HX / RTX 4090 Laptop）上采集可复核证据，本身不构成验收结果；任何“已达成”结论都必须有对应的目标机原始回执与分析输出。合成夹具、GitHub 托管 Windows 运行器或本仓库 CI 通过，都不能替代本手册。

## 目的

在同机、同五路真实 H.265、同画质 / 帧率 / 音轨 / 传输 / 画布 / 显示 / GPU 偏好的条件下，交替采集本产品与固定版本原版 OBS 的进程树 CPU、内存、呈现帧率、GPU 适配器 / 引擎、显存与稳定性，并测量两侧同口径的安装体积。目标见 [OBS 同等开销计划](windows-obs-parity-dsh-plan.md) 与 [执行记录](windows-obs-parity-execution.md)。

## 1. 冻结身份

在**仓库外私密目录**记录下列内容，公开放置时只使用匿名 ID（字母、数字、点、下划线、连字符，≤64 字符）：

| 项 | 记录内容 | 对应元数据 ID |
| --- | --- | --- |
| 机器 | 型号、序列号后四位（私密）、Windows 版本 / build | `machine` / `os` |
| 驱动 | 显卡驱动版本、控制面板 3D 设置 | `driver` |
| 电源 / 散热 | 电源计划、风扇模式、室温、是否外接电源 | `power` / `thermal` |
| 显示 | 分辨率、刷新率、缩放 DPI、显示器数量与连接方式 | `display` |
| 适配器 | 集显 / 独显拓扑、显示器连接的适配器、两程序 GPU 偏好 | `adapter` |
| 画布 | OBS / 产品画布分辨率、FPS、色彩格式与空间 | `canvas` |
| 窗口 | 窗口尺寸、五路布局、是否全屏 | `view` |
| 解码 | 硬件解码设置、缓冲、重连、色彩范围 | `decode` |
| 音频 | 音轨数、采样率、是否静音 | `audio` |
| 扩展 | 两侧禁用的录像 / 推流 / 检测 / 插件 | `extras` |
| 五路输入 | 每路匿名来源 ID + 设置 ID + codec（必须 `h265`） | `inputs[]` |
| 版本 | 产品安装包 SHA-256、OBS 版本与组件清单 | — |

真实摄像机地址、账号、口令、序列号与日志只放私密记录，**不得**进入提交、GitHub Release、附件或公开日志。

## 2. 前置检查

- 两侧都使用**全新安装**：先卸载旧开发版，再安装本次候选；记录安装包 SHA-256。
- 原版 OBS 固定为计划的 32.1.2（与产品内固定 libobs 同版本），只装必需组件；关闭自动更新。
- 同一画布、FPS、色彩格式 / 空间、音轨、五路来源与传输；OBS 侧关闭录像、推流、回放、虚拟摄像头与额外插件；产品侧关闭检测、录像、站点与兼容转码路径。
- 电源计划、GPU 偏好（两程序均设“高性能”）、显示器与 DPI、窗口位置保持一致；一次只运行一侧，另一侧**正常退出**后再开始。
- 先在 OBS 中确认五路画面完整、无黑屏 / 冻结 / 错路；产品侧同样确认。任何异常先按第 7 节记录，不要靠重试掩盖。
- 预热 ≥180 秒，正式采样 ≥1200 秒，采样间隔 5 秒；连续 3 对交替（产品 → OBS → 产品 → OBS → 产品 → OBS），共 6 次采样。

先跑一次目标机预检，确认机器/驱动/显示器/内存与两个候选 EXE 的身份一致（回执永远 `qualified=false`）：

```powershell
python -B native-host/qualification/preflight.py `
  --native-exe 'C:\private-native\bin\64bit\obs64.exe' `
  --obs-exe 'C:\Program Files\obs-studio\bin\64bit\obs64.exe' `
  --metadata 'D:\private-p5\pair01-obs.json' `
  --output 'D:\private-p5\preflight-01'
```

预检要求元数据为 `five-real-h265`、五路 `h265`、七项声明全部确认；至少 16 GiB 内存与 1 个显示器（阈值可调）。回执只证明身份/环境/工具一致，不证明五路画面、硬解、GPU 或性能；`--diagnostic` 只供 CI 用公开占位元数据自检，不能用于目标机验收。
- 长效稳定性：另做一次 ≥2 小时连续运行（可单独记录），期间不隐藏窗口、不改变布局。

## 3. 采集命令

两侧使用同一采集器、同一间隔、同样私密输出目录规则（Git 仓库外、全新绝对目录）。

```powershell
# 每轮先在可信任务管理器中核对根 PID 与完整 EXE 路径。
python -B native-host/qualification/collect.py `
  --pid <根PID> --exe '<完整绝对EXE路径>' `
  --metadata '<私密目录>\pair01-product.json' `
  --output '<私密目录>\pair01-product-raw'
```

- 产品根进程为 `WebOBS.exe`，OBS 侧为 `obs64.exe`；两侧都必须确认五路可见窗口在采样期间保持可见。
- 元数据从 [metadata.example.json](../native-host/qualification/metadata.example.json) 复制后手工核实；`campaignId`、`runId`、`pairId` 唯一，`pairIndex` 从 1 连续，`position` 为 1/2，`variant` 为 `obs`/`product`，`workload=five-real-h265`，五路 `codec=h265`，`declarations` 全部人工确认后才可置 `true`。
- 离线统计（每轮一次，输出到新的私密目录）：

```powershell
python -B native-host/qualification/summarize.py --run '<私密目录>\pair01-product-raw' --output '<私密目录>\pair01-product-summary'
```

采集器与统计器**始终**输出 `qualified=false`、`strictTotal=false`、`coverageIncomplete=true`；CPU 仅为已观察进程树下界，不能单独宣布 OBS 同等开销。GPU、显存、功耗、延迟、硬解与最终画面必须另行测量并记录。

## 4. 同时记录

- 每路呈现帧率与丢帧：产品诊断面板 / OBS 统计窗口，采样开始与结束时各记录一次。
- GPU：适配器名、引擎利用率、显存占用；两侧用同一工具（如 GPU-Z / HWiNFO64 日志），导出私密文件。
- 功耗 / 温度 / 频率：同一工具、同一采样间隔。
- 每轮一张私密截图，证明五路内容与布局；记录任何黑屏 / 冻结 / 重连的时间点。

## 5. 安装体积同口径

产品安装包已在 CI 的 NSIS 安装烟测中写入 `installedTreeFootprint`（逻辑字节、主数据流分配、文件 / 目录数、分配单元）；回执还带 `sizeGroups` 与 `sizeGroupsComplete`：按“相对目录前两级”归因（根目录直接文件记为 `.`，最多 199 组再加 `__other__`，不含文件名或绝对路径），用于定位 Electron、运行时、插件等各占多少。目标机可用同一脚本复测：

```powershell
. .\desktop\tests\installed-tree-footprint.ps1
$scope = New-InstalledTreeFootprintScope -Root 'C:\Private\WebOBS-target' -Purpose isolated-nsis-install-before-first-start
# 运行安装器到该目录后：
Measure-InstalledTreeFootprint -Scope $scope | ConvertTo-Json -Depth 4
```

原版 OBS 用同口径：先卸载、确保目标目录不存在、登记 scope，再全新安装并测量；两侧必须同为“逻辑文件长度 + 主数据流分配”，不得把解包目录、用户数据、页面文件或缓存混入。

## 6. 交接清单

- 6 份 `collect.py` 原始目录（或经确认的哈希）、6 份 `summarize.py` 输出（JSON + txt）。
- 机器 / 驱动 / 电源 / 显示 / 适配器 / 画布 / 解码 / 音频 / 扩展的匿名 ID 与私密明细。
- 两侧安装包 SHA-256、版本、OBS 组件清单、安装体积回执。
- 每路帧率 / 丢帧、GPU / 显存 / 功耗 / 温度记录、每轮截图与异常时间线。
- 五路输入匿名 ID 与设置 ID 的私密对照表。

## 7. 失败处理

出现全黑、冻结、错路、掉帧或重连时：立即停止采样并保留现场，记录精确时间、产品原生诊断快照（`draw_sample` 字段仅作诊断，不代表像素）、五路截图与日志尾部；不要通过反复重启、隐藏窗口、降低分辨率 / 帧率、关闭音轨或启用编码器来“跑过”门槛。失败本身是有效证据，交回后按 P1/P2 继续定位。

## 边界

本手册不授予管理员权限、不下载或安装任何未锁定依赖、不上传或发布数据。OBS 对照必须使用与产品相同的固定版本与来源配置；任何一侧缺失、窗口不可见或设置不一致，该对数据作废并重测。

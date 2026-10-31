# P5 私密进程 CPU / 内存采样原型

这是 [OBS 同等开销计划 P5](../../docs/windows-obs-parity-dsh-plan.md#10-阶段-p5同机性能验收) 的**准备工具**，不是性能验收结果。只按操作者给定的已运行根 PID / **完整且精确的 EXE 路径**，只读采集 Windows 所观察到的后代。不会启动、关闭、暂停、隐藏、截屏或修改 OBS / WebOBS，不读取命令行、环境、摄像机地址、来源配置或用户日志，不下载依赖、不上传或发布任何结果。

**永远输出 `qualified=false`、`strictTotal=false`、`coverageIncomplete=true`。** 轮询无法证明所有短命进程都被观察，也不能发现经未知中间父进程启动或根进程树外的服务。结果是 *observed-tree lower-bound diagnostic*：已观察进程的 CPU 增量下界诊断，不是全部所属进程的严格总量。即使 CPU 比值小于等于 1，也不能宣布 OBS 同等开销目标达成。Windows 实机/API fixture 通过也不证明摄像机、GPU 或性能资格。

## 范围与依赖

Windows x64 使用用户已有的 64 位 Python 3.10+ 与系统 API（`ctypes`，无第三方包、无管理员权限要求）。不提供任意 Python 二进制下载。离线统计与合成算法回归可在 Linux / Windows 使用标准 Python 运行。

[collect.py](collect.py) 使用 Toolhelp parent snapshot、只读查询权限、`GetProcessTimes` 和 `GetProcessMemoryInfo`；[win32.py](win32.py) 不请求终止或写入进程权限。根进程首次核对 `QueryFullProcessImageNameW` 与传入 EXE 的规范大小写/分隔符路径，路径别名不被自动接受。根进程退出会停止采集，绝不重新附着新根进程。

每个已观察后代按 `PID:creationFileTime` 标识并保留句柄，防 PID 重用。已退出后仍从原句柄读最终累计 CPU；若权限或查询失败，记为缺失与不完整，不填零。子进程必须有已观察父身份且出生时间落在父生命周期内；可疑父 PID 重用不被默认为产品进程。未观察到的快速启动/退出和未知中间父进程仍无法补回。保留句柄带来少量内核对象开销，两侧应使用同一工具和采样间隔。

**根进程树外的真正所属服务不在范围内。** 操作者必须检查完整进程归属；`ownedExternalProcesses=null` 是待补指标，不表示没有外部服务。源生成器、采样器及两侧完全相同的外部设施应在产品树外，两侧范围要相同。不要仅为测试而把实际产品服务移出统计范围。

## 私密输出与元数据

所有输出必须是 Git 仓库外、既有私密父目录下的**全新绝对目录**；拒绝既有目录、Git 内的忽略构建目录、符号链接和 Windows reparse ancestors。Windows 创建时采用受保护 DACL，仅当前用户和 SYSTEM 可继承完全控制；Linux 合成/离线输出目录为 `0700`。不覆盖、合并、清空或自动删除结果。

不要选桌面、公共目录、OneDrive/同步目录、网络共享或发布附件目录。工具不负责后续备份/同步软件的泄露风险，仍需操作者保管。原始回执包含 PID、创建时间、EXE **文件名**（不含完整路径）、内存、CPU、时间戳与匿名条件 ID，均应视为私密。不会打印相机、路径、命令行、环境或原始异常消息。

先把 [metadata.example.json](metadata.example.json) 复制到 Git 外的私密目录，手工核实并修改。示例的所有确认项默认 `false`，**不能未经核实改成 `true`**。

- `campaignId`、`runId`、`pairId` 是匿名标识；每轮 `runId` 唯一，每对 `pairId` 唯一；`pairIndex` 从 1 连续，`position` 为 1 / 2，`variant` 是 `obs` / `product`。
- `identities` 保存同条件的匿名 ID，不填路径、URL、口令或自由文本。实际 Windows / 驱动 / 电源 / 散热、屏幕连接与 DPI、适配器、画布 / FPS、窗口尺寸 / 数量 / 可见布局、解码 / 缓冲 / 重连 / 颜色、音轨和扩展状态在**另一份 Git 外私密人工记录**中由 ID 对应，工具不自动发现或验证它们。
- `inputs` 恰好五个有序且不同的匿名来源 ID + 设置 ID + codec；设置 ID 对应每路分辨率、帧率、码率、音频、RTSP 传输及来源配置。真实相机必须 `workload=five-real-h265` 且五路 `codec=h265`。合成短测必须 `workload=fixture`，不能改名当真实相机。
- `declarations` 明确确认五路完整可见、同画质、录像/推流/检测关闭、另一侧已停止、完整归属已人工复查。这些是人工声明，不是自动像素、媒体或生命周期证据。

匿名 ID 只能用字母、数字、点、下划线、连字符，最长 64 字符。两侧 ID 不同则离线配对拒绝；**相同 ID 也不能证明真实设置相同**。真实配置检查和逐路画面/硬解/GPU证据必须另外完成。

## 手工采样

手工正常启动一侧，保持五路真实 H.265、同画布/FPS/音轨/可见窗口/布局与 OBS 原生预览/投影设置；另一侧正常退出，不要同时占摄像机/解码器。自行从可信任务管理器核对根 PID 和完整 EXE 路径；采样器不会搜索或启动产品。默认再预热 180 秒、正式采样 1200 秒、间隔 5 秒。

```powershell
python -B native-host/qualification/collect.py `
  --pid 1234 --exe 'C:\private-native-bundle\bin\64bit\obs64.exe' `
  --metadata 'D:\private-p5\pair01-obs.json' `
  --output 'D:\private-p5\pair01-obs-raw'
```

路径/PID 只是示例，必须替换为已运行且获准测量的目标；不传启动参数给产品。采样器 Ctrl+C 仅停止自己的采样，不停止产品，尽可能保留新目录内的部分原始回执；非正常或根退出回执不可当完整采样。采样器仅读权限不够时记录/失败，不请求管理员授权。

开发者短算法诊断必须另用 `workload=fixture` 元数据，并显式传 `--fixture --warmup 0 --duration 10 --interval 1`。短时或 fixture 回执永远被标为非资格；不要把短测比值写成长期性能结论。普通模式拒绝低于 180 / 1200 秒的请求。

目录中的 [manifest 契约实现](collect.py) 包含根 EXE 在采样开始时的磁盘 SHA-256（不是已加载内存映像的签名/内容证明）、完整/部分状态、计量方法、处理器总数、起止 UTC、时长、原始摘要和重算统计；`samples.jsonl` 保存 warm-up / baseline / measure、单调时间、Windows FILETIME、每样本累计 CPU / working set / private commit、身份、发现/退出/不确定事件和一次顺序采样的跨度；`metadata.json` 仅保存严格允许字段。原始文件只在新的私密目录中创建，SHA-256 证明文件一致性，不提供防人为伪造的签名。

## 至少三对、交替顺序的离线报告

顺序示例：第 1 对 OBS → 产品，第 2 对产品 → OBS，第 3 对 OBS → 产品。每次手工正常结束当前一侧，再启动下一侧。采样时间不能重叠；仍需人工确认另一产品在 warm-up 前已停止。序号元数据必须与采集实际时间顺序一致。每轮同五路有序输入、同所有条件 ID、同采样间隔/逻辑处理器数，且每一侧 EXE SHA-256 在各轮保持一致。

```powershell
python -B native-host/qualification/summarize.py `
  --run 'D:\private-p5\pair01-obs-raw' --run 'D:\private-p5\pair01-product-raw' `
  --run 'D:\private-p5\pair02-product-raw' --run 'D:\private-p5\pair02-obs-raw' `
  --run 'D:\private-p5\pair03-obs-raw' --run 'D:\private-p5\pair03-product-raw' `
  --output 'D:\private-p5\paired-diagnostic-01'
```

[summarize.py](summarize.py) 校验原始文件 SHA-256，重新从累计数值计算统计，拒绝与存储统计不一致的回执，校验输入、设置 ID、至少三对、交替顺序、无重叠、同 EXE 身份等。新输出 `paired-summary.json` 和 `summary.txt` 保留每轮、每对比值及限制；不带输入目录绝对路径，仍属私密，不自动发布。只做 observed-lower-bound 产品 / OBS 比值，不作达标裁决。

## 数值口径与未知项

CPU 相邻区间 = 已观察身份的累计 CPU 增量秒 / 实际单调墙钟间隔秒 / **全处理器组逻辑处理器总数** × 100。首次 baseline 不计成 0% 样本。测量间新生且出生不早于上一边界的进程，首次累计 CPU 纳入；出生更早而晚发现时不把含测量前工作的 lifetime 全塞入区间，而是标为模糊/不完整。已观察已退出身份保留最后累计值，以后增量为零，进程本身不是被删掉后假定零成本。

报告整树区间百分比的算术 mean / median / nearest-rank p95 / peak、timeWeightedMean 及 observedCpuSeconds。不能把各角色/进程的独立 p95 或中位数相加当总值。区间不完全等长时优先审查 timeWeightedMean 和原始样本。顺序 API 读数并非同时发生，`captureSpanSeconds` 与实际间隔暴露时序误差，过大采样跨度/缺口会标记；不捏造置信区间。三对仍不足以自动证明噪声范围内的等价性。

内存给出每样本所有观察到的存活进程 working set 求和与 private bytes 求和的 mean / median / p95 / peak、首尾差、有效/缺失样本数。**Working set 相加会重复计算共享页，private bytes 是私有提交量，不是私有常驻物理内存。** 缺失读数记 `null`，不把缺失进程当零。外部系统合成器/服务转移开销仍须另外核对。

GPU 各适配器 / Video Decode / 3D / Copy、显存、功耗、延迟、最终画面、逐路硬解、温度、频率和树外所属服务全部保持 **`null`，不是 0、未使用或通过**。不读取/相加任务管理器不同设备/引擎 GPU 百分比。本工具不能据此验证同一 GPU、五路帧进度/冻结/黑屏/降帧/音轨，也不能完成 2 小时稳定性、重连、切换、安装/升级/退出清理验收。

## 回归与 Windows 必须验证项

```text
python -B native-host/qualification/test_qualification.py
python -B native-host/qualification/test_windows_api.py
```

[test_qualification.py](test_qualification.py) 使用合成累计数值/假句柄/临时文件验证 PID 重用、退出尾数、首次 baseline、新进程增量、缺失指标、私密目录拒绝、SHA-256 重算、元数据/配对/顺序拒绝等，不证明真实 API 正确。Linux 上 [test_windows_api.py](test_windows_api.py) 明确 skip；Windows 该测试只创建并结束自己的短时 Python fixture，不启动/停止任何产品；四项合约覆盖系统 times/memory/snapshot、保留句柄退出 CPU、读取实际 protected DACL 并只允许当前用户与 SYSTEM，以及短采样结束后 fixture 仍存活/可应答。测试源码存在或 Linux skip 不等于 Windows API 已通过。操作者仍须核实实际目录的后续权限变动、Unicode 路径、PID/路径拒绝、子孙启动/退出、权限不足、采样中根退出、缺失尾数与进程树外服务边界。正式跑之前应在独立 fixture 上复核采样器自身开销；两侧采用同版本/间隔/工具。

本工具不改变默认宿主、服务或产品运行状态；独立原生宿主 CI 另行执行这些纯合成/系统 API 合约，不自动开展 P5 实机测量。本目录不包含摄像机、配置、录制或任何实机测量数据。Windows 全流程和实际用户机器五路同条件 P5 验收仍待执行。

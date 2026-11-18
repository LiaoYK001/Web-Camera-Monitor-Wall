# 给下一位 AI：持续交付 v5.0 完整 Windows WebOBS Wall

> **当前执行入口已更新为[v5.1交接与任务书](V51-NEXT-AGENT-HANDOFF-2026-11-17.md)。** 本页功能要求作历史参考，旧版本目标/PR/认领状态由最新交接替代。

日期：2026-11-16，Asia/Shanghai。执行前先读[当前交接手册](V5-CURRENT-HANDOFF-2026-11-16.md)、实际最新AGENTS和共享账本。

## 1. 可直接作为下一位 Agent 的启动指令

> 从现有项目继续实际开发，尽可能持续完成到 v5.0 Windows x64 完整融合版的构建、验证、集中验收和发布。用户需要至少一版可安装、保留旧数据、可日常使用的完整成品；不要再次以交计划、独立OBS原型、未接线模块、契约测试绿色或生成开发安装器结束任务。
>
> 核对当前代码与统一账本，先协调R1-001现负责人，认领真实范围。直接复用已发布v4.5的原生媒体能力和旧WebOBS已有业务实现；按本任务书W1→W4做实际用户流程。各阶段通过后自行进入下一阶段，不反复问是否继续，不要求用户测试中间开发包。缺少目标机只阻塞最终设备证据，继续完成其余开发与Windows CI。
>
> 交付物必须是一个统一启动入口的完整Windows安装包，并且旧功能有可用入口、所需组件可在同机安装、旧数据可迁移/恢复、更新可用。先完成所有Agent可完成的工作，冻结一版完整候选，通过GitHub Release交付最终集中验收；最终实机通过后按有效授权和版本发布流程正式发布。保留v4.5既有预览，不提前开放稳定feed，不恢复暂停的Android/容器交付。无法完成的部分写具体缺口、已提交WIP与下一条动作，不能用笼统“还需测试”掩盖未实现功能。

本指令来源于用户本次明确要求，承接[原始完整任务书](../windows-webobs-wall-release-plan-2026-11-11.md)。旧任务书中的v4.1版本预期已被“完整版本从v5.0开始”取代，旧分支/SHA只是历史；功能、数据、安全与性能目标仍有效。

## 2. 什么叫本次要交的“完全体”

不是扩展到任意未来功能，而是**当前受支持Windows WebOBS已有功能，在单一OBS原生媒体宿主上形成一个可安装、可升级的产品**。完整范围以24项[功能矩阵](/home/czl/projects/monitor_wall_v5/docs/windows-native-feature-parity.md)和原始任务书为基线，开发中不要无限扩展新需求。

最终可从产品入口实际完成：

1. 安装/升级 → 导入旧账号、设备、场景和偏好 → 登录已有账号 → 原生多路监看。
2. 编辑与保存场景 → Preview独立预看 → TAKE/转场改变真实Program → 多个固定Scene与Program投影。
3. 逐源声音、监听、电平、多轨；设备控制/快照/对讲；录像、推流、NVR、时间线、回放和证据导出。
4. 事件/规则/通知、检测和叠层、go2rtc/网站源、远程Web/PWA/已有Android协议、离线同步与诊断。
5. 托盘/后台持续任务 → 正常退出/崩溃收束 → 备份恢复 → 原生更新检查、校验下载、确认安装、失败回退。

允许复用受认证系统浏览器中的现有管理页面；不要求本轮把所有业务界面改写Qt。页面必须由安装后程序提供可发现入口，组件确实存在、服务可启动、权限一致、流程可用。不能只证明源码有页面，也不能要求用户另备服务器、装Python/Node/OBS或从命令行拼装产品。

## 3. 收敛实现方式，减少无产出的工作

- **沿用一个OBS frontend/Qt宿主和现有控制面。** 普通本地RTSP直接OBS媒体源→场景→原生显示；core保持control-only，禁止为本地监看再启动第二套libobs/转码/浏览器解码。
- **保留现有数据模型与业务实现。** 使用Registry、Secret引用、Scene/Studio schema、现有API和Python服务；先适配现有supervisor/安装器，不另造摄像机目录、账号体系、播放栈或重复的业务服务。
- **管理页优先复用。** 导航进入管理区，不自动再播放一墙媒体；新原生默认入口无Electron常驻，旧Electron路径保留作迁移兼容直至完整等价门槛满足。默认替换须有行为/数据/生命周期/安装证据。
- **每项新增基础设施当轮接入实际产品。** 现有wall_apply等纯函数/执行流可以复用，但不能持续添加“以后接线”的层。没有消费者的抽象、重复模型、外观重做不是当前优先项。
- **功能闭环先行，检查随风险补齐。** 先给一个真实操作路径接线，再用真实服务、媒体、安装验证；不要为简单文案增加测试，也不删除能捕获缺陷的断言。
- **不把同一问题反复从头审计。** 读取已提交证据，修复当前可复现缺口；新业务入口在引入时补执行时认证审计。若任务依赖因未来未实现功能形成循环，先在账本有据拆分现有入口与后续功能验收责任，不能虚报完成或绕过认证。

## 4. 立即接续：先收束正在进行的R1

详见交接手册：当前R1-001 owner=`next-v5-t3-acp-1116-e364e40c`，PR58@8709f3d OPEN，CI43848916218已failure，事件索引p95预算失败，其余9个job通过；完整Windows候选job skipped。

执行顺序：

1. 重新核对owner、branch、PR/check状态；与现负责人交接，不能冒用ID或覆盖共享工作树。
2. 阅读PR58实际diff与残余AUTH/RBAC缺口；在已确认接续/认领后重跑失败job。若稳定失败，确认工作负载、时钟与索引行为并修复真实原因，不提高阈值换绿、不无限重试抽中一次绿色。
3. 保留双模式真实HTTP、排队失效、camera scope与WS注销回归。实际服务保持loopback/Origin/有界请求/私密凭据；新增输出/远端入口仍须执行时复检和撤销收束。
4. 按风险运行同源码实际Windows产品/安装回归，审查后双语合入dev。只有任务实际验收满足才关闭R1-001；剩余旧数据/输出功能由其对应任务承接并继续验收。
5. 立即进入W1。CI等待时继续不冲突的方案核对、下一流程或已有前置测试；不重复构建已发布v4.5。

## 5. 四个成品节点：每个节点都要能从安装包操作

这些节点组织现有R任务，不增加第二套进度账本。小项按原任务认领、留检查点；每个节点完成后自行继续。中间构建默认仅Agent验证，不反复交用户试。

| 节点 | 对应任务 | 必须交出的实际产品能力 | 结束证据 |
| --- | --- | --- | --- |
| **W1 原生完整工作台** | R1-001；R2-001/002/003/004（R2-005已完成） | 现有账号/设备直接进入监看；完整Scene/Preview/Program/TAKE、转场、编辑、声音、固定/Program投影及保存恢复 | 安装后实际操作和动态最终像素/音频；源共享、撤权、冲突、故障恢复；不是JSON成功 |
| **W2 旧业务全部能用** | R3-001/002/003/004 | Qt可发现入口＋复用管理页；设备控制、输出/NVR/回放、事件/检测/网站、远端/离线/诊断；按需服务与完整安装组件 | 每项从产品启动到真实业务结果；权限、后台消费者、安装/离线组件及启用成本 |
| **W3 可替代旧版安装** | R4-001/002 | 旧稳定/支持中开发版及v4.5预览数据导入；备份回退；托盘后台任务；原生updater与覆盖升级 | 隔离Windows真实旧→新、新→后续升级；数据语义/恢复、失败注入、卸载保留 |
| **W4 完整候选冻结交付** | R5-001、R6-001 → R7-001/002 | 完整功能/可选组件清单、两小时长稳、成本报告、可安装最终候选及GitHub下载；最终目标机集中验收后正式发行 | 固定源码/二进制/依赖身份、全部可做自动化通过，最终设备清单明确；正式发布后下载/feed核验 |

### W1：不要让Studio继续停留在控制文档

实际缺口位置：`core/src/obs_scene_runtime.cpp` 的Direct-only `disabled_prepared`、`core/src/studio_controller.cpp::take`、`native-host/src/product_window.cpp` 的Preview与空Program。本轮已经只读复核。

实施必须连接一个可执行链：

`真实会话/权限 + 文档revision/来源身份/相机配置版本 → 有界串行请求 → OBS frontend线程实际应用 → 回读Program/状态 → 提交/确认文档或失败恢复`

- 复用现有受认证loopback控制接口与Qt HTTP客户端；只在现通道上补确有必要的宿主执行适配，明确身份绑定、取消/超时和结果关联，避免引入多套重叠IPC。
- 明确文档提交与运行时执行的顺序及崩溃恢复；拒绝把两进程文件写入说成天然原子。陈旧请求/执行失败不得留下“API说已切、屏幕未切”的成功状态。
- TAKE前后执行时授权；未登录/注销/换人/撤权关闭受保护Preview、Program和投影。未来输出/网站源也在执行与持续使用时受控。
- 保留Scene/Source UUID、裁剪、层级、锁定、嵌套和草稿；不同名称不猜身份，修改Preview不偷偷改变Program。
- 五路基线外保留现有有界1–64快捷布局；完整编辑能力不能因这个子项已完成而省掉。64不是硬件承诺。
- 声音复用OBS混音/输出轨；逐源监听与账号偏好、项目轨道分清，投影默认不叠加声音；非空多轨是真实待做项。
- 用不同动态画面验证Preview切换、TAKE/转场、Program与固定Scene投影分离、共享来源、恢复及撤权；用可辨频率/轨道的实际音频验证静音/监听/输出，不能只验设置JSON。

### W2：在同一台Windows把已有业务接回去

先对比旧 `desktop/src/supervisor.mjs` 与新 `native-host/scripts/product_supervisor.py`、`stage_product_runtime.py`。当前原生stage主要复制camera/cluster；supervisor明确关闭NVR/go2rtc/composite，不能宣称旧业务已自动存在。逐项补依赖、组件清单、入口、受控启动与收尾。

| 功能闭环 | 复用入口/模块 | 必须补齐和验证 |
| --- | --- | --- |
| 设备、ONVIF、PTZ、预置位、快照、对讲 | camera服务与现有设备控制页 | camera scope；松键/断网/注销停动；实际快照/对讲收尾；无硬件项精确列最终待测 |
| 合成录像/推流 | 同一OBS宿主原有编码/输出能力 | 单一输出所有者；无任务无编码；输出状态/错误/轨道/退出保护；正常停机可播放文件 |
| NVR、时间线、归档回放、证据 | nvr/archive现有API和页面 | 原码流录制、计划/配额/多卷、磁盘故障；实际seek/Range/导出hash/权限；不复制第二份本地监看链 |
| 事件、规则、通知与外部集成 | events与现有页面 | 持久outbox、重试预算、MQTT/HA等既有语义；任务与后台消费者；重启/去重/事件录制 |
| 检测、统计/隐私等叠层 | 现有analytics/provider与OBS场景适配 | 本地/录像/远端范围明确；provider按需安装与启动；最终像素验证遮罩/框，不能只显示配置 |
| go2rtc与网站Profile | 原有固定代理、online_source及锁定提取器 | `/api/v1/go2rtc/`＋settings.manage；Cookie私密、凭据剥离；固定relay实播；按需FFmpeg预算 |
| Web/PWA/已有Android连接 | 原有API、远端UI与按需gateway/Caddy | Direct/Composite由原生宿主提供实际媒体；新增远程服务沿既有受控配置显式启用，默认不暴露管理端口；不重发APK |
| 离线、备份、问题中心/诊断 | clients/v2/backup与原页面 | 有限离线授权、冲突不覆盖Program；一致性备份、脱敏支持包；缺组件错误能自助定位 |

为每个服务登记启动者、消费者、默认/按需、健康检查、重启预算、PID/Job归属与退出条件；同PID内线程服务按实际计量。多进程本身不是缺陷，重复拉流/解码/编码和无需求常驻才是需定位的开销。关闭本地窗口不能误停NVR/远程任务，最后消费者结束应释放资源。

可以整合成带组件选择的完整离线NSIS/同Release离线组件附件；组件版本/摘要/安装入口必须锁定、可验证、可回滚。完整功能必须在同机可装可用，不能用“可选”隐藏未完成迁移；离线总量和扩展目录仍要统计。

### W3：把数据和升级做成真实产品流程

- 旧账号/角色/逐相机授权、Registry/Profile/Secret、Scene/Studio/嵌套/声音/偏好、录像索引/原文件引用和可选组件配置全部建立明确映射。v4.5选择/场景也需可导入，不靠重新手填。
- 读取预检→一致性私密备份→新目录转换→语义/loader验证→受控切换→失败回滚。旧数据先保留，不对活跃SQLite/WAL盲复制；用backup API或受控停机验证内容。
- 独立合成旧档案覆盖支持的schema、幂等、磁盘满/不可写/崩溃中断；保留旧安装器与兼容副本。本人档案只在最终验收经授权试迁移，不擅自扫描/覆盖。
- 原生updater保留检查、取消、下载大小/SHA-512/发行身份校验、用户确认安装、正常停机、任务/草稿保护、一致性备份及失败恢复。旧electron-updater测试绿色不代表原生实现存在。
- 实际验证旧稳定→v5、新原生→后续版本两条升级链，可用隔离身份和私密合成feed。默认不install-on-quit；不得污染正式稳定feed/用户安装。
- Windows测试须含Unicode/空格、标准用户、首装/覆盖/重装、默认卸载保留、托盘和后台任务、单实例、宿主/服务故障收束；物理多屏/DPI/音频设备/睡眠唤醒等未具环境项明确留最终验收。

### W4：停止长期只出dev包，冻结一份完整候选

- 功能矩阵每项有入口、安装组件、数据/权限与实际结果。全部可独立完成的R1–R4工作落实，再做完整运行状态的回归；不把缺少用户4090当作开发停点。
- 运行至少两小时Windows合成五路长稳，观察各进程资源趋势、源进度/最终画面、声音、断流、后台任务与故障恢复。较长既有NVR门禁不缩短。
- 同时报告setup下载、logical/allocated、首启新增、核心与完整离线组件总量；与同版本OBS同口径对比，不能把159MB下载与200MB安装直接比较。
- 默认监看不应无需求启动MediaMTX/FFmpeg转码/检测；核对全部所属进程（含树外服务）的CPU、内存和功能增量。采样记录Intel/NVIDIA各自Video Decode、3D、Copy与显存；实际逐路解码证据与“渲染器是NVIDIA/勾了硬解”分开。
- 同等五路H.265/画质/FPS/音轨/延迟/窗口/输出，与固定OBS交替至少三对六轮；每轮预热180秒、采样1200秒、间隔5秒。目标≤OBS继续有效，超标定位优化；诊断下界/合成CI不冒充完整总量或4090实测。
- 没有目标机时先交付**功能完整且自动化通过的最终集中验收候选**及易用产品内采样，不等待一切硬件数值才生成成品。状态写“完整候选，待目标机最终验收”，不得宣称性能已达标或提前升正式稳定。
- 最后只要求用户安装冻结候选、验证本人旧数据、真实五路和日常操作/硬解/性能；发现阻塞缺陷由Agent修复并回归，再给针对性复验。

## 6. 测试与构建执行入口

先检查真实CMakeCache与脚本参数，不盲复制不存在的命令。本机v5树已有`build/core`、`build/native-api`，引用主checkout固定OBS源码/build。下列是现有入口；测试结果必须标明本轮实际执行或引用历史。

```bash
# 在实际代码工作树运行，先按本轮改动重新构建适当目标。
ctest --test-dir build/native-api --output-on-failure
ctest --test-dir build/core --output-on-failure
python3 -B native-host/tests/product_http_runtime.py --binary build/core/webobsd
python3 -B tests/test_cluster_service.py
python3 -B tests/test_event_service.py

# WebUI有变更时：在web目录逐条运行。
pnpm typecheck
pnpm build
# archive / management / support-diagnostics / continuity用各自专用配置。
# focused: pnpm exec playwright test -c playwright.local.config.ts --project=chromium <spec>
```

相关功能使用原有实际服务/代理/网站三类测试，不把支持列表当实播。Windows实际OBS/Qt产品测试在`native-host/tests/product_windows.py`、UI/像素辅助脚本；恢复、安装入口为`desktop/scripts/test-native-product-restore.ps1`与`test-native-product-install.ps1`。完整产品需要扩展这些脚本覆盖新流程，而不是借用旧Electron验收名义。

既有内部Windows流程可用`windows-desktop.yaml`：`native_host=true`、`product_mode=true`、`native_preview=false`、`official=false`、精确`5.0.0-dev.N`与现行工程门禁`v4-M1-dev`。下一个未占用版本从dev.2核对起。内部脚本现有`defaultProduct=false`/`fullFeatureMigrationQualified=false`/publicationForbidden限制是预览/内部产品政策；正式v5需要新增带真实证据的完整发行路径，**不能简单翻转这些常量或重命名dev安装器**。

按变更风险先本机快速回归，再批量跑有意义的同源码Windows集成；复用锁定缓存。已有检查通过后无新代码/新风险不反复全跑。CI失败定位、修复、复验后推进下一功能，不用无休止重复无关测试消耗开发。

## 7. 最终文件、GitHub下载与发布

用户明确偏好GitHub Release下载，Actions Artifacts慢。实现与内部测试继续用CI；**最终完整候选**通过仓库允许的candidate/prerelease路径，版本形如`v5.0.0-rc.N`（先核对策略支持和Tag占用），非Latest、无稳定feed，提供一个可直接下载的完整安装包/完整离线组件、摘要和简明验收说明。若当前策略仅允许内部产物，先实现并审查候选发行路径；不要借v4.5身份或擅自绕过publicationForbidden。

最终实机通过后：

1. 指定v5.0的双语、经审查`dev → main`发布PR；查Tag触发范围，避免误发布暂停平台；正式Tag`v5.0`、程序版本`5.0.0`，不发两个等价正式Tag，不覆盖历史。
2. 明确候选/最终源码及二进制身份；若从main重建，重新验证安装和相关行为，不宣称与RC字节相同。
3. 完整NSIS、SHA-256/SHA-512/size、验证的`latest.yml`、适用blockmap、manifest、依赖锁、SBOM、许可证、产品与匹配第三方对应源码、双语发布说明、升级/回退说明。
4. 原生updater实际消费验证后的元数据；稳定附件就绪再开放稳定feed。默认未签名沿既有决定明确UNSIGNED，不把没有签名当作停止理由。
5. 正式Release后核验Tag/提交/附件摘要/匿名下载/更新检测；不自动给用户安装。v4.5和旧Tag/附件不可覆盖。

本次用户目标是推进完整发布；中途开发/构建/回归不再反复问继续。若最终公开动作因有效规则确需确认，必须先把完整可审阅候选和证据做好，最后一次性提出；不凭版本号推断最终设备已通过或稳定feed已经授权。

## 8. 每轮开发的输出要求

继续维护同一`state.json`，不建新“计划完成率”。每项检查点至少说明：当前源码/工作树、真实产品行为增量、所改文件/接口、实际测试环境与结果、证据、剩余缺口、下一条动作。W1–W4只是组织任务的交付节点，不替代R账本依赖。

每个会话应留下已接入产品的增量或对具体阻塞的实际修复；不能只改计划、报“正在审计”后交接。若确实只剩环境阻塞，保存可接续WIP和最小复现，并推进可独立功能。不要擅自承诺几天完成；至少W1形成后按已完成工作与剩余清单给条件估计，避免用虚构百分比安抚用户。

结束/交接前使用主checkout脚本`check`和相关工作树`git diff --check`；更新功能矩阵/历史证据，释放自己实际认领且需要转交的任务。不要替他人释放任务、覆盖无关修改或把根checkout未提交协作工具夹带进产品PR。

## 9. 完成交付检查清单

- [ ] W1–W3实际安装后流程闭合，旧功能24项有对应入口和安装方式，缺失项未伪称完整。
- [ ] 单一原生媒体所有权；全入口执行时认证/恢复/撤销；Preview/Program/TAKE最终画面与实际音频正确。
- [ ] 旧数据迁移、备份恢复、两条升级链、正常退出/崩溃与后台任务实际验证。
- [ ] 完整候选同源码Windows构建、安装、媒体/业务/故障/长稳通过，用户无需开发环境。
- [ ] 核心/完整体积、全进程资源与功能增量报告真实；真实五路/个人数据/OBS对照集中最终验收，不隐藏未测项。
- [ ] 最终集中验收阻塞修复通过，正式发布包与源码/依赖/许可证/更新元数据一一对应。
- [ ] GitHub可下载完整安装包及资料；正式发行与feed经过有效流程且公开核验完成。

**最后给用户的答复先放完整安装包下载、版本/候选或正式状态、保留功能与升级方法、真实成本和少量最终待验项。不要再以“下一步可以开始产品集成”作为长期开发的交付。**

English: deliver the existing Windows product's supported capabilities through one OBS-native host, installed business services, safe data migration and native updates. Reuse working code and authenticated management pages. Continue across W1–W4 without repeated permission to proceed, qualify the actual installed product, deliver a complete candidate through GitHub Release for concentrated field acceptance, then complete the reviewed v5.0 stable release flow.

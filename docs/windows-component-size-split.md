# Windows 完整候选组件体积拆分 / complete candidate component size split

本文只度量字节：按组件列出安装包与安装树体积，并与同机安装的原版 OBS 32.1.2 安装树按同一工具口径对照。它不说明任何组件已经验收、可用或媒体正确，也不能替代目标机验收。
This document measures bytes only. It never claims a component is qualified, usable or media-correct, and it does not replace target-device acceptance.

## 生成方式 / how it is produced

```
python -B native-host/scripts/component_size_report.py \
  --components build/obs-native-ci/runtime/product-components.json \
  --nsis build/obs-native-ci/native-product-nsis.json \
  --obs-reference native-host/qualification/obs-32.1.2-size-reference.json \
  --markdown
```

Windows 完整候选运行会在上传回执前生成 `build/obs-native-ci/native-product-size-split.json`，随内部回执工件一起保留；上面的脚本对下载下来的回执同样可用。分组规则以固定正则实现，契约测试 `native-host/tests/test_component_size_report.py` 保证分组、边界与拒绝逻辑。
Every complete candidate run writes `native-product-size-split.json` from its own receipts before the sanitized upload; the same script works on downloaded receipts. Grouping is a fixed rule table covered by `native-host/tests/test_component_size_report.py`.

## 当前基线：5.1.0-rc.16 / current baseline

来源 / source: [run 44194328169](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44194328169)，源码 `472f3fe5cddf90f304801aab4dccd4765b0076f2`，安装树在首次启动前测量（`FILE_STANDARD_INFO`/`FILE_ID_INFO`，4096 B 分配单元，硬链接与重解析点拒绝）。这是内部候选，不是正式 v5.1 发布。

| 组件 / component | 文件 / files | 字节 / bytes | 占比 / share |
| --- | ---: | ---: | ---: |
| FFmpeg (libav* / sw*) | 14 | 246,514,688 | 31.08% |
| Embedded Python runtime | 4868 | 172,898,288 | 21.8% |
| Node runtime for services | 1 | 92,825,416 | 11.7% |
| Web UI bundle (PWA) | 34 | 56,653,823 | 7.14% |
| MediaMTX gateway | 1 | 53,876,736 | 6.79% |
| Caddy LAN HTTPS proxy | 1 | 49,535,488 | 6.25% |
| go2rtc (binary + bundled UI) | 190 | 46,970,471 | 5.92% |
| Qt 6 runtime | 6 | 22,898,688 | 2.89% |
| OBS data and assets | 1476 | 12,372,562 | 1.56% |
| Support DLLs (OpenSSL, curl, sqlite, VC++) | 13 | 9,829,384 | 1.24% |
| Other staged files | 43 | 7,781,015 | 0.98% |
| OBS frontend and product plugin | 1 | 5,095,936 | 0.64% |
| Licenses and notices | 266 | 4,821,390 | 0.61% |
| OBS plugin binaries | 18 | 4,006,400 | 0.51% |
| Product control server and online source | 2 | 3,215,872 | 0.41% |
| Qt plugins | 13 | 2,936,320 | 0.37% |
| Python product services | 23 | 861,790 | 0.11% |
| **合计 / total staged** | **6,970** | **793,094,267** | 100% |

- 安装包 / setup: 212,162,215 B · SHA-256 `12039948205f915de180eb0a84f74d0b51ef3fd737a30234851305dbe4242dbd`
- 安装树（首启前）/ installed tree before first start: 794,579,783 logical / 806,620,488 allocation B · 6,972 files / 956 directories
- 相对同机原版 OBS 32.1.2 安装树 / versus stock OBS on the same machine: 165.8% of its logical bytes


## 读数与可拆分项 / reading the split

- **FFmpeg 两份并存**：`bin/av*` 供产品服务/转码，`bin/64bit/av*` 供 OBS 的 `ffmpeg_source`，两者版本线不同（62 与 61 系），合计约 246 MB（31%）。合并为一份需要验证 OBS 与产品两侧使用同一 libav 版本；在此之前不静默删除任一份。
- **内嵌 Python 运行时 172 MB（4868 文件）**：主体是 `python/Lib/site-packages`（numpy、onnxruntime 等）。分析/事件类可选能力可以拆成按需组件；默认监看路径不需要它们常驻。
- **Node 92 MB 单一二进制**：只用于本机服务与 PWA 托管，可评估与系统 Node 复用，但那会改变“自包含安装”契约，需先由用户确认。
- **MediaMTX 54 MB、Caddy 50 MB、go2rtc 47 MB（含上游 UI）**：三者都是按需网关/代理；当前都随包分发但只在启用时启动。按需下载或分卷安装是后续选项，未实现。
- **OBS 侧被裁剪的部分**：`obs-plugins/64bit` 只有约 4 MB（原版 317 MB，主要是 CEF/obs-browser），`data/` 约 12 MB。也就是说产品相对原版的净增主要来自上面的网关、Python 与 Node，而不是 OBS 本体。
- 相对同机原版 OBS 安装树为 **165.8%** 逻辑字节；安装包 212,162,215 B 对原版安装器 157,809,480 B。

Two FFmpeg lineages coexist (product services and OBS's `ffmpeg_source`), the embedded Python runtime is dominated by optional analytics packages, and the three gateways are shipped but only started on demand; OBS itself is trimmed (no CEF/obs-browser). None of these reductions is implemented yet, and none of them may be removed silently before the same-version compatibility check exists.

## 未关闭 / open

- 最终候选（v5.1 待发布版）必须重跑本拆分并替换上面的表格；rc.16 只是当前可用的完整候选回执。
- 逐组件的“按需安装/按需下载”尚未实现：当前安装器仍一次性携带全部组件，因此这里只描述拆分依据，不声称已拆分交付。
- 目标机（用户本机）安装树、录像/缓存目录与更新器缓存不在本度量范围内。

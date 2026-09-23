# Bold Vision 360

本地运行的 360° 视听感知原型：Insta360 X4 Air → CameraSDK / MediaSDK → 本地声音分类与目标检测 → 第一视角 HUD。

**当前 `main` 状态：计划内的 Windows 工程 MVP 源码已集成，可在已配置的本机连接真实相机演示；尚不是完成现场准确率、告警延迟和故障恢复验收的成品。** 240 次独立声音试验与 10 分钟安静负样本目前均未执行，四项数值目标没有合格结论。源码仓库不包含相机 SDK、模型权重和现场素材；新电脑须按下文安装配置。详细的已测/未测清单见 [项目状态](docs/project-status.md) 与 [验收记录](reports/acceptance.md)。

## 在当前电脑运行

双击 **`Start Bold Vision 360.cmd`**，浏览器打开 <http://127.0.0.1:8765>，点击「连接相机」。也可执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1
```

保留启动终端；退出前点击界面「停止」，再在终端按 Ctrl+C。相机只能由一个程序占用，先退出 `CameraSDKDemo` / `RealTimeStitcherSDKTest`。当前连接不需要更换 WinUSB 驱动。

首次启动加载本地模型可能需要数秒；「调试视图」显示实际模型就绪状态。实时、回放、模拟三种模式有明确标记，不会在相机失败时自动播放假画面。

## 已实现

- C++ SDK 采集进程：960×480 ERP、AAC、有限队列、自动重建会话、正常退出释放相机。
- Python 服务：AAC 解码、本机麦克风备用、YAMNet 分类、YOLOv8n ONNX / DirectML 检测、圆周角融合与告警优先级。
- React / Three.js：全屏透视 HUD、边缘光弧、方向标签、最近事件、双栏检测视图、设置和标定面板。
- 本地音视频录制、按原时间关系回放并重新识别、事件导出、240 次现场测试表和统计工具。

实测边界与结果见 [验收报告](reports/acceptance.md)。X4 Air 的强降风噪模式输出 **48kHz 同源双声道**；切换全景声后实测 **48kHz 四声道**。2026-09-23 已完成用户配合的四方位与转动验证，并把门槛收紧为**每个方位误差 ≤22.5°、置信度 ≥0.2**。首轮右、后方约 32–33° 不合格；较清晰人声条件下重采后，当前标定集平均误差 **9.8°**、最大 **16.0°**，独立转动误差 **0.6°**，详见 [方位误差复查](reports/spatial-accuracy-review.md)。这不是完整现场准确率验收。低置信度时仍显示「方向未知」或明确标记的唯一视觉候选；不据此确认发声者身份。

声音显示修复及定位排查见 [声音与 HUD Review](reports/review-audio-hud.md)。已有三份录制的抽样 PCM 两路完全相同；不能把 AAC 的 `stereo` 标签当作独立空间输入。系统现在自动显示声道结构、相关性、差异能量及定位条件，方向未知时仍显示真实波形和三色三棱锥。

用户已确认使用 **相机内置麦克风**，先测试智能降风噪-强，后切换全景声并得到四声道。降噪已纳入 [降噪、分类与定位设计](docs/audio-noise-design.md)：保存原始解码 PCM；定位对所有声道采用相同的 80–4000Hz 带通；可选的 80Hz 低频抑制仅用于分类副本，默认关闭。输入结构随机身模式变化已得到实测，具体处理机制仍未验证。

声音模型和粗方位的实现、支持类别、已有 PCM 回放耗时及开源分发边界见 [本地声音识别与粗方位](docs/audio-model.md)。新增轮胎尖叫/打滑、碰撞/碎裂、车辆经过、犬吠和门铃提示仍需现场带标签样本验证；系统不提供语音转录。

当前完成度、并行分支与剩余模块见 [项目状态](docs/project-status.md)。

## 安装与重建

制作可审核的本地源码 ZIP 及核对第三方许可边界，见[源码包制作与发布边界](docs/release.md)。源码包不包含 SDK、模型权重、素材或本机标定文件。

要求 Windows x64、Python **3.12 x64**、Visual Studio 2022/2026 的「使用 C++ 的桌面开发」及 Windows SDK。首次安装联网，运行不联网。

1. 复制 `config.example.json` 为 `config.local.json`，填写解压后的 CameraSDK 与 MediaSDK 路径。
2. 安装依赖及模型，构建：

```powershell
# 若已具备 C++ 工具链可省略 -InstallCpp；安装工具链会触发 Windows UAC。
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -Python "C:\path\to\python.exe" -InstallCpp
```

3. 修改代码后运行 `scripts/build.ps1`；仅改界面可加 `-WebOnly`。依赖版本锁定在 `requirements.txt` 和 `web/package-lock.json`。

模型来自官方 YAMNet SavedModel 和 Ultralytics YOLOv8n，下载/导出脚本为 `scripts/models.py`；本机 `models/manifest.json` 记录哈希。Ultralytics 模型及相关软件有其自身许可（包括 AGPL/商业许可选项），分发前按官方许可处理；SDK 也不随源码分发。开发用 CPU PyTorch 仅负责 ONNX 导出，运行检测使用 DirectML，无需配置 CUDA。

音频编解码使用 PyAV 携带的 FFmpeg 库，不依赖系统 `ffmpeg.exe`。`scripts/diagnose.ps1` 会打印 FFmpeg 版本、音频设备、相机进程及运行状态。

## 操作说明

- **HUD：** 默认正前方 90° 水平视场；左右按钮每次旋转 45°，「回正」回到佩戴者前方。边缘方向随当前查看方向变化。
- **调试视图：** 左侧全景检测，右侧 HUD；显示 FPS、推理耗时和最近声音分类。推理耗时不是端到端告警延迟。
- **声音波形：** 由实际 PCM 的 20ms 能量包络驱动，保留最近 1.28 秒；方向未知时显示在声音卡片中，有方向证据时显示边缘声纹弧。未识别类别但收到声音时显示「正在分析环境声音」。这不是语音字幕或说话人身份识别；模拟事件没有音频时只显示提示弧，不生成假波形。
- **定位状态：** HUD 左上角可点击查看「双声道同源」「仅视觉候选」或标定状态；调试视图显示声道相关性。标定面板可导出声音诊断 JSON。
- **录制：** 实时模式连接成功后开始；素材保存在 `recordings/<会话>/`，包含 JPEG、浮点 PCM 和 `timeline.jsonl`。录制包含现场画面与声音，用户可自行管理这些本地文件。
- **回放：** 选择本地会话，重新运行识别，结束后显示「回放已结束」。不自动切回实时模式。
- **模拟：** 「回放」面板内进入明确标记的模拟模式，再选择类别与方向；仅验证界面，不参与识别验收。
- **最近事件：** 点击查看证据来源；仅表示系统识别记录，不表示用户漏看。
- **配置：** 停止采集后修改前方偏移、相机机身实际收音模式、备用麦克风；收音模式字段只是记录，不会通过 SDK 修改相机机身设置。
- **降噪：** 设置中分别记录相机内置/外接麦克风、强/弱降风噪等机身模式，软件额外处理默认关闭。实验性 80Hz 低频抑制保留基线分类，诊断可比较两路分数；不代表已验证识别提升。回放使用录制时的设置，旧素材不会被自动标记成当前机身模式。

## 标定与现场测试

本次已由用户在相机正前方伸手，核对物体位于 ERP 水平中央，前方偏移保持 0°。这是前方的粗核对，不能代替八方向测量。

只有实时相机四声道音频可执行声道标定：填写真实收音模式 → 1.5m 处前/右/后/左分别发声 2 秒 → **声源移回最初的正前方并固定**，相机从上往下看顺时针转 90° → 验证此时声源变为左侧。映射不唯一、能量置信度低或转动不通过时，不启用方向。标定页显示逐方位误差与失败原因，原始采样保存在 `runtime/calibration-samples.npz`，匹配相机和收音配置时可在重启后恢复；转动验证结果为 `runtime/calibration.json`，并绑定采样率和定位算法版本。验证后可把相机转回正常朝向。

本仓库的 `reports/field-trials.csv` 已生成 240 个正样本测试行和一个 10 分钟负样本行。源码 ZIP 不含现场报告；从 ZIP 安装时，先运行 `.venv\Scripts\python.exe scripts/evaluate.py --template reports/field-trials.csv` 生成空白表。不要对已有实测表再次运行该命令，否则会覆盖记录。未测行 `observed=0`，不得填成通过。手工记录声音开始和 HUD 首次显示时间（同一外部视频/时钟），填写 `onset_ms` / `hud_ms`。

完整填写与统计口径见 [现场试验说明](docs/field-testing.md)。仅有 240 行并不代表完成；统计会检查每个条件/类别/方位/重复组合、明确的检测结果和负样本误报计数。

```powershell
.venv\Scripts\python.exe scripts/evaluate.py --input reports/field-trials.csv --output reports/field-results.json
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/browser_check.py
# 使用已有录制与明确标记的模拟 UI 检查声音波形/图标，不启动相机；结束后停止回放
.venv\Scripts\python.exe scripts/audio_hud_check.py
# 用隔离的模拟事件量化两种分辨率下 HUD 中央区域遮挡；不替代真实声音验收
.venv\Scripts\python.exe scripts/hud_occlusion_check.py
# 同一录制的基线/低频抑制对比，不作无标注准确率结论
.venv\Scripts\python.exe scripts/audio_ab_check.py --session 20260922-225114 --seconds 10
.venv\Scripts\python.exe scripts/soak.py --seconds 600
# 会切换相机、执行进程故障注入；不要在正式演示中执行
.venv\Scripts\python.exe scripts/lifecycle_check.py
```

未知方向和漏检始终保留在统计总数中；方位误差另附方向覆盖率，延迟另附有效测量数。没有实测时返回 `null`，不生成虚假百分比。

## 结构与接口

| 模块 | 职责 |
|---|---|
| `native/` | 唯一相机拥有者，SDK 解码拼接及 AAC 转发 |
| `server/` | 数据源管理、模型、融合、校准、录制和 API |
| `web/` | HUD、ERP 检测视图和本机控制面板 |
| `scripts/` | 安装、构建、启动、诊断、验收工具 |
| `tests/` | 几何、融合、连续窗口、标定、回放、指标统计测试 |

HTTP API 文档在运行中的 `/docs`。`GET /api/status` 返回实际能力和状态；`POST /api/start` 接受 `live`、`replay`（带 `session`）、`simulation`；`POST /api/stop` 停止。`/ws/frames` 发送 JPEG 二进制，`/ws/events` 每 100ms 发送状态与事件。服务只监听 `127.0.0.1`。

事件方位：前 0°、右 90°、后 180°、左 270°，允许 `angle=null`。优先级 P0 鸣笛/警笛，P1 铃声/喊声/轮胎尖叫或打滑/碰撞或碎裂，P2 普通人声/车辆经过/犬吠/门铃；默认 1.2 秒保持、300ms 圆周平滑、15° 扇区滞回。风险提示不输出未经标定的距离、TTC 或具体说话内容。

## 排障

- **相机无画面：** 检查安卓模式、供电、USB 线和是否被其他 Demo 占用。启动无帧会重建会话两次，详细日志在 `runtime/capture.log`。
- **相机无音频：** 服务尝试直播子模式与音频开关，5 秒无可用音频后启用电脑麦克风；界面显示真实来源。电脑麦克风也不可用时显示错误，不伪造事件。
- **有声音、无方向：** 打开标定面板查看实际输入能力。两声道同源时无法通过声道差推算方向；无唯一视觉候选时保留方向未知。核对机身模式的方法：停止取流 → 机身屏幕顶部下拉 → 音频设置；USB 界面不可操作时先拔线。官方的 360 音频仅承诺全景录制，切换后仍需实测 SDK 输出，不能仅修改网页中的收音模式字段就启用定位。
- **模型加载错误：** 查看调试状态，重新运行 `scripts/models.py`，随后重启服务。
- **低帧率：** 确认独显可用，关闭其他 GPU 负载；必要时在本地配置中设置 `software_decode=true`，重启服务后验证。
- **格式兼容：** 本机 MediaSDK 3.1.7 回调 `format=0`，但实际为 RGBA、stride=3840；代码只在满足单平面布局与 alpha 校验时接受此兼容格式。相机和拼接时间戳实测按毫秒递增，服务根据实际速率识别单位并保留原始值。

# Bold Vision 360

本地运行的 360° 视听感知原型：Insta360 X4 Air → CameraSDK / MediaSDK → 本地声音分类与目标检测 → 第一视角 HUD。

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

实测边界与结果见 [验收报告](reports/acceptance.md)。当前 X4 Air 直播输出 **48kHz、2 声道**，没有启用 Ambisonic 声音方向。声音仍能识别；唯一匹配视觉目标时显示「视觉候选方向」，多人/多车场景显示「方向未知」。这不是对发声者身份的确认。

## 安装与重建

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
- **录制：** 实时模式连接成功后开始；素材保存在 `recordings/<会话>/`，包含 JPEG、浮点 PCM 和 `timeline.jsonl`。录制包含现场画面与声音，用户可自行管理这些本地文件。
- **回放：** 选择本地会话，重新运行识别，结束后显示「回放已结束」。不自动切回实时模式。
- **模拟：** 「回放」面板内进入明确标记的模拟模式，再选择类别与方向；仅验证界面，不参与识别验收。
- **最近事件：** 点击查看证据来源；仅表示系统识别记录，不表示用户漏看。
- **配置：** 停止采集后修改前方偏移、相机机身实际收音模式、备用麦克风；收音模式字段只是记录，不会通过 SDK 修改相机机身设置。

## 标定与现场测试

本次已由用户在相机正前方伸手，核对物体位于 ERP 水平中央，前方偏移保持 0°。这是前方的粗核对，不能代替八方向测量。

只有实时相机四声道音频可执行声道标定：填写真实收音模式 → 1.5m 处前/右/后/左分别发声 2 秒 → 声源留在原正前方，相机向右转 90° → 验证此时声源变为左侧。映射不唯一、能量置信度低或转动不通过时，不启用方向。若固件输出世界坐标音频，首版转动验证会拒绝启用，而不会输出错误头相对角度。

`reports/field-trials.csv` 已生成 240 个正样本测试行和一个 10 分钟负样本行。未测行 `observed=0`，不得填成通过。手工记录声音开始和 HUD 首次显示时间（同一外部视频/时钟），填写 `onset_ms` / `hud_ms`。

```powershell
.venv\Scripts\python.exe scripts/evaluate.py --input reports/field-trials.csv --output reports/field-results.json
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/browser_check.py
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

事件方位：前 0°、右 90°、后 180°、左 270°，允许 `angle=null`。优先级 P0 鸣笛/警笛，P1 铃声/喊声，P2 普通人声；默认 1.2 秒保持、300ms 圆周平滑、15° 扇区滞回。风险提示不输出未经标定的距离、TTC 或具体说话内容。

## 排障

- **相机无画面：** 检查安卓模式、供电、USB 线和是否被其他 Demo 占用。启动无帧会重建会话两次，详细日志在 `runtime/capture.log`。
- **相机无音频：** 服务尝试直播子模式与音频开关，5 秒无可用音频后启用电脑麦克风；界面显示真实来源。电脑麦克风也不可用时显示错误，不伪造事件。
- **模型加载错误：** 查看调试状态，重新运行 `scripts/models.py`，随后重启服务。
- **低帧率：** 确认独显可用，关闭其他 GPU 负载；必要时在本地配置中设置 `software_decode=true`，重启服务后验证。
- **格式兼容：** 本机 MediaSDK 3.1.7 回调 `format=0`，但实际为 RGBA、stride=3840；代码只在满足单平面布局与 alpha 校验时接受此兼容格式。相机和拼接时间戳实测按毫秒递增，服务根据实际速率识别单位并保留原始值。

# 现场试验与统计口径

首版验收表 `reports/field-trials.csv` 预留 **2 种噪声条件 × 3 类声音（鸣笛、警笛、喊声）× 8 个方位 × 5 次 = 240 次**正样本，另有至少 10 分钟安静环境负样本。前、右、后、左分别是 0°、90°、180°、270°，中间方位每隔 45°。此前用于 W/X/Y 声道映射的四方位录音是**标定数据**，不代替这些独立试次，也不用来训练分类器。

现场执行时，用同一个工作表逐次记录；命令每次会从磁盘重读进度，退出后可继续。下面以第 1 次为例，先运行 `next` 查看尚未完成的下一试次，并按其中的噪声条件、声音类别和相对相机的方位布置声源：

```powershell
.venv\Scripts\python.exe scripts/field_trials.py next
.venv\Scripts\python.exe scripts/field_trials.py record --trial 1 --detected 1 --predicted-angle 8 --onset-ms 12500 --hud-ms 13250 --clock-source "同一段外部录像" --notes "距相机 1.5 米；相机固定；智能降风噪-强"
.venv\Scripts\python.exe scripts/field_trials.py next
```

`--predicted-angle` 可省略，表示 HUD 显示类别但方向未知。若漏检，则用 `--detected 0`，不填写 HUD 时间或方向；可以记录外部录像中的声音起始时间：

```powershell
.venv\Scripts\python.exe scripts/field_trials.py record --trial 2 --detected 0 --onset-ms 24000 --notes "未出现对应类别告警"
```

检测到的试次必须填写 `--onset-ms`、`--hud-ms` 以及 `--clock-source`。两个毫秒数必须来自同一个外部时钟或录像；命令会核查数值与顺序，但不能替代人工核对声源和 HUD 画面。录入后不可直接覆盖已观测的试次，若人工录错，请保留原始证据并审查 CSV 后更正。工具会拒绝重复试次、非法角度、缺失时间、倒序时间和重复的负样本段；写入采用原子替换，中断后原表仍可读取。工作表的 240 次试验配置和试次 ID 不允许改动。

安静负样本按真实时长分段记录。预留行的 ID 是 `negative-10min`；若另做一段，用唯一的 `negative-session-2` 等 ID（仅 ASCII 无空格），并明确写出误报数，零次也要写 `0`：

```powershell
.venv\Scripts\python.exe scripts/field_trials.py negative --session-id negative-10min --minutes 10 --false-positives 0 --notes "安静室内；相机内置麦克风；记录时间 14:00–14:10"
```

每次实际完成后才把 `observed` 改为 `1`；`detected` 必须明确填 `1` 或 `0`。若检测到了类别但方向未知，`detected=1`、`predicted_angle_deg` 留空；漏检则 `detected=0`。记录检测到的事件时，`onset_ms` 与 `hud_ms` 使用**同一外部时钟或录像**读取声音开始和 HUD 首次可见时间；不以服务端模型耗时冒充从发声到显示的延迟。若检测结果或时间没有记录，统计仍把该试次保留在分母中，并标明记录不完整。

负样本行须同时填写实际 `negative_minutes` 和 `false_positive_count`；若没有误报，明确填 `0`，留空不会被当成零。两种噪声条件的声音强度、播放器与相机距离、收音模式、相机朝向及其他环境变化应写在 `notes` 中。按原计划，需在安静环境与交通噪声条件各完成 120 次。

```powershell
.venv\Scripts\python.exe scripts/evaluate.py --input reports/field-trials.csv --output reports/field-results.json
```

统计输出保留漏检、未知方向、无延迟记录、重复/缺失试次和负样本漏填数量。`status=complete_measurements` 只说明矩阵和必要记录完整，**不表示召回率、方位误差、误报率或 P95 延迟达标**。方位误差与 HUD 延迟仅能在有有效测量值的试次上计算，输出同时给出覆盖率和样本数；漏检始终计入召回率分母，未知方向始终计入方向覆盖率分母。最终结论须连同这些分母以及失败样本一起报告。

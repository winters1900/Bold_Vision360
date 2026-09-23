# 离线音频延迟诊断

`scripts/audio_latency_check.py` 直接读取一段现有录制的 PCM，按录制文件中的相对时间间隔送入相同的 `Runtime.audio_worker`，经声音模型和融合模块生成事件，并通过项目实际的 `/ws/events` 路由在本地测试 WebSocket 接收。它在单独进程内运行，不连接现有 8765 服务、不请求 `/api/start` 或 `/api/stop`，也不启动相机采集或另一个 HTTP 服务。录制素材只读；诊断 JSON 默认写在 `reports/local-audio-latency.json`。

在项目根目录运行：

```powershell
.venv\Scripts\python.exe scripts/audio_latency_check.py --session 20260923-114933-8c69 --seconds 10
```

如在独立工作树运行，使用 `--recordings-root` 和 `--model` 指定主工作树中已有的素材及预训练模型。报告包含实际使用的分类阈值：优先采用录制元数据中的阈值，旧录制缺失的类别使用当前默认值；音频预处理和声道标定则从录制元数据读取。这使旧素材复测不随日后的本机阈值修改而悄悄改变。模型不训练，原始 PCM 不修改。

报告中的三个时间段都以同一台主机的单调时钟测量：

| 字段 | 含义 |
| --- | --- |
| `model_inference_p95_ms` | 每次预训练模型 `infer` 调用的耗时；若启用本地滤波，会分别计入原始和滤波后两次调用。 |
| `alerting_classification_call_p95_ms` | **产生事件的那些窗口**的分类调用耗时，还含线程调度及可选第二次模型调用。 |
| `audio_timestamp_to_event_p95_ms` | 回放时**最后一个参与该次事件更新的解码 PCM 块时间戳**到服务端事件生成的代理链路耗时。 |
| `audio_timestamp_to_websocket_receipt_p95_ms` | 同一个 PCM 块时间戳到本地 `/ws/events` 客户端拿到对应事件版本的代理链路耗时。 |
| `event_to_websocket_receipt_p95_ms` | 服务端事件生成到本地 WebSocket 客户端收到的耗时。 |
| `replay_feed_lag_p95_ms` | 离线调度实际入队时间晚于目标录制时间的程度，可用于发现测量时机器过载。 |

WebSocket 每 100 ms 发送快照，可能略过两次快照之间产生又被更新的事件版本；`event_updates_generated`、`event_updates_received_by_websocket` 和 `websocket_update_coverage` 必须一起看。没有事件或没有对应 WebSocket 收件时，P95 为 `null`，不把缺测当成零。报告使用录制片段，不提供声音类别准确率或方位准确率。

**这些数值不是“真实声源开始到 HUD 显示”的端到端延迟。**录制的块时间戳不是外部声音起点；探针没有测相机实际采集延迟、视频同步、浏览器 WebSocket 到达后的绘制或屏幕可见时间。YAMNet 约 0.96 秒分析窗及告警去抖也无法从“最后 PCM 块→事件”数值中体现。实施方案的 P95 ≤900 ms 目标必须用同一外部时钟或录像标注真实声音开始与 HUD 首次可见时刻，按 `docs/field-testing.md` 完成现场试验后才能验收。

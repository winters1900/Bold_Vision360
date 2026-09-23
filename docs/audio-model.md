# 本地声音识别与粗方位

首版使用 Google 公开发布的预训练 YAMNet SavedModel。它接受 16 kHz 单声道音频，输出 AudioSet 的 521 个声音类别；本项目把其中明确的标签汇总为 12 种 HUD 提示。运行时仅加载一个声音模型，对约 0.96 秒滚动窗口每约 100 ms 推理一次，不训练、不访问云端。模型由 `scripts/models.py` 在首次安装时下载，权重、相机 SDK 和录制素材均不提交仓库。模型来源和文件哈希保存在本机 `models/manifest.json`。

| HUD 提示 | AudioSet 标签 | 优先级 |
|---|---|---|
| 汽车鸣笛 | Vehicle horn / Air horn | P0 |
| 警笛 | Siren 及各类应急车辆警笛 | P0 |
| 疑似爆炸声、疑似枪声 | Explosion；Gunshot, gunfire（分为两类，不混同） | P0 |
| 自行车铃、喊声 | Bicycle bell / Shout / Yell / Screaming | P1 |
| 轮胎尖叫/打滑声 | Tire squeal / Skidding | P1 |
| 碰撞/碎裂声 | Smash, crash / Breaking / Shatter | P1 |
| 人声、车辆经过、犬吠、门铃 | Speech / Conversation、Car passing by、Bark / Bow-wow、Doorbell / Ding-dong | P2 |

鸣笛、警笛和犬吠原本就接入了同一个预训练模型；之前的实测素材主要是人声，不能据此断言模型“只能识别人声”。这次直接接入 YAMNet 已有的 `Explosion`（420）与 `Gunshot, gunfire`（421），不增加第二个模型。`Boom`、`Fireworks` 与 `Firecracker` 没有合并成“爆炸”；[AudioSet 类别定义](https://research.google.com/audioset/ontology/explosion_1.html)也把这些标签区分开。HUD 的“疑似”只表示声学分类，不确认真实爆炸、枪击或事故。

`轮胎尖叫/打滑声`和`碰撞/碎裂声`也只是声学类别提示，**不判断事故是否发生**；`人声`不转录或判断具体话语。类别分数不是经校准的概率。初始阈值写在 `config.example.json`，现有本地配置会自动补齐新类别阈值。当前鸣笛、警笛、犬吠阈值分别为 0.35、0.35、0.6，新爆炸/枪声候选初始阈值均为 0.5；所有阈值及连续两个推理窗口超阈值的去抖均未按独立危险声样本校准。短促爆炸/枪声可能在 0.96 秒窗口与去抖下漏检或延迟，只有现场带标签正、负样本足够时才据此调整。新增类别的召回率和误报率目前未验收。

可选对照模型包括预训练 [PANNs/Cnn14](https://github.com/qiuqiangkong/audioset_tagging_cnn/blob/master/README.md) 与 [AST](https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593)。它们需要另一套推理链和本机性能/延迟验证；在没有危险声实测集之前，不能仅凭公开数据集分数认定替换模型会改善本项目。当前先保留单个 YAMNet，以录制的独立鸣笛、警笛、犬吠、爆炸/枪声候选及负样本检查每类分数、漏检与误报。YAMNet、PANNs 的类别表不同，未来更换模型必须重新映射类别。

粗方位并非 YAMNet 的输出。相机处于经过四方位及转动验证的四声道全景声配置时，独立计算 W/X/Y 声道间的强度矢量；低置信度、标定失配、单/双声道输入时不提供确定音频方位。机身强降风噪会改变输出结构，须重新诊断，不沿用全景声标定。唯一且时间、类别匹配的视觉目标可提供标明来源的候选方向。`runtime/calibration.json` 和 `runtime/calibration-samples.npz` 保存的前、右、后、左及转动采样只用于空间声道映射和复查，**没有逐类声音事件及起止时间标注**，不能直接用于声音分类模型微调。

四声道强度矢量只描述当前混合声场，无法同时给不同声源各自定位。因此当同一推理窗口跨阈值的类别属于不同声音类型时，类别告警照常保留，但不把同一声学角度复制给每一类；HUD 会说明“同时识别多类声音 · 方位无法归属”。`人声`与`喊声`可能是模型对同一声源的重叠标签，按同一类型处理。若有唯一匹配的视觉目标，仍可显示标明来源的视觉候选方向。这是保守的归属限制，不能证明剩下单一类别时一定只有一个真实声源。

本机用两段此前录制的 10 秒真实相机四声道 PCM 回放测试：各 85 次推理，模型推理 P95 分别为 7.57 ms 和 6.50 ms。右侧较清晰人声录制中，85 个窗口有 21 个超过当前人声阈值，新增五类均没有超过阈值；后方录制仅 1 个人声窗口超过阈值，提示真实场景下仍可能漏检。窗口数不等于独立事件数，也不能据此计算召回率；0.96 秒分析窗口和去抖还会增加从发声到 HUD 的总延迟，**900 ms 端到端目标未验收**。可复现命令：

```powershell
.venv\Scripts\python.exe scripts/audio_model_check.py --session 20260923-114933-8c69 --seconds 10
.venv\Scripts\python.exe scripts/audio_model_check.py --session 20260923-115447-afd2 --seconds 10 --output reports/local-audio-model-check-rear.json
```

YAMNet 的[官方模型说明](https://www.kaggle.com/models/google/yamnet/TensorFlow2/yamnet)介绍了输入、类别和未经校准的分数；[TensorFlow Models 源代码](https://github.com/tensorflow/models/tree/master/research/audioset/yamnet)采用 Apache 2.0。若公开分发模型权重，需要单独核对其发布页许可；本仓库默认只提供下载脚本。相机 SDK 和 YOLOv8n 权重也分别受原厂许可约束，不与本项目源码一并发布。

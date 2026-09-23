# 源码包制作与发布边界

`scripts/release.py` 从指定的 **Git 提交快照**生成本地源码 ZIP，不读取工作区当前文件内容。脚本只收根目录启动/依赖配置，以及 `server/`、`native/`、`web/`、`scripts/`、`tests/`、`docs/` 中白名单扩展名的文件。它明确不收 SDK、模型权重、录制、运行状态、本机配置、报告、测试截图、设计图片、Office/PDF 原件、依赖安装目录、构建产物和工作树。新目录或文件类型默认不进入包；新增必要文件时须审核白名单和测试。

在准备公开的提交上运行：

```powershell
.venv\Scripts\python.exe scripts/release.py
.venv\Scripts\python.exe scripts/release.py --verify dist\bold-vision360-source-<提交短哈希>.zip
```

输出为 `dist/bold-vision360-source-<提交短哈希>.zip` 和同名 `.manifest.json`。ZIP 内另含 `SOURCE-MANIFEST.json`，记录完整提交哈希、每个文件的字节数及 SHA-256。`--verify` 检查包内文件集合、哈希及外部清单一致性。ZIP 内容顺序和时间戳固定，相同提交与代码版本应生成同样的字节。发布前可先查看清单、解压检查内容；生成包本身不会上传、推送或发布。

首次在另一台 Windows x64 机器安装，需要 Python 3.12 x64、Visual Studio C++/Windows SDK、可联网的 Python/npm 依赖源，并自行取得与相机匹配的 CameraSDK、MediaSDK。复制 `config.example.json` 为 `config.local.json` 并填写 SDK 路径，再运行 `scripts/setup.ps1`。安装脚本会下载 Node、Python 依赖和预训练模型并构建原生/网页代码；日常识别在本机运行。具体命令与相机设置见 [README](../README.md)。源码包不含可运行二进制，也不含现场录制或标定文件，因此在另一台机器上须重新标定声音方位。

**许可尚需项目所有者决策。** 当前仓库未设置项目根 `LICENSE`；本工具不代选许可证，也不代表源码已获得公开再许可授权。决定发布前，应确认团队成员、设计素材及引用文档的权利归属，并确定项目许可证。相机 SDK 须按影石提供的条款单独获取，不能随此源码包分发。[YAMNet 源码所在仓库](https://github.com/tensorflow/models/blob/master/LICENSE)采用 Apache-2.0，但下载的模型权重仍应核对其发布页条款。[Ultralytics 对 YOLO 代码和模型的许可说明](https://docs.ultralytics.com/help/contributing/#what-does-the-agpl-30-license-mean-if-i-use-ultralytics-yolo-in-my-own-project)列有 AGPL-3.0 与企业授权路径；选择整套项目的许可和分发方式前，应处理这项依赖的影响。Python/npm 依赖在首次安装时由各自来源获取，若以后打包这些依赖的二进制，也需另核对对应许可和声明。

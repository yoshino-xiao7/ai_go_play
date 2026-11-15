# 发布准备与模型分发

目标是让新用户在没有作者本机配置、缓存和运行环境的电脑上完成安装，并运行所选功能。基础画布无需模型；图像、视频、语音、口型和后期处理分别安装。教程录制应在干净环境验收通过之后开始。

[文档中心](../docs/README.md) · [分支治理](../docs/GOVERNANCE.md) · [版本发布流程](../docs/RELEASING.md) · [发布就绪记录](release-approval.json)

## 当前状态

2026-11-15：所有者确认 v0.1.0 并要求进入发版流程。[本轮候选验收](V0.1.0-ACCEPTANCE.md)记录新增的干净安装、保存退出、备份恢复与回归结果，供 dev → integration 审查。下面的历史快照仍保留原始范围；发布是否完成以 GitHub Release 为准。

本节是 2026-11-14 的发布准备快照，**不是发布批准**。当前版本未发布；正式候选还须遵守 integration → main 审查和 GitHub Releases 流程。历史测试数量只适用于对应记录，不代表后续代码自动通过。

| 范围 | 结果与依据 | 尚未完成 |
| --- | --- | --- |
| 首次启动 | [Web 向导](首次启动架构.md)、[初次验收](setup-validation.json)、[中文路径空环境复查](new-user-validation.json) | 另一台真实电脑完整验收 |
| 语音与口型 | [独立环境安装](语音与口型从零安装.md)、[空缓存推理记录](local-ai-validation.json) | 跨机器兼容性验证 |
| 实际生成 | [28 项本机生成验收](GENERATION-VALIDATION.md)，包括 18 段视频播放与跳转 | 最终发布候选按受影响范围复测 |
| 保存与退出 | [退出功能验收](EXIT-VALIDATION.md)，保存失败和活动任务会阻止退出 | 实际 Release 下载包复测 |
| 模型清单 | 48 个去重文件，本地共 186,797,079,987 字节，约 173.97 GiB；含权重、配置、tokenizer 和清单 | 不覆盖任意用户导入模型 |
| 夸克分发 | 48/48 名称与大小匹配；[25 个实际下载文件 SHA-256 一致](QUARK-DOWNLOAD-VALIDATION.md) | 其余 23 个未回下载，按用户决定不再继续；不能写成云端全量哈希通过 |
| 来源与许可 | [逐文件来源](model-sources.json)、[许可复核](MODEL-LICENSES.md)；w2v-bert、CAMPPlus 依据已补齐 | 指定权重授权适用范围、原始声明等剩余材料，见许可复核记录 |
| 仓库治理 | [规则、检查及启用记录](../docs/REPOSITORY-SETUP.md) | 默认分支工作流接入及受套餐限制的服务器保护 |

网盘根目录提供 [模型下载与安装说明](模型下载与安装说明.txt)、[模型清单](models.json)、[校验值](model-checksums.sha256)和 [verify_models.py](verify_models.py)。下载后优先用 Web 向导导入；手动检查将四份文件放在同一目录，运行 `python verify_models.py --models-root "C:/AI/models"`，也可加 `--pack 01-qwen-image`。下载来源为 [百度网盘](https://pan.baidu.com/s/5nO-pzE6K3be3-t0zkpm1Pw)（无需提取码）或 [夸克网盘](https://pan.quark.cn/s/2ce0688209ca)（提取码 `BsXE`），模型目录一致。百度镜像核对范围见 [镜像验收记录](BAIDU-MIRROR-VALIDATION.md)。

2026-11-13 已将 14 个已有文件归类、34 个缺失文件补传；21:52（北京时间）核对名称和大小。操作记录保存在本机 `.qa/release-audit/`，不纳入公开包。全部本地文件已计算 SHA-256，云端完整性范围以下载核对记录为准。

## 模型目录

[models.json](models.json) 列出了准确文件名、相对安装路径、所属功能包和代码依据。路径相对于统一模型目录。内置图像工作流和 Turbo 使用固定文件名；标准 H3 支持其他兼容权重，这份清单选择本机现有的 INT8 组合，安装后需在 H3 设置中选择对应文件。

| 包目录 | 功能 | 文件数 | 本地容量 GiB |
| --- | --- | ---: | ---: |
| 01-qwen-image | Qwen Image 2.1 文生图、参考图、编辑 | 3 | 16.10 |
| 02-h3-image | H3 图像及提示词增强 | 4 | 52.74 |
| 03-h3-video | H3 标准视频与音色设计 | 5 | 92.20 |
| 04-h3-turbo | H3 Turbo 视频 | 5 | 60.50 |
| 05-indextts | IndexTTS 2.5 及声音特征模型 | 16 | 6.60 |
| 06-indextts-emotion | 可选的文本情绪模型及 tokenizer | 11 | 1.13 |
| 07-latentsync | LatentSync 1.5、Whisper、VAE、人脸检测 | 5 | 5.11 |
| 08-video-enhance | RIFE 4.26、Anime6B、Remacri | 3 | 0.10 |

表中各功能包包含共享依赖，容量不能直接相加。补传计划将共享文件只列一次，并保留全部引用它的功能包。下载说明需明确共享文件的位置。

建议夸克按 `包目录/models/原相对路径` 分类，例如 `01-qwen-image/models/diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors`。下载后合并到同一个模型根目录，不要改变权重文件名。

本清单不覆盖用户自行导入的工作流、其他模型变体或模型库里的全部 LoRA。扩展包应另列依赖；不要把下载缓存、`.partial`、`.incomplete`、`.parts` 分片和私有创作素材混入发布包。

## 盘点和夸克差异核对

工具仅读取模型并写出报告，不上传、移动或删除权重。使用任意 Python 3.12 即可，不依赖画布或 GPU 环境。

```powershell
python scripts/audit_release_models.py --models-root "F:/bilitv/ai_models" --output .qa/release-audit
```

把路径替换为实际模型根目录。报告 `model-audit.json` 按文件记录本地状态；`upload-plan.json` 给出按模型分类的补传来源及目标。未提供云盘清单时，云端标为 `unknown`，补传计划为空，不能据此认为无需补传。

夸克清单格式为 JSON，路径应去掉分享根目录和功能包前缀，统一为模型根目录下的路径：

```json
{"files": [{"path": "diffusion_models/example.safetensors", "size": 123}]}
```

`size` 必须是字节数。可提供 `sha256`。同名文件大小相同只标为 `same_size_unverified`；只有双方 SHA256 一致才标为 `verified_sha256`。

```powershell
python scripts/audit_release_models.py --models-root "F:/bilitv/ai_models" --remote-inventory .qa/quark-models.json --output .qa/release-audit
# 最终发布前完整读取所有文件并计算校验值，约需读取 174 GiB。
python scripts/audit_release_models.py --models-root "F:/bilitv/ai_models" --remote-inventory .qa/quark-models.json --sha256 --output .qa/release-audit
```

报告中的本机绝对路径只用于本地补传；`.qa/` 已被 Git 忽略。上传模型后重新获取云端清单核对，不能把本地补传计划当成上传成功记录。

## 环境与安装缺口

| 组件 | 已确认依赖 | 发布前还需完成 |
| --- | --- | --- |
| 基础画布 | Python 3.12+、前端构建、媒体功能所需的 FFmpeg/FFprobe | 本机干净源码副本与全新虚拟环境已通过；仍需另一台电脑验收 |
| 前端 | Vite 要求 Node 20.19+ 的 20.x 或 Node 22.12+ | 安装文档已同步具体版本 |
| Qwen Image | `TextEncodeQwenImage21GH`，来自 Goohaitools-comfyui | 固定源码、清单模型下三种入口实际生成通过；仍需另一台电脑验收 |
| H3 图像 | ComfyUI H3 图像节点、提示词增强节点、4 个指定模型 | 文生图、参考生图和编辑实际生成通过；仍需另一台电脑验收 |
| H3 视频 | ComfyUI H3 节点、Director 扩展；Turbo 还需对应扩展及 LoRA | 原生、Director、Turbo、定帧引导及原生/Turbo 默认 4 秒配置通过；仍需另一台电脑验收 |
| IndexTTS | 独立 Python 3.11、固定上游源码、锁定依赖、模型清单、Manju 语音桥接 | 一键安装及同机空缓存推理通过；仍需另一台电脑验证 |
| 文本情绪 | `qwen0.6bemo4-merge` 目录 | 从夸克 06 包合并到模型目录，安装器完整校验；空缓存实际生成通过 |
| LatentSync | 独立 Python 3.11、固定源码及依赖、模型、YuNet、FFmpeg、Manju 口型桥接 | 一键安装及同机空缓存推理通过，不再借用语音环境的 site-packages；仍需另一台电脑验证 |
| 后期处理 | Manju 增强桥接、ComfyUI `FrameInterpolationModelLoader`、FFmpeg/FFprobe | RIFE、重复帧、两个超分及两种水印实测通过；已核对音轨、时长与浏览器播放 |

向导安装官方 ComfyUI，并通过项目专用的模型路径文件和安装检查节点连接所选模型目录；从外部入口启动的 ComfyUI 也会在重启后加载该目录。无需修改 ComfyUI 源码中的盘符，也不覆盖用户的 `extra_model_paths.yaml`。

[本机环境版本参考](local-environment-reference.json) 保存了可确认的 Git commit 及本地修改状态。它用于后续复现对照，不是已经验收的安装锁文件。

已修复画布新用户默认依赖 D 盘的问题：新安装使用用户主目录下的 `ManjuData`；已有配置优先，Windows 上已有 `D:/ManjuData/library.sqlite` 的安装仍保留原数据路径。

Web 向导使用 `setup-sources.json` 固定运行环境下载源，使用 `models.json` 和 `model-checksums.sha256` 核对共享模型。旧的 `scripts/install_speech_models.py` 会查询上游当前 revision，仅供手动维护，不是首次安装入口，也不作为本次固定版本分发的验收依据。

## 发布与教程验收

2026-11-14 的来源核对和实际生成结果见 [模型许可证说明](MODEL-LICENSES.md) 与 [逐模式验收记录](GENERATION-VALIDATION.md)。此前等待的正式创作任务已结束，28 项本地功能验收已通过；该结果不作为发布批准。

1. 已完成夸克存量核对、分类整理、补传和云端文件名/大小复核。本轮 25 个实际分享下载文件 SHA-256 一致；其余 23 个受公开接口大小限制未验证，用户决定不再继续回下载。详见 [下载核对记录](QUARK-DOWNLOAD-VALIDATION.md)，不能描述为云端全量哈希通过。
2. 48 个模型包文件已记录在 [逐文件来源表](model-sources.json)，适用条件和未解决项见 [模型许可证说明](MODEL-LICENSES.md) 与 [许可复核记录](license-review.json)。`source_status: verified` 只表示来源校验匹配，不表示商业用途或再分发已获批准。w2v-bert 和 CAMPPlus 的官方许可依据已补齐；LatentSync 1.5 的许可版本适用性等事项仍待确认。分发包需附原始许可证和 NOTICE。
3. 已固定 ComfyUI、必要节点和语音/口型安装源及依赖清单。验收记录区分全新安装与复用环境，不能把节点检查通过当作所有模式都已生成成功。
4. 发布时必须包含本次新增的启动脚本、`release` 清单、引导后端/前端、桥接节点和两份“首次启动先看我”。本地尚未提交的文件不会出现在远程仓库下载包中；提交发布版本后，还需下载该版本 ZIP 复核文件完整性。
5. 验证创建项目、导入素材、保存并重开、导出及重新导入项目。
6. 按所发布功能包逐项实际生成：Qwen 文生图与编辑、H3 图像、标准视频、Turbo 视频、音色设计、语音克隆、文本情绪、口型、插帧、两个超分选项。记录显卡、显存、分辨率、时长、耗时和错误；不使用推测的最低显存要求。
7. 用缺失模型、缺失节点、缺少 FFmpeg 的环境核对用户看到的错误和恢复步骤。
8. 验收通过后再录从零教学视频：环境安装 → 模型下载及放置 → 节点与桥接安装 → 自检 → 第一张图 → 视频和语音 → 常见问题。

教学视频使用空白用户目录和示例素材，避免依赖作者的账户、API 密钥、已有项目或隐式缓存。

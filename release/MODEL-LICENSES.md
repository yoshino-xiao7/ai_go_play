# 模型来源与许可证核对

核对日期：2026-11-14。项目代码的 MIT 许可证不替代模型许可证。本页记录来源事实和上游条款，不是统一的商业使用授权。暂不发布或重新上传模型包。

## 逐文件依据

[model-sources.json](model-sources.json) 覆盖分享清单的全部 48 个文件，保存固定版本、实际文件路径、下载来源、校验方式及许可证。47 个文件匹配上游 LFS SHA-256、Git blob SHA-1 或实际下载的 SHA-256；另一个 `manju-models.json` 是安装器生成的本地清单。小文件 Git blob 校验包含 Git 的对象头，不等于直接对文件求 SHA-1。

[model-checksums.sha256](model-checksums.sha256) 用于下载后的本地完整性校验。本次从夸克分享实际下载的 25 个文件（88,381,980 字节）SHA-256 全部一致；另外 23 个大文件因公开下载大小限制未完成回下载校验。用户已决定不再继续下载。48 个文件名称和大小全部匹配，但这不等于云端内容已全量哈希校验，详见 [下载核对记录](QUARK-DOWNLOAD-VALIDATION.md)。

| 模型或组件 | 原始 / 转换来源 | 许可证与需要保留的条件 |
| --- | --- | --- |
| Qwen Image 2.1 Turbo、配套编码器和 VAE | [Qwen](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo)、[Comfy-Org](https://huggingface.co/Comfy-Org/Qwen-Image-2.1) | Qwen Research License：研究、评估及非商业用途；商业用途需另行授权。复制协议、保留 NOTICE、标明修改。 |
| MiniMax H3 Image 与配套编码器 / VAE | [MiniMaxAI](https://huggingface.co/MiniMaxAI/MiniMax-H3-Image)、[Comfy-Org](https://huggingface.co/Comfy-Org/MiniMax-H3-Image) | H3 Image Community License；排除欧盟、英国、韩国、美国。年化收入超过 100 万美元，或提供 Hosted Service，需要事先书面授权；具体定义以上游完整条款为准。 |
| MiniMax H3 视频 FL2VA、Ref2VA、音视频 VAE | [MiniMaxAI](https://huggingface.co/MiniMaxAI/MiniMax-H3)、[Comfy-Org](https://huggingface.co/Comfy-Org/MiniMax-H3)、[Kijai 视频 VAE](https://huggingface.co/Kijai/MiniMax-H3-experimental) | H3 Community License；同样排除上述地区，年商业收入超过 2000 万美元须另行授权；商业界面归属标记、分发协议和可接受使用条款仍适用。Kijai 转换仓库没有另附独立转换许可文本。 |
| Qwen3.5 提示词增强 | [Qwen](https://huggingface.co/Qwen/Qwen3.5-9B)、[Comfy-Org](https://huggingface.co/Comfy-Org/Qwen3.5) | Apache-2.0，保留许可与适用声明。 |
| H3 Turbo LoRA | [larryvrh](https://huggingface.co/larryvrh/MiniMax-H3-Turbo-Lora) | 作者标注 Apache-2.0；基础 H3 的条款仍然适用。 |
| Turbo Heretic 文本编码器 | [ethanfel](https://huggingface.co/ethanfel/Qwen3-VL-32B-Ultra-Heretic-H3-ComfyUI-INT8-ConvRot)、[llmfan46](https://huggingface.co/llmfan46/Qwen3-VL-32B-Instruct-ultra-uncensored-heretic)、[Qwen](https://huggingface.co/Qwen/Qwen3-VL-32B-Instruct) | 仓库声明 Apache-2.0；已记录转换链和本地重命名。 |
| IndexTTS 2.5 与情绪模型 | [IndexTeam](https://huggingface.co/IndexTeam/IndexTTS-2.5) | bilibili Model License；月活超过 1 亿或年收入超过人民币 10 亿元需另行授权；保留模型目录内 LICENSE。 |
| w2v-bert-2.0 | [facebook](https://huggingface.co/facebook/w2v-bert-2.0)、[官方授权范围](https://github.com/facebookresearch/seamless_communication/blob/9a081e935c29c6b1e0e05bcbf3fcb623ad306524/README.md#license) | **依据已补齐**：官方模型卡 MIT，Seamless Communication 的 License 段明确将 W2v-BERT 2.0 编码器纳入 MIT_LICENSE；已收录 Meta 署名的完整原文。不要错用同仓库 SeamlessM4T 的非商业许可。 |
| CAMPPlus | [funasr](https://huggingface.co/funasr/campplus)、[ModelScope 原始模型](https://modelscope.cn/models/iic/speech_campplus_sv_zh-cn_16k-common) | **依据已补齐**：两个官方模型卡均声明 Apache-2.0，原始权重 SHA-256 与本地一致；已保存模型卡、关联 3D-Speaker 项目许可及标准 Apache-2.0 原文。模型仓库没有单独 LICENSE 文件这一事实保留，不将其误判为许可类型未知。 |
| BigVGAN | [NVIDIA](https://huggingface.co/nvidia/bigvgan_v2_22khz_80band_256x) | MIT；原始许可已收录。 |
| LatentSync 1.5 UNet | [ByteDance 模型卡](https://huggingface.co/ByteDance/LatentSync-1.5)、[维护者早期回复](https://huggingface.co/ByteDance/LatentSync/discussions/3) | 模型卡声明 OpenRAIL++。维护者曾在早期版本讨论中指向 CreativeML Open RAIL++-M（2023-07-26）全文，本次已保存。**尚缺该全文对 1.5 指定权重版本的明确适用确认**；1.5 的相关询问尚无维护者答复，不能混用代码 Apache-2.0。 |
| Whisper tiny | [OpenAI Whisper](https://github.com/openai/whisper)；文件来自 LatentSync 配套快照 | MIT；保留原始许可。 |
| sd-vae-ft-mse | [Stability AI](https://huggingface.co/stabilityai/sd-vae-ft-mse) | 官方模型卡明确声明 MIT，已保存固定版本原文及 kl-f8 基础项目的 LMU Munich MIT 声明；后者不等于 Stability AI 微调版独立版权声明。微调版完整原件仍缺，不把通用模板冒充作者原件。 |
| YuNet 2023mar | [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | 模型子目录 MIT，保留 Shiqi Yu 原始声明。 |
| RIFE 4.26 heavy | [routineLife1/DRBA](https://github.com/routineLife1/DRBA) | 仓库 MIT；已核对固定提交中的权重文件。 |
| RealESRGAN x4plus Anime6B | [官方 v0.2.2.4 发布附件](https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.2.4) | BSD-3-Clause；保留原始声明。 |
| 4x Foolhardy Remacri | 作者 FoolhardyVEVO；[社区模型目录](https://openmodeldb.info/models/4x-Remacri) 指向 [FacehugmanIII 镜像](https://huggingface.co/FacehugmanIII/4x_foolhardy_Remacri) | 社区目录标注 CC-BY-NC-SA-4.0：非商业、署名、相同方式共享，并标注改动。直接下载镜像标注 unknown，作者原始授权仍待确认；不能采用另一镜像冲突的 CDLA 元数据来放宽授权。 |

## 固定版本与变更说明

- Qwen Turbo 本地权重匹配 Comfy-Org 的 `219a3db9865efbc1ca36a51120aed6402cb95071`。当前 `main` 的同名文件已经改变；来源表使用实际匹配的历史版本。
- H3 视频 INT8 VAE 匹配 Kijai 的 `c2e7b89b1800123c49a0f620a1932c01d8952256`，不是当前 Comfy-Org 的另一份同名转换。
- Turbo 文本编码器在本项目重命名为带 `minimax_h3` 的文件名；内容未修改，SHA-256 与 ethanfel 上游完全相同。
- 其余模型文件只归类目录，不修改权重。第三方量化、裁剪、训练和合并由来源表中的上游作者执行，不是本项目的原创权重。

## 分发材料与剩余事项

[licenses/index.json](licenses/index.json) 记录原始许可、官方模型卡和补充证据的固定版本、来源 URL、类型和 SHA-256；参考文本与作者原件明确区分。[NOTICE.txt](NOTICE.txt) 保存署名与变更声明。之后制作模型压缩包时，应把这些文档、来源表、许可复核记录和整个 `licenses/` 目录一并附上，保留模型目录自身的 LICENSE。

本次补齐了 w2v-bert 和 CAMPPlus 的官方依据，修正了 NOTICE 将 Remacri 社区声明写成作者已确认授权的问题。[license-review.json](license-review.json) 将结论与具体文件、原文证据关联，以下分发材料仍不完整，暂不重新打包或上传这些权重：

- LatentSync 1.5：已有全文参考，待确认对指定 1.5 版本的适用性。[已有询问](https://huggingface.co/ByteDance/LatentSync-1.5/discussions/1)尚无维护者答复；未代用户发帖或联系作者。
- Remacri：待取得作者原始授权；社区记录的 CC-BY-NC-SA-4.0 不能改写成作者已确认，更不能用镜像的宽松元数据覆盖。
- sd-vae-ft-mse：许可类型为官方声明的 MIT，仍缺微调版完整版权与许可原件。
- Kijai H3 VAE：基础 H3 协议原文齐全，转换仓库没有单独转换授权，相关分发材料待确认。

Qwen 的研究用途限制、H3 的地区 / 托管服务限制以及 Remacri 社区声明的非商业限制必须保留给下载者判断；代码开源不代表所有模型可用于任意商业服务。源文件匹配和 GPU 功能通过均不能关闭这些许可事项。

H3 公开提供给第三方前，还需按原始协议落实下游使用条款、适用地区及服务条件；现有“隐私与用户手册”确认不能自行视为已完成这些分发要求。

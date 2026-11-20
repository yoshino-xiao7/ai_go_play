---
name: ai-go-play-h3-enhancer
description: 收录并调用MushroomFleet的minimaxh3-enh原版技能。用于根据用户创意和真实参考图增强H3视频提示词，保留原句、输入用途、镜头与声音安排；只输出提示词，不生成视频。
---

# ai-go-play · H3提示词增强

这是社区增强技能的原版收录入口。实际增强前读取原版 `minimaxh3-enh/SKILL.md`，并按其要求读取所需 references；不把本入口当作增强方法摘要。

它是社区增强项，不标成MiniMax官方。用户指定交付位置、素材、语言和阶段时沿用当前请求；上游默认Markdown文件不能覆盖用户明确要求的画布留痕。实际提交由 `ai-go-play-canvas` 负责。心理活动的演法由当前创作确定，不能只因其内容是心理活动就误归类为原版所说的 off-screen voiceover。

原文的工具名称按宿主能力对应：`ask_user_input_v0` 使用当前宿主问答工具或当前对话提问；已确认的信息直接沿用。读取图片、写入交付内容也使用宿主实际提供的能力，不因同名工具不存在中断，不假装调用未提供的工具。

## 读取收录原文

在本技能目录运行：

```powershell
python scripts/source.py materialize
```

读取器仅需 Python 3.12+ 标准库。Windows 一键安装提供项目根目录的 `.venv/Scripts/python.exe`；`python` 不在 PATH 时用该解释器的绝对路径运行本技能的 `scripts/source.py`。独立安装时使用可用的 Python 3.12+。

该命令先核对封存包与逐文件SHA-256，再将原目录结构解封到系统临时缓存，返回原版入口的绝对路径。打开返回的入口执行；相对引用、图片和原始文件名保持不变。已有缓存若被修改，另建副本，不覆盖修改。它不联网、不执行上游代码，也不调用生成器。Windows路径过长时使用系统支持的扩展路径；需要指定可写短缓存目录时追加 `--cache-dir <目录>`。

只读单个文件可用 `python scripts/source.py read 原始相对路径`；完整清单与固定版本见 [来源清单](sources/manifest.json)，使用说明见 [来源与许可](NOTICE.md)。补充仓库文档可能引用未收录的仓库级文件，按清单中的固定上游地址查阅。

原文中的相对引用以原文件目录为基准，先规范化为绝对路径再读取；Windows 长路径中的 `..` 也必须先解析。

---
name: ai-go-play-h3-official
description: 收录并调用MiniMax-AI官方H3视频提示词技能。用于T2VA、I2VA、FL2VA、L2VA与Ref2VA的模式、字段、参考标签、声音及关键帧表达；不负责调用视频生成器。
---

# ai-go-play · H3官方提示词

这是官方原版技能的收录入口。实际编写前读取原版 `skills/h3-prompt-writing/SKILL.md`，再按原版要求读取 `base-en.txt` 或 `ref-en.txt`。字段、标签和输出规则以该固定版本为依据，不以旧项目摘要代替原文。

需要社区增强时，单独调用 `ai-go-play-h3-enhancer`；需要实际画布提交时，单独调用 `ai-go-play-canvas`。社区规则和项目接口不写回官方原文。

## 读取收录原文

在本技能目录运行：

```powershell
python scripts/source.py materialize
```

读取器仅需 Python 3.12+ 标准库。Windows 一键安装提供项目根目录的 `.venv/Scripts/python.exe`；`python` 不在 PATH 时用该解释器的绝对路径运行本技能的 `scripts/source.py`。独立安装时使用可用的 Python 3.12+。

该命令先核对封存包与逐文件SHA-256，再将原目录结构解封到系统临时缓存，返回原版入口的绝对路径。打开返回的入口执行；相对引用、图片和原始文件名保持不变。已有缓存若被修改，另建副本，不覆盖修改。它不联网、不执行上游代码，也不调用生成器。Windows路径过长时使用系统支持的扩展路径；需要指定可写短缓存目录时追加 `--cache-dir <目录>`。

只读单个文件可用 `python scripts/source.py read 原始相对路径`；完整清单与固定版本见 [来源清单](sources/manifest.json)，使用说明见 [来源与许可](NOTICE.md)。补充仓库文档可能引用未收录的仓库级文件，按清单中的固定上游地址查阅。

原文中的相对引用以原文件目录为基准，先规范化为绝对路径再读取；Windows 长路径中的 `..` 也必须先解析。

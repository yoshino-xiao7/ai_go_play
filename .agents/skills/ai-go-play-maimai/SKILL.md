---
name: ai-go-play-maimai
description: 收录并调用BenBenHS/maimai-tangtang的原版动画制作与首帧技能，用于剧本拆镜、二维日常表演、首帧、动态和审片。原技能、制作参考和配套图片独立保存，不与项目自写导演规则混编。
---

# ai-go-play · 麦麦糖糖原版制作

本项收录原项目的两个互相引用的技能，作为同一来源包使用。

- 剧本、分镜、动态、声音、审片：读取原版 `skills/maimai-tangtang-animation/SKILL.md`，按它的链接继续读取所需参考。
- 首帧、画风与人物核对：读取原版 `skills/mmt-cel-first-frame/SKILL.md`。
- 角色与图片：使用解封后的原始相对路径；扩展服装图库未打包的图片按manifest所列固定上游版本访问。

先读原版，再实际执行，不用此前的项目融合稿或历史试镜替代。当前用户决定角色、模型、风格和交付阶段；原版角色作为参考，不自动成为当前故事出演角色。需要控制本项目画布时单独调用 `ai-go-play-canvas`。

## 读取收录原文

在本技能目录运行：

```powershell
python scripts/source.py materialize
```

读取器仅需 Python 3.12+ 标准库。Windows 一键安装提供项目根目录的 `.venv/Scripts/python.exe`；`python` 不在 PATH 时用该解释器的绝对路径运行本技能的 `scripts/source.py`。独立安装时使用可用的 Python 3.12+。

该命令先核对封存包与逐文件SHA-256，再将原目录结构解封到系统临时缓存，返回原版入口的绝对路径。打开返回的入口执行；相对引用、图片和原始文件名保持不变。已有缓存若被修改，另建副本，不覆盖修改。它不联网、不执行上游代码，也不调用生成器。Windows路径过长时使用系统支持的扩展路径；需要指定可写短缓存目录时追加 `--cache-dir <目录>`。

只读单个文件可用 `python scripts/source.py read 原始相对路径`；完整清单与固定版本见 [来源清单](sources/manifest.json)，使用说明见 [来源与许可](NOTICE.md)。补充仓库文档可能引用未收录的仓库级文件，按清单中的固定上游地址查阅。

原文中的相对引用以原文件目录为基准，先规范化为绝对路径再读取；Windows 长路径中的 `..` 也必须先解析。

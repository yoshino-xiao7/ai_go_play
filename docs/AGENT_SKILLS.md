# 使用 ai-go-play 创作技能集

技能是给 Agent 读取和执行的制作方法。完整工程在 `.agents/skills/` 提供四个独立入口；上游原文和参考素材分别封存在各自来源包中。

## 在项目中调用

把完整源码或发布 ZIP 解压后的工程作为 Agent 工作目录。在 Codex 中可使用 `$技能名` 明确调用，也可以描述任务让 Agent 选择。项目技能发现与调用规则见 [OpenAI 官方说明](https://learn.chatgpt.com/docs/build-skills)。其他 Agent 的技能发现路径以其自身说明为准，也可明确让它读取对应 `SKILL.md`。

| 入口 | 示例请求 |
| --- | --- |
| `ai-go-play-canvas` | `$ai-go-play-canvas 读取当前项目，列出卡片和固定素材版本，先不修改。` |
| `ai-go-play-h3-official` | `$ai-go-play-h3-official 按官方原文为这段文字写 H3 视频提示词，先不生成。` |
| `ai-go-play-h3-enhancer` | `$ai-go-play-h3-enhancer 增强这个镜头的表演与声音提示词，保留对白，先不生成。` |
| `ai-go-play-maimai` | `$ai-go-play-maimai 读取原版制作技能，把这段剧本拆镜，只交付文字分镜。` |

麦麦糖糖入口内保留动画制作和首帧两份原版技能，由任务选择；它们属于同一来源包，不增加项目入口数量。

## 运行环境和自检

读取来源包需要 Python 3.12+ 标准库，无需安装额外 Python 包、联网或运行 GPU。Windows 一键启动准备的解释器位于项目 `.venv/Scripts/python.exe`，不要求全局存在 `python` 或 `manju` 命令。

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts/check_agent_skills.py
```

检查会核对四个入口、三个来源包及逐文件哈希，在隔离临时目录解封，并读取原版入口及封存文件。缺文件或校验失败会返回非零退出码。该检查验证打包与读取能力，模型出图质量和 Agent 的实际创作表现需另行审查。

手动打开原版时也从项目根目录运行，例如：

```powershell
.\.venv\Scripts\python.exe .agents/skills/ai-go-play-h3-official/scripts/source.py materialize
```

按返回的 `entrypoints` 读取原文，按原文继续读取所需参考。相对引用以原文件目录为基准，先解析为绝对路径；Windows 长路径中的 `..` 需要先规范化。可用 `--cache-dir <可写目录>` 指定缓存位置。

画布控制需要运行中的 ai-go-play 服务。项目 CLI 可用 `.\.venv\Scripts\python.exe -m manju --help`，也可直接调用服务 API。用户独立安装技能时，仍需提供 Python 和所用工具；技能文本不会安装绘图工具、H3、ComfyUI 或模型。

## 在其他工作目录使用

按所用 Agent 的安装方式安装四个完整技能目录。Codex 用户可让安装技能处理当前工程，例如：

```text
用 $skill-installer 将当前工程 .agents/skills/ 下四个 ai-go-play 技能完整安装为用户技能，保留所有 sources、scripts、references 和许可说明。
```

不要只复制入口 `SKILL.md`。三个来源包的 `sources/upstream.zip`、`sources/manifest.json`、`scripts/source.py` 和 `NOTICE.md` 都属于安装内容。独立安装仍使用自己的 Python 3.12+，不能依赖原作者机器的目录或当前会话的辅助脚本。

## 输入、工具和收录范围

H3 官方与增强技能负责提示词。没有参考图时可以按文字模式编写；采用首帧或参考模式时需要实际输入，Agent 应先看图。分辨率等生成参数由画布或生成器设置。

增强原文中的 `ask_user_input_v0` 对应宿主的问答工具或当前对话；没有同名工具时按当前宿主能力执行。用户已经提供的信息应直接沿用。

首帧制作需要宿主提供图像生成能力，视频制作需要就绪的生成器与模型。宿主没有相应工具时，文字分镜和提示词仍可交付，但不能声称已经生成媒体。

麦麦糖糖来源包包含两份完整技能、核心参考、样张和基础角色图；扩展设计与服装图库、音频、权重及部分仓库级补充文件留在固定上游版本。实际缺少的可选素材按 `sources/manifest.json` 的上游地址查阅，不能当作已加载输入。原角色可以作参考，当前用户决定故事出演角色和风格。

各包 `NOTICE.md` 与 `sources/manifest.json` 记录来源、版本、许可和收录范围。项目源码的 MIT 许可不替代上游各自条款。

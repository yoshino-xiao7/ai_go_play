# Manju · 本地创作工作台

Manju 0.1 提供项目管理、无限画布、图片/视频/音频资产库、不可变素材版本、预览任务、回收站、项目打包、存储迁移和本机 ComfyUI 进程管理。已接入本地 ComfyUI 图片生成、H3 视频、IndexTTS 人物配音、LatentSync 口型同步与可选的 OpenAI 云端图片生成；可按分镜制作，也可在多轨时间线自由剪辑、混音、叠加图片和文字，并按画布参考依赖自动编排生成。浏览器与 CLI 通过同一个本机 API 操作数据，生成素材与成片都保存在项目和资产库中。可执行功能、已完成的真实验收和模型效果限制分别见下文。

## 功能导航

| 功能 | 已有能力与使用入口 |
| --- | --- |
| [画布与主体库](#在画布制作素材板) | 素材卡、人物/场景/道具、多图与人物音色、固定版本引用、候选采用、草稿恢复、跨画布复制、画框合成 |
| [图片生成](#在画布生成图片) | ComfyUI 本地文生图、参考生图与蒙版编辑；可选 OpenAI 云端图片工作流 |
| [视频生成](#本地-minimax-h3-视频创作) | H3 文生视频、首尾帧、图片/视频/音频混合参考及 Director 流程 |
| [人物配音](#本地人物配音indextts-25) | IndexTTS 2.5 固定音色、情绪、语速、发音纠正与候选试听；人物卡另支持 H3 音色设计 |
| [口型同步](#本地口型同步latentsync-15) | 固定视频与配音、自动或手工人脸区域、音频偏移与独立结果版本 |
| [分镜成片](#从分镜到成片) | 镜头清单、缺失素材批量生成、版本采用、字幕、背景音乐、MP4 与剪辑包导出 |
| [多轨剪辑](#多轨剪辑) | 视频/音频/图片/文字轨道、裁剪、混音、画中画与成片导出 |
| [自动编排](#画布自动编排) | 按画布参考依赖预检、复用已有结果、执行下游、取消与重试 |
| [存储与迁移](#本地目录与迁移) | 内容去重、不可变版本、引用保护、回收站、项目包与完整资料库迁移 |
| [ComfyUI 管理](#管理本机-comfyui) | 扫描安装、启动/停止、进程接管、队列保护与日志 |
| [CLI / Agent](#cli-与-agent) · [API 与验证](#api-与验证) | 本机 HTTP API、JSON 命令、修订冲突检查、幂等请求与持久化任务 |

## 快速开始

仓库名为 `ai_go_play`，应用名与 Python 命令为 `Manju` / `manju`。已有工作区可直接执行安装；在其他电脑上先克隆私有仓库（需拥有仓库访问权限）：

```powershell
git clone https://github.com/yoshino-xiao7/ai_go_play.git
cd ai_go_play
```

Windows 使用 Python 3.12 及以上和 Node.js 22.12 及以上。在仓库目录执行安装和构建。音视频导入需要 FFprobe，预览转码需要 FFmpeg。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -c requirements.lock -e ".[dev]"
npm --prefix frontend ci
npm --prefix frontend run build
```

双击 `start.vbs` 会在后台启动工作台，并自动打开浏览器，整个入口使用隐藏窗口。长期服务通过 `pythonw.exe` 运行，日志写入文件。`start.cmd` 会立即转入相同的无窗口入口。脚本先检查已运行的本地服务，同一端口重复启动会打开现有工作台。首次启动会检查依赖和前端产物，缺项时弹窗显示安装命令并保存错误日志。默认页面为 http://127.0.0.1:8765。关闭浏览器后服务和预览任务继续运行。

Agent 或自动化可以调用 `powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -NoBrowser`，检查返回码并读取输出。`start.ps1` 与 `start.vbs` 都接受 `-Port`、`-DataDir`、`-ConfigFile` 和 `-NoBrowser`，中文及含空格路径应加引号。系统禁用 Windows Script Host 时，可以直接使用 `start.ps1`。

首次默认启动成功后，工作区的 `.manju/launcher.json` 会保存实际配置路径，确保以后从 Explorer 或 Agent 启动时使用同一份配置。该文件由 Git 忽略。显式目录参数及 `MANJU_DATA_DIR`、`MANJU_CONFIG_FILE` 优先，适合启动独立资料库。

也可以在终端启动，按 Ctrl+C 退出服务。

```powershell
.\.venv\Scripts\python -m manju serve
```

隐藏进程日志位于 `%LOCALAPPDATA%\Manju\run\server-8765.out.log` 和 `server-8765.err.log`。同目录的 `server-8765.json` 记录本次启动的 PID、端口和仓库目录，`launcher-*.log` 记录入口失败原因。启动进程会脱离终端，Agent 捕获命令输出时也能正常返回。自定义端口可以执行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -Port 8766`。

需要整体退出时，先等待生成结束或明确取消任务，再在 ComfyUI 面板主动停止托管服务。随后核对启动记录中的 PID，在任务管理器结束该进程树，或执行 `taskkill /PID <记录的PID> /T /F`。`/T` 会同时结束后代进程，包含该工作台启动的 ComfyUI，不能用于需要保留生成服务的重启。

仅重启工作台、保留 ComfyUI 时，先根据监听端口、命令行及启动记录核对实际运行 `-m manju serve` 的服务进程，只对这个已确认的服务 PID 执行 `Stop-Process -Id <服务PID>`，不要结束整棵进程树。重新启动工作台后会按持久记录核验并接管仍在运行的托管 ComfyUI。不能仅凭 `python.exe` 或 `pythonw.exe` 名称结束进程。

FFmpeg 检测会尝试显式环境变量、PATH、WinGet 安装目录及常见目录。若诊断找不到实际二进制，先设置路径，再启动服务。

```powershell
$env:MANJU_FFMPEG = "C:\ffmpeg\bin\ffmpeg.exe"
$env:MANJU_FFPROBE = "C:\ffmpeg\bin\ffprobe.exe"
.\.venv\Scripts\python -m manju serve
```

前端依赖使用 `frontend/package-lock.json` 和 `npm ci` 固定解析结果。Python 依赖范围记录在 `pyproject.toml`，已验证的依赖版本锁定在 `requirements.lock`，安装时通过 `-c requirements.lock` 使用。

### 按功能准备依赖

| 使用范围 | 额外准备 |
| --- | --- |
| 项目、画布、图片资产管理 | 安装 Python 与前端依赖并构建即可，不需要 GPU 或云端密钥 |
| 音视频导入、预览、成片 | FFprobe / FFmpeg；中文烧录字幕还需可用的中文字体 |
| ComfyUI 图片与 H3 视频 | 可用的本机 ComfyUI、对应自定义节点及模型；在工作流页检查就绪状态 |
| IndexTTS 人物配音 | 独立 Python 3.11 / CUDA 推理环境、IndexTTS 2.5 模型及语音桥接节点，见人物配音章节 |
| LatentSync 口型同步 | 独立推理环境、LatentSync 1.5 模型、人脸检测模型及口型桥接节点，见口型同步章节 |
| OpenAI 图片 | 可选的 `OPENAI_API_KEY`、网络及当前 API 项目的模型权限；生成按 API 用量计费 |

克隆仓库不会携带模型、ComfyUI 安装、`.manju/` 中的推理环境、用户资产库或本机密钥。README 中的 `D:/github/...`、`F:/bilitv/...` 是原开发机配置或示例路径，迁移时应替换为实际路径。历史验收记录中的 `.qa/` 是本机证据目录，已被 Git 忽略，不包含在仓库中；下文的历史验收不表示新机器已通过同样验证。

## 在画布制作素材板

1. 在项目页创建项目，选择自由画布、16:9 或 9:16。
2. 在资产库导入图片、视频或音频。可改名、加标签、查看尺寸/时长、原件位置、版本和项目引用。
3. 将素材加入项目画布。素材卡固定引用一个 `asset_version_id`，新版本上传后可以检查候选并明确换用。已有卡片继续引用原版本。
4. 拖动、缩放、连接素材卡，加入文字、分组和画幅。画布自动保存内容、卡片位置和关系。平移、缩放、选中、预览及搜索定位只改变本机视图，视角单独记忆，不触发保存或更新共享修订。其他页面或 CLI 修改后，未编辑的画布自动同步并保留当前视角；真实内容编辑存在冲突时保留本机草稿。
5. 导出 `.manju` 项目包可保存画布及其引用媒体，重新导入会创建新的项目和资产 ID，内容相同的原件复用存储。

顶部项目名称下拉菜单按最近访问顺序列出项目，其余项目按修改时间排列，支持按名称或项目 ID 搜索、切换、新建、更名，以及在独立新页面打开。当前项目也可通过名称旁的铅笔更名。“项目信息”展示创建时间、最近修改、画布修订、画幅和图片、视频、音频、文字、主体、画框、分组及连线数量。顶部“项目 ID”按钮与信息弹窗都可复制完整 ID，供 Agent 使用 `manju canvas inspect --project PROJECT_ID` 等 CLI 命令定位同一画布。更名只更新项目信息，不改动画布修订。

同一内容重复导入会复用已有资产，相同文件名而内容不同会创建独立资产。向指定资产添加版本可以保存同角色的多次修订。素材删除前检查所有项目引用，回收站中的项目同样保护素材。先从项目移除素材或永久删除相关项目，再将素材移入回收站并按需要永久删除。修复缺失原件要求上传与选定版本哈希一致的文件，改动后的内容通过添加版本保存。

右击卡片可复制、复制副本、粘贴、保存到其他画布、保存到主体库、下载、撤销、重做和删除。多选后右击其中一张卡片会保留整组选区；锁定的卡片不会被删除。下载对应卡片当前显示的媒体原件，不支持的操作会置灰。右击空白处可在落点新建图片生成卡、文字、分组、横竖构图框，或导入图片、视频和音频；粘贴也使用该落点。文字输入区保留浏览器原生右键菜单。

“保存到其他画布”可选择已有项目或新建项目，复制所选卡片、分组内的内容及内部连线，放在目标画布已有内容旁边。媒体复用固定版本和物理文件，源画布保持原样；目标有并发修改时会重新读取合并。

人物、场景和道具使用独立主体卡。卡片上方的节点名称是当前画布中的别名，卡片内部的 `@主体名`、描述和参考图构成主体设定；资产显示名称可在属性面板单独修改。右击空白处或左侧工具栏可新建主体，右击现有图片可转为主体。

每个主体最多保存 12 张固定版本图片，第一张用作封面和连线参考；其他图片可通过 `@` 单独引用。卡片内的“＋”支持本地添加、从资产库选择、从画布选择。人物卡右上角的音色菜单支持上传、选择已有音频，或“设计角色音色”：填写声线描述和中性试听文本，本地 H3 生成 1 个或 3 个候选，试听后“采用并绑定角色”。无需已有录音；参考角色外形为可选。候选使用独立持久化任务、随机种子和模型快照，自动保存为音频资产；关闭窗口后任务继续，重新打开可查看候选。生成候选不会自动替换现有绑定。

人物音色菜单中的“用此角色生成原生音画”会新建 H3 全参考视频卡，带入主参考图及已绑定的固定音频版本，并开启原生声音。音频用途是音色身份：当前镜头决定新台词、语气、语速、停顿和表情；不会用参考录音替换视频声音，也不自动补口型。视频中的 `@角色 · 音色` 同样默认采用这一用途。固定输入不等于模型严格锁定声音，跨镜头的音色一致性和表演自然度仍需试听确认。音色设计沿用 H3 音画联合采样，只解码并保存约 8 秒音频，因此耗时接近视频生成；它用于角色定音，不用于逐句合成。需要独立旁白或配音时，可使用“生成独立配音”进入 IndexTTS 创作卡。

连线从卡片两侧的圆形“＋”开始，支持点击两端连接或按住拖拽。默认显示细灰色曲线，悬停或选中卡片时关联线高亮为蓝色；选中连线可编辑关系文字或删除，并支持撤销。图片或主体连接到图片生成卡时，会将固定图片版本传入参考列表，生成结果仍回填原生成卡片。

“保存到主体库”保存名称、描述、多图及人物音色，至少需要一张图片。在“素材 → 主体库”搜索、按类型筛选、编辑或拖入任意项目。放入画布的是主体设定快照，库内修改不影响已有卡片；仍被主体库或画布引用的任一图片、音频不能删除。完整资料库迁移包含主体库，单个项目包包含主体快照及其全部图片和音频，导入时不关联原主体库条目。

### 草稿恢复、节点查找与画框合成

画布右上角“更多 → 草稿恢复 / 导入 JSON”可以查看本机草稿、冲突备份及导入先前下载的画布 JSON。发生修订冲突时，先备份草稿再加载服务端最新版本；恢复会把旧内容作为新节点副本追加，保留当前画布和原始备份。分镜面板也提供本机草稿恢复：恢复的镜头追加为副本，当前镜头和成片设置不被覆盖，确认后可删除不需要的副本。

顶部搜索按钮按节点名称、文字、主体名称或生成描述查找节点，选择结果可定位并展开其上级分组。画布采用视区内节点渲染，视频卡使用海报缩略图；查看原件时才打开播放器。视区裁剪减少屏外 DOM，但并不限制项目节点数，也不保证任意规模或大量独立媒体都保持同样速度。长项目仍建议按场景分组，使用镜头清单安排顺序。

选中画幅框，在属性面板点击“合成画框图片”，将与画框相交的图片和文字按位置、层级合成为透明 PNG，超出画框的部分被裁去。结果作为新图片加入当前画布和资产库，原卡片保持可编辑。画框中的视频、音频不能用于这一静态合成；它们应通过“分镜成片”制作视频。画框合成支持图片等比缩放、透明度和中文文字，尚不包含图层混合模式、旋转变形等完整图像编辑器功能。

## 从分镜到成片

1. 先在画布准备人物、场景与各镜头首帧，再建立视频生成卡和人物配音卡。每张源卡保存生成描述、参考素材、工作流和参数；人物音色用于配音，不能直接替代视频口型驱动。
2. 点击顶部“分镜成片”，按顺序添加镜头，填写场景、人物、说话人、准确台词及计划时长。镜头同时显示为画布中的分镜卡，可从面板定位，或双击分镜卡重新打开面板。
3. 为每个镜头关联已配置的视频卡、配音卡，或直接选择项目已有视频、音频。“生成缺失素材”只提交缺少已采用版本的镜头；视频沿用源卡设置，配音使用镜头中的台词及源卡音色。源卡已有进行中或状态待核对的任务时，不重复提交。
4. 在源卡试听、查看并采用候选，再回到分镜面板刷新，明确采用源卡当前视频或配音。镜头固定具体素材版本，后续生成不会悄悄替换已采用结果；来源变化会显示更新提示。需要返工时，可只重做当前镜头的视频或配音。
5. 设置视频裁剪起点、镜头时长、配音延迟、原视频与配音音量。字幕使用镜头台词，可指定镜头内的开始和结束时间。成片设置支持统一尺寸、帧率和背景音乐；输出时长按目标帧率对齐。
6. 点击“检查”和“连播”，确认画面、台词、音色、人物外貌与镜头衔接。视频不够长、素材原件缺失或配音超出镜头时长时，导出会报错，避免静默截断台词。调整镜头或重做配音后再检查，并记录验收状态及返工备注。
7. 点击“导出成片”，后台按镜头顺序裁剪、对齐配音、混合音乐并烧录中文字幕，输出 H.264/AAC MP4。任务保存输入快照，关闭面板或浏览器后仍继续运行；成功后可在面板播放、下载，成片同时加入当前画布和资产库。失败可按原快照重试；修改镜头后的新方案应发起新的导出。

“SRT”导出独立字幕；“剪辑包”包含采用的视频、配音、字幕与镜头清单，供外部剪辑软件继续制作。项目 `.manju` 包保存的是可继续编辑的画布、分镜、设置及引用媒体，与最终 MP4、剪辑交接包用途不同。项目复制和导入会重映射镜头固定版本及源卡 ID。

声音素材合成与字幕时序由固定版本及明确时间参数控制。需要人物说话时，可先生成准确台词，再以这段配音和人物视频执行 LatentSync 口型同步；H3 音频参考本身不保证逐字复现指定对白。口型模型仍可能改变面部细节，声音情绪、说话口型与跨镜头人物、服装、动作都需要人工审核。“固定参考版本”保证输入可追溯，不保证模型每次都保持人物一致。

### 分镜 CLI

`production inspect` 返回共享画布的 `revision`、`settings`、按顺序排列的 `shots` 和成片任务。镜头字段包含 `id`、`title`、`scene`、`characters`、`dialogue`、`speaker`、`duration`、`trim_start`、`audio_offset`、`video_volume`、`audio_volume`、`status`、`notes`，以及固定 `video_version_id` / `audio_version_id` 和来源 `video_node_id` / `audio_node_id`。修改时保留读取到的修订号；过期修订返回 409，须重新读取并合并。

```powershell
$manju = ".venv/Scripts/manju.exe"
$projectId = "替换为项目ID"
& $manju production inspect --project $projectId --json |
    Set-Content -Encoding utf8 "production.json"
# 编辑 production.json 的 shots 和 settings，保留原 revision。
& $manju production apply --project $projectId --file "production.json" --request-id "ep1-plan-v1" --json

$plan = & $manju production inspect --project $projectId --json | ConvertFrom-Json
$batch = & $manju production generate --project $projectId --revision $plan.revision --kind video --kind audio --request-id "ep1-materials-v1" --json | ConvertFrom-Json
foreach ($task in $batch.jobs) {
    & $manju job wait $task.id --max-wait 7200 --json
}
# 检查 batch.errors / batch.skipped；在源卡检视并采用候选。
# 再次 inspect，把所选 latest_video_version_id / latest_audio_version_id
# 写入相应镜头的 video_version_id / audio_version_id，随后 apply 保存。

$plan = & $manju production inspect --project $projectId --json | ConvertFrom-Json
$render = & $manju production render --project $projectId --revision $plan.revision --name "第一集 · 成片" --request-id "ep1-render-v1" --json | ConvertFrom-Json
$film = & $manju production wait $render.id --max-wait 1800 --json | ConvertFrom-Json
& $manju production subtitles --project $projectId --output "第一集.srt" --json
& $manju production handoff --project $projectId --output "第一集-剪辑包.zip" --json
```

检查每条命令的退出码后再读取结果；`production wait` 超时只停止等待，后台成片任务保留。`production show RENDER_ID` 查看任务，`production retry RENDER_ID` 按失败任务的原快照重试。`production generate --shot SHOT_ID --kind video --redo` 只重做指定镜头视频，保留已采用版本；可重复 `--shot` 或 `--kind`。同一批次或导出请求重试时复用相同 `--request-id` 与输入，输入改变时使用新编号。`subtitles`、`handoff` 的目标文件已存在时会拒绝覆盖。

画框合成也可以由 CLI 执行，返回新素材的 `asset_id`、`version_id` 和画布 `node_id`：

```powershell
& $manju canvas render-frame --project $projectId --frame FRAME_NODE_ID --name "场景构图" --scale 1 --request-id "frame-layout-v1" --json
```

2026-11-06：隔离资料库的浏览器验收已覆盖分镜保存、配音溢出校验、连续预览、SRT、真实 FFmpeg 合成回收入库、成片后继续编辑、冲突草稿恢复，以及 1366 / 860 像素窗口。修复后的后端全量测试 **316 项通过**，前端构建通过；另验证了预览字幕与导出一致、0–200% 音量、暂停和切镜、视频播放回退，以及轮询不覆盖未保存草稿。

真实资料库 `D:\ManjuData` 的 [《雨停之前 · 30秒真实生成验收》](http://127.0.0.1:8765/#/canvas/c846097b47034d23a77ac3c31a973279) 已由 CLI 完成制作：7 张 Qwen 图片（角色定妆和 6 张首帧）、6 条 H3 动态视频、6 段 IndexTTS 配音，以及原创程序合成配乐。六镜各取 5 秒，导出 **1280×720、24fps、720 帧** H.264/AAC 成片；视频轨为 30 秒，MP4 容器因音频封装显示 30.016 秒。源视频为 864×480，成片适配至 720p。项目包含 **22 个资产**，全部原件、成片和固定版本均可见；成片已在项目资产与全部资产中实际打开播放，并通过 1 / 11 / 26 秒跳转、完整解码、字幕抽帧和导出包完整性检查。

验收脚本及证据位于 `.qa/short-drama-live/`：`run.py` 保存 CLI 调用流程，`media-quality.json`、`final-ui-results.json` 保存媒体与浏览器结果；同时导出了 MP4、SRT、剪辑交接 ZIP 和 `.manju` 项目包。本地无提示 ASR 检出了全部六句台词，第 1 / 2 句仍有近音识别差异，结果保存在 `final-transcript.json`，不能视为人工听审通过。这是 V1 旁白与电话叙事样片，只证明当时顺序分镜制作及回收流程。后续已加入多轨剪辑、画布 DAG 执行与真实口型模型；V2 影视对白、多声线及口型近景已完成下述独立验收。


2026-11-06 V2：同一真实项目通过 CLI 执行 9 节点依赖图，重新生成 6 段配音、对白近景首帧和 H3 视频，再由 LatentSync 驱动口型；其余 5 镜沿用 V1 画面。林雨与母亲使用独立长音色，母亲另用情绪参考，原始音频保留动态、拼音纠正与句间停顿。两处原句复核音频一并入库；第二句无提示 ASR 完整吻合，第一句仍出现同音汉字差异，不能代替人工听审。全部新配音无满刻度样本，CAM++ 声纹比较支持两角色输出确实各自接近对应音色。

V2 成片为 **1280×720、24fps、720 帧，视频与音轨均 30.000 秒**，七轨 22 片段包含主画面、林雨、母亲电话声、配乐、雨声、字幕和标题。母亲原件偏轻，以独立轨道增益校正；最终峰值 −7.2 dBFS。项目现有 **40 个资产**，V1 的 22 个固定版本全部保留且原件 SHA-256 一致。素材和成片均在真实项目与全部资产列表可见；1366 / 860 浏览器验收完成实际播放、6 / 11 / 26 秒跳转、口型卡片专用编辑与无写入检查，零 JS / HTTP 错误。

真实口型输出为 125 帧 / 25fps / 5 秒，配音偏移实测 350ms。修复 Whisper 分块补帧造成的 80ms 延长，并只融合模型口部，保留源片其他部位；同一区域对比中，上脸平均差异下降约 54%。这证明时序与局部保护正常，不证明逐音素准确或演员级自然表演。编排重复运行时 9 节点全部复用；口型处理修订后只有该节点重新生成，其余 8 项复用。全画布 27 个已配置节点预检通过。

完整证据与可续跑 CLI 脚本在 `.qa/short-drama-v2/`：`acceptance.json`、`final-ui-results.json`、`audio-quality-v2.json`、`voice-separation-qa.json`、`lipsync-final-proof/`，并保留新版 MP4、SRT 和 `.manju` 项目包。代码验证为全量 422 项通过，后续口型保护及相关回归 87 项通过（当前共 431 个测试用例）；前端构建及提交断网恢复、DAG 引用恢复的浏览器检查通过。

## 多轨剪辑

在画布顶部打开“多轨剪辑”。可以从分镜追加导入视频、配音、字幕及背景音乐轨，也可以从项目素材区直接添加或拖入固定版本素材。导入是追加操作，已有剪辑保留；再次导入会增加一组新轨。

1. 添加视频、音频或文字轨。视频轨同时接受图片；不同视频和文字轨可叠加，轨道顺序决定覆盖层级。
2. 拖动片段安排起点，拖动左右边缘裁剪，在播放头处“分割”；片段可移到兼容轨道，并支持撤销、重做。时间按所选帧率对齐，属性区可以直接输入时间。
3. 选择片段调整位置、缩放、透明度、音量及淡入淡出。文字支持字号、文字颜色、背景和对齐方式；音频与视频原声可选择原音、对白、电话或旁白处理。
4. 可以静音 / 隐藏轨道或片段，也可锁定防止修改。素材始终固定版本，来源产生新版本时需要明确换用。
5. 播放预览、设置输出画幅与帧率、保存，再导出 H.264/AAC MP4。导出保留输入快照，提供进度、失败重试与最终播放器，成功后回收到项目画布和资产库。

预览在浏览器组合媒体，声音预设通过 Web Audio 近似处理；正式导出由 FFmpeg 按帧合成并执行音频滤波、压缩与混音。浏览器字体、文本布局与音频滤波实现可能产生差异，应以导出结果检查最后效果。此版本提供位置、缩放、透明度和淡入淡出，没有关键帧动画、曲线调速、旋转、调色节点或完整转场库。

多轨保存使用共享画布修订号。并发修改返回冲突，不静默覆盖；本机草稿可下载。加载最新版本后恢复旧草稿，会把旧轨道和片段作为新副本追加，保留当前剪辑及备份。性能与同时解码的视频数有关，浏览器预览不能代表任意数量视频轨都能实时播放。

### 多轨 CLI

`timeline inspect` 返回 `revision`、`settings`、`tracks`、`clips`、`total_duration` 和导出任务。轨道有 `type=video/audio/text`、`order`、`muted`、`locked`；片段包括 `track_id`、`start`、`duration`、`trim_start`、只读派生的 `trim_end`、固定 `asset_version_id`、`transform={x,y,scale,opacity}`、`volume`、`fade_in/out`、`audio_preset` 及文字字段。时间单位为秒，位置单位为输出像素；视频 / 图片先等比适配至输出画幅，再整体缩放并定位。

```powershell
$timeline = & $manju timeline inspect --project $projectId --json | ConvertFrom-Json
& $manju timeline import-production --project $projectId --revision $timeline.revision --request-id "ep1-import-v1" --json
& $manju timeline inspect --project $projectId --json | Set-Content -Encoding utf8 "timeline.json"
# 编辑 tracks / clips；保留 revision，修改出点时同步 duration，或省略派生 trim_end。
& $manju timeline apply --project $projectId --file "timeline.json" --request-id "ep1-edit-v1" --json
$timeline = & $manju timeline inspect --project $projectId --json | ConvertFrom-Json
$render = & $manju timeline render --project $projectId --revision $timeline.revision --name "第一集 · 多轨版" --request-id "ep1-timeline-render-v1" --json | ConvertFrom-Json
& $manju timeline wait $render.id --max-wait 1800 --json
& $manju timeline show $render.id --json
# 失败后按同一快照重试：timeline retry RENDER_ID --json
```

隔离资料库的真实 FFmpeg 与浏览器验收覆盖了多轨叠加、文字、图层透明度、混音 / 电话滤波、拖动、跨轨移动、裁剪、分割、锁定、静音、撤销 / 重做、导出回收和冲突草稿恢复，证据在 `.qa/timeline-ui/`。这不替代真实短剧的逐镜审核。

## 画布自动编排

打开“自动编排”，先预检，再开始。编排读取已配置生成卡的真实参考输入，按依赖顺序执行图片、视频、音频和口型任务；普通故事关系线不作为生成依赖。可执行全画布，或从所选节点向下游执行（包含必要上游）。预检会检查缺失素材、工作流能力、循环依赖、锁定与待核对提交。执行记录保存计划、输入快照、各节点任务和输出版本，页面关闭后仍继续运行。

相同配置和固定输入可复用本项目该节点已成功的结果；“强制重做”忽略复用。下游引用本次上游的明确输出版本，不取后来变化的当前版本。失败会阻止依赖它的下游，重试保留已经成功的节点。取消停止安排后续节点，并尽力取消已提交任务；无法取消的运行任务继续跟踪，不会通过终止共享 ComfyUI 来强制清场。已采用的画布素材与新生成候选仍按各卡片的采用规则管理。

```powershell
$plan = & $manju canvas-run plan --project $projectId --scope all --json | ConvertFrom-Json
# 先检查 plan.valid、errors、warnings 和 nodes 中的运行 / 复用决定。
$run = & $manju canvas-run start --project $projectId --scope all --revision $plan.revision --request-id "ep1-canvas-run-v1" --json | ConvertFrom-Json
& $manju canvas-run wait $run.id --max-wait 7200 --json
& $manju canvas-run show $run.id --json
& $manju canvas-run list --project $projectId --json
# 所选节点及下游：plan / start --scope downstream --node NODE_ID（可重复 --node）
# 强制重做：plan / start --force；重试或取消：canvas-run retry / cancel RUN_ID
```

开始执行时应传预检得到的 `revision`；输入或画布变化后重新预检。相同请求重试复用 `request_id`，改变输入使用新编号。CLI 的 `wait` 超时只停止等待，不取消后台任务。自动编排执行的是已配置的生成依赖，不会自行创作剧本、选择最佳候选，也不会自动完成分镜审核与时间线成片导出。

## 本地口型同步（LatentSync 1.5）

画布顶部“口型同步”选择一段固定版本视频和一段准确配音，设置视频起点、片段时长及配音延迟。可自动检测人脸，或在视频上手工框选人物区域；自动模式选择检测到的最大人脸，手工模式限制选择范围并跟踪。设置采样步数、同步强度与种子后提交，进度和原始任务在“生成任务”中可见，结果作为新视频版本回收，保留输入视频。

接口限制片段 0.2–120 秒、10–50 采样步、同步强度 1–3；视频必须覆盖片段，配音加延迟不能溢出。桥接将输入规范到 **25fps**，输出帧数按 `round(duration × 25)` 确定。它使用真实 LatentSync 模型，没有用程序绘制假嘴形，也不会将视频套用 H3 参考图缩放流程。配音已随结果写入音轨，剪辑时注意避免同时播放这条音轨与重复添加的同一份独立配音。

本机桥接源码为 `integrations/comfyui_manju_lipsync`；Comfy 插件的 `runtime.json` 指向独立 Python 环境、LatentSync 代码、模型、YuNet 人脸检测模型与 FFmpeg。当前实际位置为 `.manju/runtimes/latentsync-env311`、`.manju/runtimes/latentsync` 和 `F:/bilitv/ai_models/lipsync/LatentSync-1.5`。模型目录需要 `latentsync_unet.pt`、`whisper/tiny.pt` 及 `vae`；这些本地配置不会随源码自动安装。`lipsync settings` 检查桥接暴露的可用状态，缺失时明确报错。文件就绪不代替一次真实推理验收。

### 口型 CLI

```powershell
& $manju lipsync settings --json
# lipsync.json 中 project_id / version_id 替换为真实固定 ID。
$job = & $manju lipsync create --file "lipsync.json" --request-id "ep1-lipsync-v1" --json | ConvertFrom-Json
& $manju job wait $job.id --max-wait 3600 --json
```

```json
{
  "project_id": "PROJECT_ID",
  "prompt": "人物按本镜配音说话",
  "references": [
    {"id": "video", "role": "video", "version_id": "VIDEO_VERSION_ID"},
    {"id": "audio", "role": "audio", "version_id": "AUDIO_VERSION_ID"}
  ],
  "lip_sync_options": {"video_start": 0, "audio_offset": 0.15, "duration": 5, "face_mode": "auto"},
  "parameters": {"steps": 20, "cfg": 1.5, "seed": 42},
  "result_policy": "review"
}
```

手工模式使用 `face_mode="manual"`、`face_box=[x,y,width,height]`，坐标对应原视频像素，框至少 40×40 且不能超出画面。可加 `source_node_id` 将候选回填到指定视频卡；CLI 自动设置 `kind=video` 和 `workflow_id=builtin-latentsync15-local`。

2026-11-06 的真实首跑已得到入库视频，150ms 配音偏移用 16kHz 波形互相关验证一致。抽样能看到嘴形变化，但动漫侧脸的眼睛、面颊、下颌也被改动，面部有柔化，不能声称变化只发生在嘴部。首次产物多出 2 帧的问题已修复，并以真实 FFmpeg 边界测试验证；原产物作为证据保留。完整数据、同时间画面对照及方法限制保存在本机 `.qa/short-drama-v2/lipsync-proof/report.md`（未随仓库提交）。目前没有逐音素人工标注或 SyncNet 指标，不把音轨时间准确等同于逐字嘴形准确；新的正面近景与 V2 成片仍须单独验收。

## 在画布生成图片

### OpenAI 云端图片

工作流入口统一展示本地 ComfyUI、H3 和 OpenAI 已接入能力。点击“OpenAI 连接与模型”可检查密钥与当前项目可用的图片模型；检查只读取模型列表，不会生成图片。

后端优先读取环境变量 `OPENAI_API_KEY`，否则读取项目根目录中已被 Git 忽略的 `.env.local`。密钥只由本机后端使用，不出现在浏览器响应或生成记录中。

首次配置时可将 [`.env.example`](.env.example) 复制为 `.env.local`，在本机填入自己的密钥后启动服务；已有 `.env.local` 时直接编辑原文件。该文件只用于读取 `OPENAI_API_KEY`，其他运行环境变量请在 PowerShell 中设置。不配置密钥仍可使用本地功能。

在画布图片卡的工作流菜单选择“OpenAI · 文生图 / 参考生图 / 图像编辑”，选择模型、画质和预设或自定义尺寸，填写描述后生成。支持 GPT Image 2.6 Sunburst / Flare、GPT Image 2.5 Sunburst / Flare 和 GPT Image 2；仅允许使用当前项目模型列表中可见的模型。2.5 / 2.6 支持五档画质，GPT Image 2 支持三档。尺寸须为 16 的倍数，长边不超过 3840，宽高比不超过 3:1，面积为 655360–8294400 像素。

提交前实时显示美元计价的**单张图片输出预估**，提示词与参考图输入费用另计。估算算法与价格基准来自 [OpenAI 官方图片计算器](https://developers.openai.com/api/docs/guides/image-generation#calculating-costs)，基准日期 2026-11-06。任务详情保留模型、画质、尺寸、预估及 API 返回用量，并据此计算参考费用，最终账单以平台为准。

参考生图与编辑会将固定版本图片发送给 OpenAI。沿用画布的白改黑保蒙版，后端转换为 API 所需的透明蒙版；每次生成一张，结果写入本地资产库和原卡片候选历史。云端生成在独立线程执行，不阻塞本地任务轮询。已提交的 OpenAI 任务不能撤回；响应中断时不会自动重发，须核对平台用量后结束跟踪。已收到但保存失败的结果优先从本地回执恢复，避免再次生成计费。

### ComfyUI 本地图片

1. 在 ComfyUI 面板连接或启动本地服务，再进入“工作流”页检查 Qwen Image 2.1 Turbo 和 MiniMax H3 Image 模板的本机可用性。检查会核对节点、模型和输入映射。工作台不会自动下载模型或安装插件。
2. 打开项目画布，创建生成卡或选中图片，在卡片下方填写描述，选择文生图、参考生图或图像编辑。工作流和生成参数按需展开。资产库和属性栏默认收起，可通过画布工具按钮打开。内置模板尺寸须为 32 的倍数，MiniMax H3 Image 默认使用 2048×2048。
3. Qwen 接收最多 3 张图，按顺序使用“图1”“图2”。MiniMax H3 Image 的文生图和图像编辑来自 ComfyUI 官方模板，使用 INT8 主模型、共享文本编码器和本地 Qwen3.5 9B 提示词增强。参考生图复用官方多图编辑链路，提示词指定各参考图在目标画面中的作用。编辑以第一张图为底图，最多共输入 16 张图，`@` 素材按顺序映射到 `<Picture 1>`、`<Picture 2>` 等。画布选定的宽高用于实际生成，采样固定 6 步、CFG 1。
4. 输入 `@` 选择图片卡，或将图片卡连接到生成卡，再检查面板中的实际引用列表与顺序。提交使用的是卡片固定的 `asset_version_id`，原件会上传到 ComfyUI，并填入工作流图片输入；这些引用实际参与生成。资产后续新增版本不会改变已提交任务的输入。
5. 支持蒙版的编辑工作流可以绘制或上传蒙版。蒙版尺寸须与第一张底图一致，白色区域修改、黑色区域保留；全黑或有效区域过小的蒙版会被拒绝。内置 GH 节点会扩展、羽化蒙版边缘，模型和 VAE 也可能改变细节，因此不承诺黑色区域的像素完全不变。
6. 结果自动进入本地资产库，并直接显示在当前卡片中，保留卡片位置、大小和描述。重复生成及一次返回多张图片时，图片保存在同一卡片的历史中，可切换查看；不会自动增加派生卡片和连线。原图也保留在历史中。通过 CLI 未指定源卡片，或生成期间源卡片已被移除时，才创建结果卡片。
7. 关闭浏览器不会取消后台生成。在“任务”的“生成任务”页查看提示词、工作流修订、实际参数、固定输入版本、输出和执行错误，也可导出完整生成记录。失败或取消的任务可按原快照重试；正在执行的任务取消时需要明确确认中断。

工作流页支持复制内置模板后修改模型名称、默认参数、描述和图片的节点输入映射，以及 `SaveImage` 输出节点。可保存尚未配置完成的草稿，执行前必须通过校验。导入文件应为 ComfyUI 导出的 **API 格式 JSON**，或工作台导出的工作流 JSON；ComfyUI 界面画布格式需要先转换为 API 格式。导入后会推断常用绑定，但仍应检查提示词、参考图顺序、蒙版和输出是否真正连通。修改工作流不会改变已有生成任务保存的快照。

选中图片后，上方浮动工具条提供图片编辑、参考生图、局部重绘、下载和属性入口；下方创作面板集中显示参考缩略图、描述与常用设置。输入 `@` 可从画布图片、全部资产或主体库选择，描述中的引用会显示图片标签，悬停可看大图。画布图片使用该卡片当前显示的固定版本，同名不同图片会分配可区分的引用名称。删除文字中的显式图片引用会同步解除该引用，文本撤销会恢复它；连线引用与编辑底图仍由缩略图区管理。

“镜头语言、画面风格、光线氛围”提供可编辑的中文描述预设，选择后插入提示词。底部画幅设置提供 1:1、16:9、9:16、4:3、3:4，以及长边 512 像素、1K、2K，面板显示真实宽高；仅在工作流同时绑定宽高时开放。种子、步数、重绘幅度及自定义尺寸在“生成参数”中调整。内置工作流每次输出一张，自定义工作流的输出数量沿用自身配置。

项目包会保留卡片的图片历史、提示词、参考图和蒙版，并重映射导入后的素材版本；复制或导入会清除旧任务的运行状态。自定义工作流定义和生成任务的执行记录不随单个项目包携带，换资料库时需另外导入工作流 JSON，并在卡片上重新选择对应工作流。缺失工作流时会提示处理并阻止生成。完整资料库迁移会一起保留工作流和任务历史。

## 本地目录与迁移

默认资产库为 `D:\ManjuData`，默认配置为 `%APPDATA%\Manju\config.json`。存储设置显示当前路径、占用空间、剩余空间和 FFmpeg 检测结果。

| 位置 | 内容 |
| --- | --- |
| `library.sqlite` 及其 WAL 文件 | 项目、画布、资产版本、工作流、生成记录、任务和事件 |
| `blobs/` | 按 SHA-256 内容哈希保存的媒体原件 |
| `cache/` | 缩略图、可播放预览、音频波形 |
| `temp/` | 上传、项目打包和迁移时的临时文件 |
| 配置文件旁的 `*.migration.json` | 迁移日志与恢复状态 |

在存储设置选择独立的空目录，或使用 `storage migrate`。迁移在后台复制并校验原件和数据库快照，期间写操作进入维护状态。成功后切换配置并继续使用新目录。源目录会保留，可在确认目标资料和项目包可用后自行处理。失败或中断后可通过设置或 CLI 继续、取消迁移。运行中的复制完成或失败后才接受取消操作。

配置文件中的根目录优先。为独立资料库指定 `--data-dir` 和 `--config-file` 后，后续启动继续使用同一配置文件，迁移后的根目录会从配置读取。

```powershell
.\.venv\Scripts\python -m manju serve --data-dir "E:\漫剧素材" --config-file "E:\漫聚配置\config.json"
```

环境变量 `MANJU_DATA_DIR`、`MANJU_CONFIG_FILE` 可提供同样设置。配置文件应放在持久路径。项目备份优先使用 `.manju` 导出，完整资料库的外部复制应在服务退出后进行。

## CLI 与 Agent

安装后可用 `.\.venv\Scripts\manju.exe`，也可用 `python -m manju`。以下示例先定义命令路径。服务应提前运行。

```powershell
$manju = ".\.venv\Scripts\manju.exe"
& $manju doctor --json
$project = & $manju project create --name "末班车" --aspect 9:16 --json | ConvertFrom-Json
$asset = & $manju asset import --file "E:\原画\站台.png" --project $project.id --request-id "station-upload-v1" --json | ConvertFrom-Json
& $manju canvas add-asset --project $project.id --asset-version $asset.imported_version_id --x 100 --y 80 --request-id "station-card-v1" --json
& $manju asset tag $asset.id "场景" "站台" --json
& $manju canvas inspect --project $project.id --json
& $manju project export --project $project.id --output "E:\备份\末班车.manju" --json
```

每条命令支持 `--json`，成功时标准输出为一个完整 JSON 值。错误输出到标准错误，格式为 `{ "error": { "code": "...", "message": "..." } }`，退出码为 1。成功退出码为 0。`--url http://127.0.0.1:8766` 或环境变量 `MANJU_URL` 可连接另一个本机端口。`--timeout` 设置 HTTP 超时秒数。运行 `manju --help` 或某条命令的 `--help` 查看位置参数。

| 命令组 | 可用操作 |
| --- | --- |
| `doctor` | 检查本地健康状态和存储依赖 |
| `project` | `create`、`list`、`get`、`rename`、`duplicate`、`trash`、`restore`、`purge`、`export`、`import`、`link`、`unlink` |
| `asset` | `import`、`list`、`show`、`rename`、`tag`、`version`、`repair`、`trash`、`restore`、`purge`、`reveal` |
| `subject` | `list`、`show`、`create`、`update`、`delete` |
| `canvas` | `inspect`、`add-asset`、`apply`、`render-frame` |
| `production` | `inspect`、`apply`、`generate`、`render`、`show`、`wait`、`retry`、`subtitles`、`handoff` |
| `task` | `list`、`retry` |
| `storage` | `inspect`、`migrate`、`resume`、`cancel` |
| `comfy` | `scan`、`status`、`configure`、`start`、`stop`、`logs` |
| `workflow` | `list`、`get`、`create`、`import`、`update`、`duplicate`、`delete`、`validate` |
| `generate` | 提交图片、视频或人物配音生成；支持参数或 `--file` 完整请求 JSON |
| `job` | `list`、`show`、`wait`、`cancel`、`retry` |

`asset tag ASSET_ID 标签...` 替换完整标签列表，省略标签会清空。`asset version ASSET_ID 文件` 添加版本，`asset version ASSET_ID --select VERSION_ID` 选择已有资产版本。`asset repair ASSET_ID 文件 --version VERSION_ID` 修复缺失原件。`project unlink PROJECT_ID ASSET_ID --remove-nodes` 明确移除对应画布卡片和项目引用。

主体库命令同样使用固定版本，可供 Agent 重复引用：

```powershell
$subject = & $manju subject create --name "角色 · 雪凉" --version $asset.imported_version_id --description "银发、蓝色服装" --request-id "character-v1" --json | ConvertFrom-Json
& $manju subject list --search "雪凉" --json
& $manju subject show $subject.id --json
& $manju subject update $subject.id --description "第一集冬装设定" --json
# 多图按传入顺序保存，首图为封面；版本须为实际导入得到的 ID
& $manju subject update $subject.id --image $frontVersion --image $sideVersion --voice-version $audioVersion --voice-name "雪凉 · 清澈少女音" --voice-transcript "参考音频中实际说出的内容" --json
& $manju subject update $subject.id --clear-voice --json
```

`subject create` 和 `subject update` 支持 `--kind character|scene|prop`；重复 `--image VERSION_ID` 完整设置图片列表。旧的 `subject create --version` 仍可创建单图人物主体。`subject delete SUBJECT_ID` 仅移除库条目，已有画布快照继续保留。用 `canvas apply` 可写入 `type: "subject"` 节点，其 `data.subject` 包含 `kind`、`name`、`description`、`image_version_ids` 和可选音色字段；`data.asset_version_id` 必须等于首图版本，无图时省略。

上传和画布修改支持 `--request-id`。重试时复用相同标识和相同输入，改变输入时使用新标识。`canvas add-asset` 自动读取当前修订号并固定素材版本，稳定请求标识会产生稳定卡片 ID。版本 ID 应显式传入，确保跨次运行的输入一致。

`canvas apply` 使用完整画布 JSON，必须包含读取时的 `revision`。先 inspect，将需改的节点、边和视口写入文件，再提交。返回 `revision_conflict` 时重新读取并合并修改。

```powershell
& $manju canvas inspect $project.id --json | Set-Content -Encoding utf8 canvas.json
# 编辑 canvas.json，保留读取时的 revision
& $manju canvas apply $project.id canvas.json --request-id "layout-v2" --json
& $manju storage migrate "F:\漫聚新素材库" --json
& $manju storage inspect --json
```

`storage migrate` 和 `storage resume` 返回已受理状态。通过 `storage inspect` 查询 `migration.status` 和 `migration.progress`，直到 `completed` 或 `failed`。出现失败时保留错误信息，修复磁盘或目录问题后执行 `storage resume`，需要恢复原目录写入则执行 `storage cancel`。

### Agent 使用工作流与生成任务

先确认本机模板可用。以下命令沿用上面创建的 `$project` 和 `$manju`；如果在新终端执行，请先重新设置它们。文生图成功后，后续生成直接引用返回的固定图片版本。

```powershell
& $manju workflow list --mode text_to_image --json
& $manju workflow validate builtin-qwen21-text_to_image --json
$job = & $manju generate --project $project.id --workflow builtin-qwen21-text_to_image --prompt "二次元蓝发少女，干净线稿，柔和光影" --width 512 --height 512 --steps 8 --seed 42 --request-id "shot-01-text-v1" --json | ConvertFrom-Json
$result = & $manju job wait $job.id --max-wait 1800 --json | ConvertFrom-Json
$versionId = $result.outputs[0].version_id
& $manju job show $job.id --json

& $manju workflow validate builtin-qwen21-reference --json
$referenceJob = & $manju generate --project $project.id --workflow builtin-qwen21-reference --reference $versionId --prompt "保持图1的蓝发角色，将背景改为樱花树下，让她挥手" --width 512 --height 512 --seed 43 --request-id "shot-01-reference-v1" --json | ConvertFrom-Json
& $manju job wait $referenceJob.id --json

& $manju workflow validate builtin-qwen21-edit --json
$editJob = & $manju generate --project $project.id --workflow builtin-qwen21-edit --reference $versionId --prompt "将图1人物的头发改为粉色，保持人物构图" --width 512 --height 512 --seed 44 --request-id "shot-01-edit-v1" --json | ConvertFrom-Json
& $manju job wait $editJob.id --json
& $manju job list --project $project.id --json
```

`--reference VERSION_ID` 可以重复，参数顺序就是图片顺序。蒙版先通过 `asset import` 入库，再将其 `imported_version_id` 传给 `generate --mask VERSION_ID`。`--source-node NODE_ID` 可关联项目中已经保存的生成源卡，`--x` 与 `--y` 必须同时给出，用于指定结果位置。省略种子沿用工作流默认值；默认种子为 `-1` 或显式使用 `--seed -1` 时，会在提交时选定随机整数，并写入任务记录。固定种子范围为 `0` 至 `9007199254740991`，避免网页 JSON 丢失整数精度。参考图、蒙版均使用版本 ID，而非资产 ID 或磁盘路径。

`generate` 返回已保存的任务，后续用 `job show` 或 `job wait` 查询。`job wait` 遇到失败或取消返回非零退出码；等待超时只结束等待，后台任务保留。Agent 应先检查退出码再读取 `outputs`。复用相同 `--request-id` 和相同输入可恢复同一次提交，修改内容须换新标识。失败或取消后可用 `job retry JOB_ID --request-id 新标识 --json` 创建重试任务。`job cancel JOB_ID --json` 取消可安全撤回的任务；需要中断正在运行的本任务时，显式加 `--interrupt-running`，工作台会再次核验 ComfyUI 当前任务身份。状态不确定时先查询核对，不自动重复提交。

通过 CLI 维护工作流时，保留读取到的 `revision` 再更新。内置模板须先复制；`workflow create --file` 接收完整定义，`workflow import --file` 还可接收原始 API 节点图。更新文件和生成请求均支持 UTF-8 JSON。

```powershell
$copy = & $manju workflow duplicate builtin-qwen21-text_to_image --json | ConvertFrom-Json
& $manju workflow get $copy.id --json | Set-Content -Encoding utf8 workflow.json
# 编辑 workflow.json 中的模型、defaults 和 bindings，保留 revision
& $manju workflow update $copy.id --file workflow.json --json
& $manju workflow validate $copy.id --json
& $manju workflow import --file "E:\工作流\角色参考.api.json" --name "角色参考流程" --mode reference --json
# 完整请求 JSON 中填写 project_id、workflow_id、prompt、references 和 parameters
& $manju generate --file generation-request.json --request-id "shot-02-v1" --json
```

## 本地 MiniMax H3 视频创作

左侧工具栏点击 **生成视频**，或右键空白处 → 新建节点 → 视频生成。选中图片后，顶部 **生成视频** 可将图片固定为新视频卡的首帧。选中视频卡会出现底部创作面板。

- **文生视频**：用中文描述画面、人物动作、运镜和声音。
- **首尾帧**：引用一张首帧、尾帧，或各一张；缩略图下可指定用途。
- **全参考**：从画布、资产库或电脑加入图片、视频、音频。输入 `@` 选择素材，人物主体绑定的音色也能选择。图片最多 9 张、视频和音频各最多 3 段，总共最多 12 个；视频、音频每段 2–15 秒，各类总时长不超过 15 秒。参考视频会在本机转换为 24 fps 副本，原件不变。
- 参考连线到视频卡会建立固定版本引用；故事关系线不参与生成。提示词中的引用按类型编译成 H3 的 `<Picture N>`、`<Video N>`、`<Audio N>`，实际送入对应输入节点。
- 默认 480 试作档、4 秒、20 步，支持 16:9 / 9:16 / 1:1 和 768 原生档。尺寸对齐到 32 像素，横屏原生为 1344×768，竖屏为 768×1344；界面显示实际尺寸。
- 时间长度遵循 `17k+5` 帧、24 fps，取不短于所选时长的合法帧数。例如 4 秒为 107 帧，实际约 4.46 秒。面板显示实际时长。
- 默认保留模型生成的声音；取消“声音”输出静音视频。音色参考是生成条件，不保证逐字精确配音或声纹完全一致。
- 完成后直接进入原卡片。空卡采用首个结果，再次生成增加候选；支持播放、原视频预览、采用版本和移出候选。采用版本可以撤销，候选原件仍在资产库中。
- 生成卡片显示点阵等待动画，通过 ComfyUI WebSocket 读取实际执行阶段和当前步骤进度（例如采样 8/20 步）。百分比仅代表当前步骤，不推算整个视频耗时；解码、合成等没有计数的阶段只显示阶段名称。断线重连不会重新提交任务，查询 API 的 `execution_progress` 同样供 CLI / Agent 读取。
- 反复 `@` 同一个版本会复用引用；删除最后一个提及时移除对应手动引用，连线引用保留。旧视频草稿中的同版本、同用途重复引用会合并，首帧和尾帧用途分别保留；已经提交的任务快照不受影响。
- 工作流库的“视频生成”分类统一维护 H3 的五类模型、默认尺寸、步数、CFG、种子、时长和声音。画布视频卡里的“管理工作流”打开同一个配置面板；新建视频卡读取已保存的默认值，已有卡片保持原参数。任务保存模型快照、素材版本、实际节点图与参数。
- “流程与输入”可查看文生、首尾帧、全参考三种模式，并导出同一执行编译器生成的 ComfyUI API 模板。模板中的参考文件名需手动替换；暂不支持将任意视频 JSON 导入、复制为新的生成器。
- `GET /api/workflows?include_video=true` 返回图片与视频工作流目录，省略该参数保持旧图片客户端兼容；`GET /api/video/workflow?mode=text|frames|reference` 返回流程预览。`PUT /api/video/settings` 可同时提交 `models`、`defaults` 和 `revision`，仅更新模型时保留默认参数。

`GET /api/video/settings` 检查模型和节点，`PUT` 更新须携带 `revision`。内置 `builtin-h3-local` 编译官方 H3 节点图，再进行视频/音频解码、保存 MP4、入库和原卡片回写。当前交付只执行本地 ComfyUI；**云端适配尚未实现**，本地失败不会自动上传素材。本地 768 档不等同于云端 2K 增强能力。

Agent 使用同一套服务：

```powershell
manju video status --json
manju generate --kind video --project PROJECT_ID --source-node VIDEO_NODE_ID --prompt "二次元少女向镜头挥手，微风吹动衣摆，轻柔风声" --duration 4 --request-id "shot-video-01" --json
manju generate --kind video --project PROJECT_ID --video-mode frames --first-frame IMAGE_VERSION_ID --last-frame END_IMAGE_VERSION_ID --prompt "从首帧平滑过渡至尾帧" --duration 6 --json
manju generate --kind video --project PROJECT_ID --video-mode reference --reference IMAGE_VERSION_ID --reference VOICE_VERSION_ID --prompt "<Picture 1> 中的人物说话，参考 <Audio 1> 的声音" --json
manju job wait JOB_ID --json
manju video status --json | Set-Content -Encoding utf8 h3-profile.json
# 修改 models，保留 revision
manju video configure --file h3-profile.json --json
```

`--silent` 输出无音轨视频；`--file request.json` 接收完整请求，支持 `prompt_parts`、固定引用 ID、幂等 `request_id`。视频默认 `result_policy: review`。任务查询、取消、重试与图片共用 `job` 命令。项目包保留视频候选、音频参考和草稿，导入后清除旧任务标识，模型配置沿用目标资料库。

实现参照 [ComfyUI 官方 H3 教程](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native)、[H3 模型说明](https://huggingface.co/MiniMaxAI/MiniMax-H3)、[社区 H3 Director](https://github.com/AIMixer/ComfyUI_MiniMaxH3_Director) 与 [社区无限画布](https://github.com/meta-sota/infinite-canvas-minimax-h3)。采用显式参考用途、原卡片候选和固定素材版本的交互方式，任务仍由本项目的持久化队列与资产系统管理。

### H3 输入与采样修正（流程修订 2）

默认使用 `res_multistep / simple / 20 steps / CFG 1`。旧资料库中原封不动的 CFG 4、20 步默认预设会迁移到 CFG 1；其他自定义默认参数保留。已有卡片和完成任务不改写，旧卡可点击“改用 H3 推荐配置”，或在创作设置中“恢复 H3 推荐采样”。这不是质量保证：模型、参考构图和提示词仍会影响结果。

每个视频参考缩略图下方的“设置”可以维护：

- 图片裁切范围与实际输入预览。三视图可快速选择左、中、右单个视角，也可输入百分比微调。原件不变，上传的是规范化副本。
- 首尾帧使用“完整保留·留边”或“填满画面·居中裁切”，避免两个端点使用不同的隐式缩放规则。
- 人物身份、场景构图、动作、声音等用途。人物用途会补入“同一角色、不复制多视图排版”的文字约束，不代表模型具备硬性身份锁定。
- 音视频片段的开始、结束时间。选段为 2–15 秒，视频片段不能长于生成视频；不再静默截断超长参考。可从更长的原件截取一段。
- 视频原声默认不参与参考，可单独开启。“参考原声”控制输入，“生成声音”控制输出，互不代替。

参考图处理长边默认 1024，通过独立 `ImageScaleToMaxDimension` 节点送入官方 `max` 参考管线；也可选择 1280、1536、跟随输出面积或官方高保真（短边上限 2048）。这控制参考编码输入，不会把 480 输出变成 2K。低分辨率原件也不会因此获得新细节。

服务端按固定版本、用途、裁切和片段合并完全相同的引用，同时重写结构化引用及旧文本别名。相同版本分别作为首帧和尾帧仍合法。编号按实际输入编译：视频原声占用前面的 Audio 槽位，独立音频随后编号；任务的 `reference_slots` 可核对映射。

工作流库的 H3 管理页可查看、导出“原生基线”和“Director 外接镜头组”。画布视频模型菜单选择执行流程；两者共用素材控件、队列、真实进度和原卡片候选。Director 当前是一张卡对应一个外接镜头组，尚无跨卡自动编排或连续镜头缓存；已生成的片段可在“分镜成片”中排序、裁剪并合成整片。节点未安装时明确不可用，不自动切换引擎。Director 的声音槽位最多 3 个（包含参考视频原声），超限可改用原生基线。

CLI 同样支持流程选择：

```powershell
manju generate --kind video --project PROJECT_ID --video-engine director --first-frame IMAGE_VERSION_ID --prompt "少女缓缓回头，镜头保持稳定" --ref-image-size 1024 --duration 4 --silent --json
```

复杂参考控制使用 `manju generate --file request.json --json`。请求片段示例（还需填写 project_id、prompt 等必填项）：

```json
{
  "kind": "video",
  "workflow_id": "builtin-h3-local",
  "video_mode": "reference",
  "video_options": {"engine": "native", "sampler": "res_multistep", "scheduler": "simple", "ref_image_size": "1024"},
  "references": [{"id": "hero", "version_id": "IMAGE_VERSION_ID", "purpose": "identity", "crop": {"x": 0, "y": 0, "width": 0.3333333333, "height": 1}, "fit": "contain"}],
  "prompt_parts": [{"type": "reference", "reference_id": "hero"}, {"type": "text", "text": " 在雨夜街道缓缓回头。"}],
  "parameters": {"width": 864, "height": 480, "steps": 20, "cfg": 1, "seed": 339787336},
  "duration": 4,
  "audio": false
}
```

音视频参考可设置 `clip_start`、`clip_end`（秒），视频另有 `use_audio`。`GET /api/video/workflow?mode=reference&engine=director` 导出实际编译模板；文件占位符需要替换为处理好的素材。裁切、片段、具体版本、参数、编译描述与生成图保存在任务中。

创作建议：先用 Qwen 制作符合镜头构图的图片，再用 H3 首帧模式制作动作。独立人物配音已接入 IndexTTS 2.5；Wan Animate 动作迁移及 Wan 5B 是后续适配方向，目前没有作为可执行引擎交付；不会因为本机存在模型文件就显示为已接入。

2026-11-06 本机验收：使用之前失败案例的三视图，选左侧单个人物，添加身份用途，按上述基线生成 864×480、20 步、107 帧的真实视频。逐帧检查确认主角不再复制成三视图排版，背景变为霓虹街道，并完成转身动作；雨感较弱、面部细节仍受 480 档限制。这是输入与采样组合修正的结果，不能据此单独归因于某个参数。证据保存在 `.qa/video-diagnosis/corrected-result.mp4`、`corrected-frames.jpg` 和 `quality-test-result.json`。Director 另以 256×256、1 步真实任务验证外接组执行与 MP4 入库，仅证明链路可运行。

本机 RTX 5060 Ti 16GB 已实际验证文生、首帧、图片/视频/音频混合参考，输出包含 H.264、24 fps 和 32 kHz 音轨；浏览器验证生成期间的草稿保存和原卡片更新。验收使用 256×256、1 步最小诊断任务，只证明执行与回收链路，**不代表成片画质、768 档显存占用或长片段耗时已验收**。

## 管理本机 ComfyUI

在工作台的 ComfyUI 面板中扫描安装目录、选择安装和端口，然后启动。工作台读取 ComfyUI 状态并提供最近日志。已有安装可使用便携版或带独立 Python 环境的目录，扫描结果会显示实际识别到的路径。准备环境和模型时，沿用该安装本身的配置。

CLI 使用同一套配置和进程状态。以下路径作为示例，替换为扫描返回的安装路径。

```powershell
& $manju comfy scan --json
& $manju comfy scan --path "E:\AI 工具" --json
& $manju comfy configure --installation-path "E:\AI 工具\ComfyUI_windows_portable" --port 8188 --json
& $manju comfy start --json
& $manju comfy status --json
& $manju comfy logs --limit 200 --json
& $manju comfy stop --json
```

启动和停止会返回已受理状态，随后查询 `comfy status`，查看 `starting`、`running`、`stopped` 或错误详情。重复启动复用已运行的实例。工作台只会停止自己启动并验证过进程身份的实例，已有外部实例会显示 `external`。若队列仍有任务，普通停止返回 `comfy_queue_busy`，确认要中断这些任务后可显式执行 `comfy stop --force --json`。`comfy logs` 的 `limit` 最多为 1000 行。

ComfyUI 管理配置、进程记录和日志放在工作台配置文件旁的 `<配置文件名去扩展名>.comfy` 目录。例如默认目录为 `%APPDATA%\Manju\config.comfy`，其中包含 `settings.json`、`process.json` 和 `logs/`。素材库迁移会保留这个独立运行目录的位置。

## 开发与仓库结构

| 路径 | 职责 |
| --- | --- |
| `backend/manju/` | FastAPI 服务、SQLite/媒体存储、CLI、工作流与生成、分镜、时间线和自动编排 |
| `frontend/src/` | React 19 + TypeScript 界面、React Flow 画布、素材/主体管理与各类创作面板 |
| `integrations/comfyui_manju_speech/` | IndexTTS 2.5 ComfyUI 桥接节点与独立推理 worker |
| `integrations/comfyui_manju_lipsync/` | LatentSync ComfyUI 桥接节点与独立推理 worker |
| `scripts/` | 语音模型下载校验与语音桥接节点安装工具 |
| `tests/` | API、CLI、资产版本、生成恢复、剪辑与桥接逻辑的自动测试 |
| `start.vbs` / `start.cmd` / `start.ps1` | Windows 隐藏服务启动、配置锚点与日志入口 |
| `pyproject.toml` / `requirements.lock` | Python 包声明与已验证依赖约束 |
| `frontend/package-lock.json` | 前端依赖锁定文件 |

前端开发时，在一个终端运行后端，在另一个终端运行 Vite：

```powershell
# 终端 1：隔离开发资料库，避免修改日常素材。
.\.venv\Scripts\python -m manju serve --data-dir ".manju/dev-data" --config-file ".manju/dev-config.json"
# 终端 2：打开 Vite 输出的本机地址，默认 http://127.0.0.1:5173。
npm --prefix frontend run dev
```

Vite 将 `/api` 代理到 `http://127.0.0.1:8765`，前端热更新使用这条开发链路。改动后运行下文的测试与构建；日常启动器使用 `frontend/dist/`，需要重新构建才能看到界面修改。

提交代码时同步更新受影响的 README 功能、依赖、CLI/API 示例与限制说明；真实模型验收需记录日期、输入条件和实际结果。`.env` / `.env.*`（除 `.env.example`）、`.venv/`、`node_modules/`、前端构建、`.manju/` 与 `.qa/` 均不提交。

## API 与验证

服务运行后可在 `http://127.0.0.1:8765/docs` 查看 OpenAPI。HTTP API 提供 `/api/projects`、`/api/assets`、`/api/subjects`、`/api/projects/{id}/canvas`、`/api/tasks`、`/api/settings/storage`、`/api/comfy`、`/api/workflows` 和 `/api/generations`；`/api/projects/{id}/production` 提供分镜读取/保存、批量生成、字幕和剪辑包，`/api/production/renders/{job_id}` 查询分镜及时间线成片任务。`/api/projects/{id}/timeline` 管理多轨剪辑，`/api/projects/{id}/canvas-runs` 提交和查询画布编排；`/api/video/settings`、`/api/audio/settings`、`/api/voice-design/settings`、`/api/lipsync/settings` 与 `/api/openai/images` 提供对应能力的配置或状态。媒体通过 `/api/media/{version_id}` 提供 GET、HEAD 和 Range 读取，`/api/events` 提供 SSE 事件。浏览器请求限定同源，本地服务绑定 `127.0.0.1`。

测试全部使用临时资产目录和配置文件。CLI 测试启动独立临时端口。测试覆盖去重、同名异内容、旧版本固定、项目引用保护、软删与永久删除、幂等与修订冲突、项目包往返与恶意包、中文路径迁移和恢复、失败重试、媒体损坏、Range 以及 CLI JSON/退出码。音频实际转码用本机 FFmpeg，环境缺失时该项测试标记跳过。

```powershell
.\.venv\Scripts\python -m pytest -q
npm --prefix frontend run build
```

2026-11-07 仓库初始化验证：在现有 Windows 开发环境执行上述命令，后端 **444 项测试全部通过**（257.91 秒），前端 TypeScript 检查与 Vite 生产构建通过。测试保留 1 条 Starlette TestClient / httpx 弃用提示，构建提示部分分包超过 500 kB，均未导致失败。本次验证范围为自动测试和构建；真实模型与浏览器交互的历史验收范围见各章节。

本机历史验收包含自动测试及 Edge 浏览器交互检查。较早的画布性能基线为：以 1920×1080 窗口持续平移 200 张卡片、300 条关系线 10.05 秒，320 个采样帧的 p95 为 31.6 毫秒。环境为 Ryzen 7 9700X、32 GB 内存、Edge 无头模式。测试含 30 张图片卡、10 张视频海报和 10 张音频卡，每类媒体复用一个测试素材版本，其余为文字卡。该数据记录于本次视区裁剪优化之前，不作为当前性能上限；大体积独立素材的加载耗时仍随文件和硬件情况变化。

ComfyUI 已通过本机便携版的实际验收：从画布扫描并选择安装、启动至就绪、重启工作台后接管同一进程、通过网页停止并释放端口。1920×1080 与 1366×768 下检查了管理面板、长日志滚动和错误反馈。启动耗时取决于现有插件与运行环境。自动测试另覆盖进程身份失效、外部实例保护、队列忙时确认、停止中重启恢复，以及资料库迁移期间持续写入日志的场景。

图片生成已通过本机 Qwen Image 2.1 的三项真实 512×512 工作流验收：中文文生图生成蓝发角色，参考生图更换樱花背景并挥手，指令编辑改为粉发。输出均回收到本地资产库与项目画布。工作流维护页还通过了中文复制、模型与参数修改、错误绑定校验、修复、JSON 导出再导入及删除的浏览器验收；无效 JSON 会保留原文并显示错误。生成效果与耗时取决于模型、提示词、插件和硬件，图片验收仅覆盖上述图片流程；视频、配音和分镜成片各自的验收范围见对应章节。

真实网页验收还覆盖：鼠标拉线并用 `@` 引入第二张图片后生成樱花持花图；在原图上绘制 512×512 蒙版，将胸前红色蝴蝶结改为绿色；任务的实际输入版本、参数、工作流快照和结果均能在任务页查看并导出 JSON。另有浏览器回归检查中文输入法、引用数量限制、错误反馈、未知提交状态防重复、撤销和复制。

原位生成改造后，又通过了同一卡片连续参考生图和银白发色编辑的真实验收：画布保持 3 个节点、2 条参考线，位置尺寸不变，生成期间修改的描述得以保留，两张历史图片可切换且刷新后恢复。1920 / 1366 下检查了精简面板、折叠侧栏和历史操作；小窗口首次选中可适度平移以容纳卡片与输入框，之后的手动平移不被任务状态更新拉回。旧版已经生成的独立卡片不会被自动删除。

### 画布引用与候选结果

- 连线明确区分“图片参考”和“故事关系”。旧连线先确认用途；故事关系不影响生成输入。右键连线可以切换用途，锁定节点的连线不能删除或改接。把输出端口拖到空白处，可创建带引用的新图片卡或关系文字卡；缩小到 35% 时端口仍保留约 24 像素点击区域。
- 图片参考固定具体版本。来源换图、改名或移除，不会悄悄改变已保存的输入。来源更新时可以先对比再更新引用；主体副图只要仍在来源中，不会因为封面不同而误报更新。
- 主体名称和描述可以在卡片内编辑；多图和人物音色在侧边编辑器管理。“从画布选择”支持直接点选图片、主体或音频。节点标题与主体名称分别保存。
- 网页生成采用候选模式：空卡首次自动采用第一张结果；后续结果留在同一卡片内，支持预览、对比、采用、继续修改和移除候选。候选和编辑底图均参与引用保护及项目包导入导出。
- 切换工作流保留参数草稿，仅提交当前工作流已绑定的参数。Qwen GH 编码器不支持的负面提示词控件不显示。自定义工作流须声明图片编号映射能力，才允许结构化主体引用。

Agent 可以继续使用 manju generate --file request.json --json。完整请求可设置 "result_policy": "review"；旧请求省略该字段仍沿用原有替换行为。references 中每张图可携带稳定的 id、version_id、title、description 和 use_description。prompt_parts 使用 {"type":"text","text":"..."} 或 {"type":"reference","reference_id":"角色ID"}，服务端按实际上传顺序编译成参考图编号，任务中的 compiled_prompt 可供检查。node_id 只记录来源，图片身份始终由 version_id 决定。自定义工作流的 capabilities.reference_mapping 可选 numbered 或 unsupported。

本次真实 Qwen 验收包括双主体左右构图、调换上传顺序后保持主体左右关系，以及白改黑保蒙版将蓝发角色胸前蝴蝶结改为绿色。三次结果均进入原卡候选历史，没有增加节点。浏览器验收覆盖候选采用/撤销、旧线确认、主体改名、固定参考更新、侧栏画布选图、空白处拉线创建及 860 像素窗口。角色一致性仍取决于模型与参考图，不能保证每次生成完全一致。




## 本地人物配音（IndexTTS 2.5）

1. 人物主体右上角的音色按钮 → 从电脑、资产库或画布绑定一份 **2–30 秒清晰单人音频**。
2. 同一音色菜单点击 **用此音色生成配音**。也可以从工具栏或空白处右键新建 **人物配音**，再通过 `@`、音色选择器或主体连线添加音色。
3. 在卡片下方填写实际台词。音色参考决定说话人的声音；情绪可选预设、演绎文本或第二份 **2–30 秒情绪参考音频**，演绎文本与情绪参考互斥。参数面板可调整强度、语言、语速、发音纠正、句间附加停顿、质量、采样温度及种子。参考音频原文不必与台词相同，`@人物` 引用名称不会被朗读。
4. 点击生成，结果直接回到该音频卡，并入库到当前资料库。再次生成增加候选，保留已采用版本；可对比试听原音色、情绪参考与多个生成候选，同时只播放一条音频，并支持原件预览、版本切换及下载。
5. 工作流页的 **人物配音** 分类管理 IndexTTS 可用状态和默认参数，可导出真实 ComfyUI API 图。默认参数只影响新建卡片，已有草稿与任务保留自己的设置。

语音与图片、视频共用 `/api/generations`、ComfyUI 执行队列、任务面板、取消/重试、请求去重及固定素材版本。不会把生成结果放到另一个自动连接的新节点。参考素材的悬浮、试听、选择器、中文输入法、自动保存与卡片锚定面板复用现有组件。

每次提交记录音色原件版本及哈希、人物快照、实际台词、模型、随机种子、语言、语速与情绪。人物后来改绑音色不影响已提交任务；重新绑定到新卡片才采用新版本。音色可单独用于不同项目，删除画布卡不删除原件。配音输出为无损音频；参考音色与台词不上传云端。

当前接入的引擎是 [IndexTTS 2.5 官方实现](https://github.com/index-tts/index-tts)，模型来自 [IndexTeam/IndexTTS-2.5](https://huggingface.co/IndexTeam/IndexTTS-2.5)。支持中文、英语、日语、西班牙语和阿拉伯语。单次台词最多 2000 字，建议按镜头分段。语速映射到模型的 duration_factor，不能保证精确时长。自然度、音色相似度与表演效果仍取决于参考音频和模型；生成的独立声音可在分镜或多轨时间线混音，也可作为 LatentSync 的口型驱动。

“录音室”质量实际使用 40 个 CFM 步，“标准”使用 25 步；更多步数增加计算量，不保证每句更自然。句间附加停顿为 0–1500ms：按句号、问号、叹号、分号及换行分句，分别生成后插入指定长度的 PCM 静音，保留自然句尾与原音量动态；不能据此消除原有呼吸或逗号停顿。发音纠正每行填写如 `末班车=MO4 BAN1 CHE1`，原台词保留，任务的 `compiled_prompt` 可查看实际拼音标记。

情绪强度在三种模式都有效；文本演绎建议从不超过 0.6 开始复核，文本只映射模型支持的情绪控制，不能承诺遵从所有表演指令。工作流能力检查区分情绪文本模型缺失与其它能力，缺少该模型时仍可使用音色、预设和情绪音频。旧桥接节点不支持新参数时，界面明确提示更新，不显示“录音室”却悄悄按旧步数生成。相关隔离浏览器验证见 `.qa/speech-ui/`，实际台词仍需试听及发音复核。

### 运行环境与安装

Comfy 节点 `ManjuIndexTTS25` 只负责输入、队列和回收；推理使用独立 Python 3.11 + PyTorch 2.8 CUDA 12.8 环境，不替换 ComfyUI 的 Python 包。开始语音任务时释放 Comfy 缓存模型，完成或取消时退出隐藏的推理进程、释放显存。下一次图片/视频任务按需重新加载模型，没有常驻命令行窗口。

本次安装位置：

- 运行代码：`.manju/runtimes/index-tts`，官方提交 `d9e41aac89fd00b3d71497fddb287b7f24613712`。
- 模型：`F:/bilitv/ai_models/tts/IndexTTS-2.5`；`manju-models.json` 保存仓库提交、文件大小及 SHA-256。
- Comfy 插件：`custom_nodes/comfyui_manju_speech`，本地 `runtime.json` 指向独立环境及模型目录。
- 插件源码：`integrations/comfyui_manju_speech`；安装不改动 H3/Qwen 节点和依赖。

迁移到其他电脑时，在仓库根目录用 Python 3.12 环境中的 `uv` 安装独立环境（需要提前安装 uv）。首次安装需联网；模型与依赖准备好后可本地运行：

```powershell
git clone https://github.com/index-tts/index-tts.git .manju/runtimes/index-tts
git -C .manju/runtimes/index-tts checkout d9e41aac89fd00b3d71497fddb287b7f24613712
$env:UV_PYTHON_INSTALL_DIR = "$PWD/.manju/python"
.venv/Scripts/uv.exe sync --project .manju/runtimes/index-tts --python 3.11 --no-dev --cache-dir "$PWD/.manju/uv-cache"
.venv/Scripts/python.exe scripts/install_speech_models.py --directory F:/bilitv/ai_models/tts/IndexTTS-2.5
.venv/Scripts/python.exe scripts/install_speech_bridge.py --comfy D:/github/ai_draw/ComfyUI_windows_portable/ComfyUI --runtime D:/github/ai_go_play/.manju/runtimes/index-tts --models F:/bilitv/ai_models/tts/IndexTTS-2.5
```

安装后等待 Comfy 队列空闲，再通过工作台停止、启动 ComfyUI。工作流页检查成功才允许提交。没有完整模型或未加载桥接节点时明确显示缺项，不会自动使用云端替代。

### CLI / Agent

```powershell
$manju = ".venv/Scripts/manju.exe"
& $manju workflow list --mode audio --json
& $manju workflow get builtin-indextts25-local --json
& $manju workflow validate builtin-indextts25-local --json
& $manju generate --kind audio --project <项目ID> --subject-node <人物节点ID> --source-node <音频卡ID> --prompt "别担心，我会一直陪着你。" --language zh --speed 1 --emotion calm --emotion-intensity 0.5 --seed 42 --request-id "ep1-line1-v1" --json
# 也可 --reference <固定音频版本ID>，代替 --subject-node；不传 --source-node 时创建音频结果卡。
& $manju job wait <任务ID> --json
```

完整 JSON 请求可以使用 `generate --file request.json`。`kind=audio`、`workflow_id=builtin-indextts25-local`，其它任务字段沿用图片、视频契约。参考列表首项为 `role="voice"`，第二项可为 `role="emotion"`，两者均指定 `media_type="audio"` 和固定 `version_id`；旧请求无角色时按先音色、后情绪兼容。

```json
{
  "language": "zh",
  "speed": 1,
  "emotion": "calm",
  "intensity": 0.5,
  "use_emo_text": false,
  "emo_text": "",
  "pronunciation": "末班车=MO4 BAN1 CHE1",
  "interval_silence": 200,
  "quality": "studio",
  "temperature": 0.8
}
```

上面是请求中的 `speech_options` 对象。`quality` 可为 `standard/studio`，`temperature` 范围 0.5–1.2；`use_emo_text=true` 时填写 `emo_text`，且不附加情绪音频。`GET/PUT /api/audio/settings` 与工作流 GET/PUT/validate 共享同一配置，修订过期返回 409，返回的 `profile.capabilities` 表示本机节点实际支持的扩展能力。

2026-11-06 本机验收：独立测试资料库中使用官方示例音色生成中文台词，随后通过浏览器从主体创建配音卡、真实提交、播放、改变语速/情绪再次生成、在原卡片试听候选均通过。首次冷启动约 73 秒，后续短句约 37 秒（含独立进程模型加载）；不代表所有台词耗时。原始任务与截图保存在 `.qa/speech-acceptance`，测试素材未导入用户资料库。

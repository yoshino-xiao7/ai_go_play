# 贡献指南 (Contributing to ai-go-play)

感谢你关注并愿意为 **ai-go-play** 贡献力量！

ai-go-play 的核心哲学是 **「AI to AI 的创作方式，人作为观众，作为领导去指挥 AI 创作」**。我们致力于打造一个将人类宏观创意与自主多 Agent / 多模型深度流水线无缝结合的下一代无限画布创作系统。

无论是报告 Bug、改进文档、提出新特性，还是提交代码合并请求（PR），我们都热烈欢迎社区开发者的参与。

---

## 目录

1. [行为准则](#行为准则)
2. [本地开发环境搭建](#本地开发环境搭建)
3. [项目架构目录](#项目架构目录)
4. [分支规范与 Commit 约定](#分支规范与-commit-约定)
5. [开发与构建验证](#开发与构建验证)
6. [提交 Pull Request 流程](#提交-pull-request-流程)
7. [报告 Bug 与建议新功能](#报告-bug-与建议新功能)

---

## 行为准则

作为开源项目的参与者与维护者，我们承诺营造一个包容、友善、专业且无歧视的协作环境。请在讨论、Issue 与 Review 中始终保持互相尊重与建设性沟通。

---

## 本地开发环境搭建

### 运行环境要求
- **操作系统**：Windows 10 / 11（推荐），Linux / macOS（CLI 与基础能力实验支持）
- **Python**：>= 3.10（官方生产与测试锁定推荐 Python 3.12）
- **Node.js**：>= 20（推荐 Node.js 22 LTS）与 npm >= 10
- **外部多媒体工具**：系统环境变量中需包含 `ffmpeg` 与 `ffprobe`
- **本地 AI 推理**（可选）：本地 NVIDIA GPU（显存 >= 8GB 推荐）与已配置好的 ComfyUI 服务

### 1. 克隆代码仓库
```bash
git clone https://github.com/yoshino-xiao7/ai_go_play.git
cd ai_go_play
```

### 2. 配置 Python 虚拟环境与依赖
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -c requirements.lock -e ".[dev]"
```

### 3. 安装前端依赖
```powershell
npm --prefix frontend ci
```

---

## 项目架构目录

```text
ai_go_play/
├── backend/
│   ├── manju/                  # 核心后端模块 (FastAPI + 本地 SQLite + 本地存储)
│   │   ├── app.py              # HTTP 路由与生命周期管理
│   │   ├── generation.py       # 多模型任务调度引擎与状态机
│   │   ├── orchestration.py    # 画布依赖拓扑解析与 AI 编排管线
│   │   ├── screenplay.py       # 智能剧本故事板与即梦格式解析
│   │   ├── share.py            # 亦可 (Setu) 云端画布生态桥接
│   │   ├── video_enhance.py    # 视频后期管线 (Real-ESRGAN/Anime6B 超分, RIFE 补帧)
│   │   ├── lipsync.py          # LatentSync 1.5 口型同步调度器
│   │   └── watermark.py        # 视频水印智能消除服务
├── frontend/
│   ├── src/                    # React 19 + TypeScript + Vite 前端
│   │   ├── Canvas.tsx          # 核心无限节点画布引擎 (@xyflow/react)
│   │   ├── Workflows.tsx       # 全景工作流能力矩阵与专属管线
│   │   ├── ScreenplayWorkspace.tsx # 剧本故事板与分镜解析工作区
│   │   ├── LipSyncPanel.tsx    # LatentSync 专属口型对齐面板
│   │   ├── VideoEnhanceComposer.tsx # 视频超分/补帧/去水印交互面板
│   │   ├── VoiceDesignDialog.tsx # MiniMax H3 原生音色特征设计对话框
│   │   └── SharePanel.tsx      # 云端发布、B站成片关联与云端 Hub 互通
│   └── package.json
├── start.cmd / start.ps1       # Windows 一键无窗口极速启动器
├── requirements.lock           # 生产已锁定 Python 依赖版本
└── pyproject.toml              # 项目打包与元数据配置
```

---

## 分支规范与 Commit 约定

### 分支管理
- `main`：稳定主分支，对应最新可用发布版本。
- 功能分支命名推荐：
  - `feat/feature-name`：新功能开发
  - `fix/bug-description`：Bug 修复
  - `refactor/optimization`：重构或优化
  - `docs/doc-update`：文档完善

### Commit 提交信息规范 (Conventional Commits)
请遵循如下标准格式：
```text
<type>(<scope>): <subject>
```
例如：
- `feat(workflows): add LatentSync 1.5 pipeline card and diagnostics`
- `fix(canvas): prevent edge highlight on non-reference connections`
- `docs(readme): add AI-to-AI philosophy diagram and quickstart guide`
- `refactor(share): harmonize Yike account connection status in sidebar`

---

## 开发与构建验证

在提交任何更改之前，请确保本地通过以下校验：

### 1. 前端类型检查与构建
```powershell
npm --prefix frontend run build
```
确保 TypeScript 没有报错，且产物正常编译至 `frontend/dist`。

### 2. 后端语法与启动验证
```powershell
.\.venv\Scripts\python -m manju serve --port 8765
```
访问 `http://127.0.0.1:8765/api/health` 确保返回：
```json
{
  "ok": true,
  "version": "...",
  "root": "..."
}
```

---

## 提交 Pull Request 流程

1. **Fork 本仓库** 到你自己的 GitHub 账号；
2. 在你 Fork 的仓库中创建独立的特性分支；
3. 遵循代码风格完成修改并编写必要的测试或验收证据；
4. 运行 `npm run build` 和后端检查验证无误；
5. 提交 PR 到主仓库的 `main` 分支，并在 PR 描述中清晰说明修改目的、影响范围以及自测截图或用例。

---

## 报告 Bug 与建议新功能

- **报告 Bug**：请在 Issue 中提供操作系统、Python/Node 版本、错误日志（如 `%LOCALAPPDATA%\Manju\run\server-*.err.log`）以及能复现问题的步骤。
- **功能建议**：请阐述你的使用场景、痛点，以及该功能如何契合「人作为导演、AI to AI 协作」的核心创作流。

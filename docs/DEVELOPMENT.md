# 开发环境

## 前置条件

Python 3.12 为锁定依赖及 CI 基准，包要求 3.12+；Node.js 22.12+、npm、PATH 中的 FFmpeg / FFprobe。Windows x64 为一键安装和 CI 目标；GPU、模型和节点仅在本地生成验收时必需。

## 初始化

```powershell
git switch dev
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -c requirements.lock -e ".[dev]"
npm --prefix frontend ci
npm --prefix frontend run build
git config --local core.hooksPath .githooks
```

社区贡献者在自己的 fork 任务分支工作，将 dev 替换为对应分支。不能用生产资料库测试代码。

## 隔离启动

在仓库根目录打开终端一：

```powershell
.\.venv\Scripts\python -m manju serve --port 8780 --data-dir "$PWD\.qa\dev-data" --config-file "$PWD\.qa\dev-config.json"
```

访问 http://127.0.0.1:8780 使用已构建界面。需要热更新时打开终端二：

```powershell
$env:MANJU_DEV_API = 'http://127.0.0.1:8780'
npm --prefix frontend run dev
```

Vite 默认代理 8765，显式设置 MANJU_DEV_API 可避免误操作正式服务；浏览器地址以 Vite 输出为准。资料库和配置必须与生产隔离。

## 日常工作

维护者在本地 dev 更新 integration 基线、实现修改并提交，推送 dev 后向 integration 提 PR。社区在自己的 fork 实现修改，向上游 integration 提 PR。执行相关测试并同步文档。UI 修改验证实际交互；任务修改验证失败、取消、重试和重启；存储修改验证迁移、兼容与回退。详见 [测试手册](TESTING.md)。

frontend/dist、.qa、.manju、虚拟环境、真实模型、个人素材和令牌不进入 Git。创作可使用 dev，但实验修改应使用独立数据目录。

依赖更新同步锁文件并解释原因，不顺带升级整套推理环境。语音与口型环境保持隔离。版本由维护者明确选择，通过 `python scripts/set_version.py X.Y.Z --write` 准备；该操作不会发布、打标签或自动把验收改为通过。

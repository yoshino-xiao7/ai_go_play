# 测试与验收

| 层次 | 内容 | 是否代表 GPU 实测 |
| --- | --- | --- |
| 单元 / API | 状态、事务、路径、错误与协议 | 否 |
| 类型与构建 | TypeScript、打包、锁文件 | 否 |
| 浏览器 | 交互、保存、恢复、播放、窄屏 | 否 |
| 隔离安装 | 空环境、中文路径、重试、包完整性 | 否 |
| 实际生成 | 指定模型、节点、参数及真实输出 | 仅覆盖实际用例 |

## 命令

```powershell
.\.venv\Scripts\python -m pytest -q
npm --prefix frontend ci
npm --prefix frontend run build
node --test tests/governance.test.cjs
.\.venv\Scripts\python scripts/check_docs.py
.\.venv\Scripts\python scripts/check_release.py
```

CI quality 在 Windows、Python 3.12、Node 22 上执行，准备 FFmpeg，不持有用户资料库、模型或云端账户，不把模拟调用算作 GPU 验收。

## 按修改选取证据

画布覆盖拖动、保存失败、冲突、草稿、撤销和大节点规模；存储覆盖重复请求、并发、路径和迁移；安装覆盖缺依赖、取消和恢复；退出覆盖任务拒绝、进程归属、端口和数据保留；治理覆盖错误目标、伪装分支、非所有者、过期 SHA 和错误版本；发布覆盖候选 SHA、ZIP 内容、校验值与旧版本不可覆盖。

## GPU 验收

先等待现有创作任务完成，再使用隔离资料库和验收项目。记录模型哈希、节点版本、参数、硬件、输入、输出、耗时和失败原因。验证解码、时长、音轨、浏览器播放；自动逐帧检测不能替代视觉审阅。

历史结果见 [生成验收](../release/GENERATION-VALIDATION.md)，当前候选须重测受影响范围。失败应修复或阻断，跳过写明原因；不能把未执行项标为通过。

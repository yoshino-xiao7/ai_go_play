# 贡献指南

唯一集成入口为 **integration**。普通贡献不要向 main 或 dev 提交 PR；main 只接收所有者确认版本的发布 PR。完整规则见 [治理规范](docs/GOVERNANCE.md)。

## 社区贡献

1. fork 上游 main，在自己的 fork 中创建任务分支。
2. 完成范围明确的修改，执行相关测试并记录结果。
3. 推送到自己的 fork，创建 PR 时将上游目标改为 **integration**。
4. 等待维护者审查，处理反馈；新增提交后重新确认审核。

```bash
git clone https://github.com/YOUR_ACCOUNT/ai_go_play.git
cd ai_go_play
git remote add upstream https://github.com/yoshino-xiao7/ai_go_play.git
git fetch upstream
git switch -c feat/short-description upstream/main
# 修改、测试、提交
git push -u origin feat/short-description
# PR: base repository = yoshino-xiao7/ai_go_play, base = integration
```

fork 源于 main，审查目标仍是 integration。如有冲突，按维护者意见在自己的功能分支合并 upstream/integration、解决冲突并重测，不直接推送上游集成分支。

## 维护者开发

```bash
git switch dev
git fetch origin
git merge origin/integration
# 修改、测试、提交
git push origin dev
# 创建 dev → integration PR
```

多人工作使用独立 feat/*、fix/*、docs/* 任务分支，Agent 默认使用 codex/*。所有任务分支仍向 integration 提交 PR。不要在同一工作目录并行覆盖用户改动。

## 本地检查

[开发手册](docs/DEVELOPMENT.md) 说明 Python 3.12、Node 22.12+、FFmpeg 和隔离环境。基础开发不需要完整模型。

```powershell
.\.venv\Scripts\python -m pytest -q
npm --prefix frontend run build
node --test tests/governance.test.cjs
.\.venv\Scripts\python scripts/check_docs.py
.\.venv\Scripts\python scripts/check_release.py
```

运行相关检查，并在 PR 中说明未执行项。可用 `git config --local core.hooksPath .githooks` 启用防误推 hook；它拒绝直接推送 main、integration 和版本标签，但不能替代 GitHub 保护。

## 审查与合并

- 使用 PR 模板说明目的、行为变化、测试、兼容性和回退方法。
- 所有者 @yoshino-xiao7 审查当前 head 后，评论 `/reviewed <完整 40 位 head SHA>`。
- 自己的 PR 也须记录自审；不能依赖 GitHub 的自我 Approved review。
- 普通 PR 指向 main / dev 会被评论并关闭；改为 integration 后重新打开或重新提交。
- 新提交必须重新确认；`/reject <完整 SHA>` 撤销对应确认。
- CI、路由、审核及讨论全部处理后由维护者合并。
- 发布 PR 使用 `/release-confirm <X.Y.Z> <完整 SHA>`，不能用普通审核替代版本确认。

工作流未进入默认分支或套餐不支持保护时，门禁不会完整生效；见 [启用状态](docs/REPOSITORY-SETUP.md)。

## 质量与交流

一项 PR 解决一个可审查问题，避免混入无关格式化。接口、存储、依赖和安装源修改说明迁移与回退；模型修改提供固定来源、哈希、节点依赖和许可，不提交权重。新增测试覆盖真实失败场景，GPU 实测与单元测试分开记录。

不提交令牌、私人素材、数据库、.env、.qa、.manju、虚拟环境或构建缓存。行为变化同步文档；治理变化同步工作流、规则集与测试。

提交信息采用 `type(scope): summary`，常用 feat、fix、docs、refactor、test、build、ci、chore。版本号由合并者确认，不自动推断。

围绕代码和证据讨论，尊重不同经验的贡献者。大型功能先讨论范围；缺陷见 [支持指南](SUPPORT.md)，敏感问题见 [安全指南](SECURITY.md)。

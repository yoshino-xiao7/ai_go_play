## 变更目的

说明问题、触发条件和修改后的行为。关联 Issue：

## 影响与验证

- 影响范围：
- 实际执行的测试与结果：
- 数据、配置或模型兼容性：
- 截图或验收记录（如涉及界面）：
- 回退方法：

## 提交检查

- [ ] 普通开发 / 社区贡献的目标分支为 `integration`。
- [ ] 未提交账号令牌、模型权重、个人素材、数据库或本机配置。
- [ ] 文档与实现一致；失败与未执行的测试已如实记录。

维护者完成 GitHub Review 后，评论 `/reviewed <40 位 head SHA>` 记录最终确认。自己的 PR 也须记录自审。新提交会使原确认失效。

发布 PR 仅由仓库所有者从本仓库 `integration` 发起到 `main`，另填以下字段；普通 PR 无需填写：

Release-Version: <X.Y.Z>

发布合并者须评论 `/release-confirm <X.Y.Z> <40 位 integration head SHA>`，并核对 `docs/RELEASING.md`。此 PR 合并后仍需由合并者手动运行 GitHub Release 工作流，不能只推送标签。

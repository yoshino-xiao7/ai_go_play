# 分支、审查与合并规范

负责人：@yoshino-xiao7。适用于代码、文档、依赖、模型清单、工作流和紧急修复；不授权自动发布。

## 分支职责

| 分支 | 用途 | 写入方式 |
| --- | --- | --- |
| main | 对外发布线 | 仅所有者合并本仓库 integration → main 发布 PR |
| dev | 维护者开发与创作相关开发 | 开发提交；PR 到 integration |
| integration | 唯一集成与验收分支 | 审核通过的 PR，禁止直接推送 |
| fork / 任务分支 | 社区与独立任务开发 | 自己的分支提交；PR 到 integration |

社区从 main fork，但目标为 integration。fork 内名为 integration 的分支没有发布权限。所有 PR 目标为 integration，唯一例外是上述所有者发布 PR。

## 审核确认

所有者审查当前 head 后，单独评论 `/reviewed <40 位 head SHA>`。该评论记录审核对象，不能替代实际审查。维护者自己的 PR 使用同一命令记录自审，不依赖 GitHub 不允许的自我批准。其他账号的同名命令无效。新增提交必须重新审核，`/reject <40 位 SHA>` 撤销确认，删除评论也会重新检查。

发布 PR 必须来自本仓库 integration、目标为 main、作者为所有者，正文包含 `Release-Version: X.Y.Z`。所有者验收后评论 `/release-confirm <X.Y.Z> <40 位 integration head SHA>`。版本、分支、来源仓库或 head 变化后须重新确认。main 的合并按钮由所有者操作，Agent 不代替选择版本或合并 main。

发布版本号须与 main 当前版本不同。发布验收依据 GitHub Windows `quality` 结果，未验证范围列入当前版本说明。详见[发布手册](RELEASING.md)。

## 拒绝和修正

路由工作流只读取元数据。普通 PR 指向 main / dev 时先解释 integration 为唯一集成入口，再关闭 PR，并链接贡献指南。改为 integration 后可重新打开或重新提交。合法发布来源但缺少版本字段时，检查失败但保留 PR 打开，等待补齐。

## 门禁与权限

integration 必需检查为 `policy/integration/route`、`policy/integration/review`、`quality`；main 对应 `policy/main/route`、`policy/main/review`、`quality`。按目标分支分开，防止同一个提交在不同 PR 中复用普通审核作为发布确认。保护要求 PR、检查通过、基线最新、讨论解决，禁止强推和删除。独立更新限制规则仅允许仓库管理员通过 PR 更新 main / integration；当前个人仓库的管理员为所有者。

为支持唯一维护者自审，原生 approving-review 数量为 0，实际审核由绑定 SHA 和目标分支的 policy 检查承担，不能免审。将来增加管理员或迁移组织时，先调整权限模型再授权。

管理员仍能修改规则；工作流和本地 hook 不能替代服务端保护。受 GitHub 套餐或激活阶段限制时，必须明确标注未生效。

## 发布后同步与紧急修复

main 使用 merge commit 保留来源关系。发布后通过 main → integration 基线同步 PR 更新祖先关系，仍在 integration 审查；随后 dev 合并 integration。不要删除固定分支。

紧急修复从 main 建任务分支，经 integration 验收，再由所有者合并发布 PR 并发布补丁 Release。不得直接推送 main 或覆盖旧标签。

## 首次启用

工作流先经 dev → integration 审查，再由所有者在首次正式发布 PR 中带入 main。进入默认分支前，自动策略不会完整运行，引导阶段人工执行同一规则；不得直接推送 main 来“安装保护”。详见 [仓库配置](REPOSITORY-SETUP.md)。

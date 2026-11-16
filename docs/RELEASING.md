# 版本发布手册

执行者和最终合并者为仓库所有者 @yoshino-xiao7。Agent 可以准备修改、检查和草案，不能自行选择版本、合并 main 或发布。

## 版本与产物

稳定版采用 X.Y.Z：主版本为不兼容变更，次版本为兼容功能，补丁为兼容修复。当前流程不发布预发布版本，需要时先修改规范和检查。

每次发布必须具备 main 发布合并提交、vX.Y.Z 标签、GitHub Release、版本 ZIP、SHA256SUMS 和 release-manifest.json。只有标签或源码版本字段不算发布。

## 准备候选

在 dev / 任务分支，由维护者选择版本后运行：

```powershell
.\.venv\Scripts\python scripts/set_version.py X.Y.Z --write
```

工具同步 VERSION、Python、后端、前端与锁文件。版本号须与 main 当前版本不同。同步提交 [CHANGELOG.md](../CHANGELOG.md) 中带日期的对应版本说明，以及升级与回退步骤。在该版本的 `### 验收范围` 下用 `- 未验证：…` 写清未覆盖范围。GitHub Release 会公开这段说明。

发布验收以 GitHub 托管的 Windows `quality` 结果为准。CI 执行回归、前端构建、文档与版本校验，生成并校验候选 ZIP，再从干净临时目录解压，运行启动脚本并检查版本、首次安装状态、Web 页面与正常退出。CI 验证基础工作台。发布说明要明确没有验证的物理机环境、浏览器交互、依赖配置、真实模型和 GPU 生成、数据恢复等实际范围。

ZIP 随附源码及模型许可披露，模型权重单独获取。以上修改通过 dev → integration 审查。候选新增提交后须重新跑 GitHub CI，并确认新的 SHA。

## 发布 PR

所有者从本仓库 integration 创建到 main 的 PR，填写 `Release-Version: X.Y.Z`，检查完整 head SHA 后评论 `/release-confirm X.Y.Z <40 位 SHA>`。待 policy/main/route、policy/main/review、quality 通过且讨论解决，由所有者使用 **Create a merge commit** 合并，不使用 squash / rebase 发布。发布 PR 的 quality 还检查版本正文、元数据、变更记录与验收就绪文件是否一致。

## 发布 GitHub Release

1. 等待 main 合并提交的 Windows `quality` 成功。
2. Actions → Publish GitHub Release → Run workflow，选择 main。
3. 合并者填写同一 X.Y.Z、发布 PR 编号，并勾选确认。
4. 如配置 release 环境审批，完成审批。
5. 工作流核对所有者、来源、实际合并者、版本、当前 main SHA 和 CI，再打包。
6. 先创建草稿并上传完整附件，全部完成后发布 Release；标签指向验收过的 main 合并提交。

普通 push、tag push、合并事件不会自动发布。同版本标签、Release 或草稿已存在时拒绝覆盖；执行期间 main 变化时拒绝继续发布。

## 发布后与回退

发布工作流校验合并提交和 Windows CI 结果，再生成 ZIP、SHA256SUMS 及清单并验证附件哈希。后续用户在真实环境发现的问题记入对应版本的反馈记录。

通过 main → integration 同步 PR 更新基线，再更新 dev。缺陷修复走新补丁版本，不覆盖旧标签。上传失败保留草稿供所有者检查，不公开残缺资产。校验失败先定位原因，不改期望哈希掩盖损坏。数据库回退先停服务、保留现场并恢复完整备份，未验证兼容性时不直接降级代码。

首次启用和套餐限制见 [仓库配置](REPOSITORY-SETUP.md)。保护未生效时禁止宣称门禁已开启。

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

工具同步 VERSION、Python、后端、前端与锁文件，不发布。人工补齐 CHANGELOG 中带日期的版本章节和升级 / 回退说明，填写 release/release-approval.json 的版本、五项验收及证据，全部完成才设 ready 为 true。evidence 为仓库内实际验收文件的相对路径列表，不能填空、绝对路径、临时路径或未提交的本机日志。正式检查要求证据已进入当前 HEAD；仅暂存未提交也不满足条件。

验收包括干净安装、核心回归、实际生成范围、许可披露、备份回退。license_disclosures 表示分发范围与许可说明核对，不代表模型无限制商用授权。ZIP 不含权重，模型缺口必须如实披露。

这些修改通过 dev → integration 审查；候选冻结后新增提交需重新验收和确认。

## 发布 PR

所有者从本仓库 integration 创建到 main 的 PR，填写 `Release-Version: X.Y.Z`，检查完整 head SHA 后评论 `/release-confirm X.Y.Z <40 位 SHA>`。待 policy/main/route、policy/main/review、quality 通过且讨论解决，由所有者使用 **Create a merge commit** 合并，不使用 squash / rebase 发布。发布 PR 的 quality 还检查版本正文、元数据、变更记录与验收就绪文件是否一致。

## 发布 GitHub Release

1. 等待 main 合并提交的 quality 成功。
2. Actions → Publish GitHub Release → Run workflow，选择 main。
3. 合并者填写同一 X.Y.Z、发布 PR 编号，并勾选确认。
4. 如配置 release 环境审批，完成审批。
5. 工作流核对所有者、来源、实际合并者、版本、当前 main SHA 和 CI，再打包。
6. 先创建草稿并上传完整附件，全部完成后发布 Release；标签指向验收过的 main 合并提交。

普通 push、tag push、合并事件不会自动发布。同版本标签、Release 或草稿已存在时拒绝覆盖；执行期间 main 变化时拒绝继续发布。

## 发布后与回退

下载 Release 的实际 ZIP 和 SHA256SUMS，检查哈希，在干净目录按首次启动手册安装，记录启动、退出、数据保留和声明功能。不能用开发目录成功替代下载包验证。

通过 main → integration 同步 PR 更新基线，再更新 dev。缺陷修复走新补丁版本，不覆盖旧标签。上传失败保留草稿供所有者检查，不公开残缺资产。校验失败先定位原因，不改期望哈希掩盖损坏。数据库回退先停服务、保留现场并恢复完整备份，未验证兼容性时不直接降级代码。

首次启用和套餐限制见 [仓库配置](REPOSITORY-SETUP.md)。保护未生效时禁止宣称门禁已开启。

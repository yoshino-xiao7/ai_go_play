# 仓库管理与启用记录

负责人：@yoshino-xiao7。目标仓库：yoshino-xiao7/ai_go_play。本文区分规范、已准备的配置和实际启用状态，不能以文件存在代替服务器保护。

## 当前状态（2026-11-14）

| 项目 | 状态 |
| --- | --- |
| 分支 | 远端 main、dev、integration 已存在；新增两分支由 main 建立 |
| 本地工作目录 | 已切到 dev，保留此前未提交修改 |
| main | 本次未推送、未合并；默认分支仍为 main |
| 工作流、文档、规则集 | 本地准备，尚未通过 PR 进入默认分支；不能声称自动关闭和发布门禁已上线 |
| GitHub 规则集 | 尚未启用；读取接口返回 403，提示私有仓库需升级 GitHub Pro 或改为公开 |
| GitHub Releases | 本次未创建或发布；当前 VERSION 仅为一致性元数据 |

继续保持仓库私有。启用保护所需的套餐变更由所有者决定；不得为了启用保护擅自公开仓库。[GitHub 官方规则集说明](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)列明免费公开仓库和付费私有仓库的适用范围。

## 配置来源

[governance.json](../.github/governance.json) 固定仓库、所有者、分支及必需检查名称。工作流位于 [.github/workflows](../.github/workflows)，声明式规则位于 [.github/rulesets](../.github/rulesets)。

| 规则文件 | 作用 |
| --- | --- |
| main-quality.json | main 必须经 PR、基线最新、讨论解决、三个检查成功；禁止删除和强推 |
| integration-quality.json | integration 同样必须经 PR 和检查；不接受直接推送 |
| owner-merges.json | 仅管理员可通过 PR 更新 main / integration；不豁免以上质量规则 |
| release-tags.json | v* 标签建立后不可更新或删除 |

main 必需检查为 `policy/main/route`、`policy/main/review`、`quality`；integration 使用 `policy/integration/route`、`policy/integration/review`、`quality`。采用 merge commit，不使用 squash / rebase，不自动删除固定分支。

当前个人仓库管理员为所有者。增加管理员或转入组织之前必须重新设计合并权限；RepositoryRole 管理员规则并不代表永远只有某一个用户名。原生批准数为 0，以支持唯一维护者自审；实际审核由所有者的精确 SHA 确认和必需 policy 检查负责，见[治理规范](GOVERNANCE.md)。

## 首次接入顺序

1. 在 dev 审查并提交候选文件，排除私人数据、模型权重、缓存和无关改动。推送 dev 后创建 dev → integration PR。
2. 工作流尚未进入默认 main 时，人工执行同一审查流程，并记录完整 head SHA 和检查结果。所有者审查后合并 integration；不能把缺失的自动检查记为通过。
3. 由所有者选定版本并补齐发布说明，创建 integration → main 发布 PR。GitHub Windows CI 和门禁通过后，由所有者确认版本、SHA 并亲自合并。
4. 工作流进入默认分支后，确认 Actions 已启用。PR 元数据检查只执行默认分支代码，绝不运行 PR head 的脚本；普通质量检查只使用只读令牌，不配置生产密钥或 GPU。
5. 如当前账户支持私有仓库规则集，导入并启用四份规则，验证实际生效状态。首次安装前开启必需但尚不存在的检查会阻塞首个 PR，应按以上顺序完成引导。
6. 创建 `release` environment，将允许部署分支限制为 main。若启用环境人工审批，唯一维护者场景不要同时禁止本人审批而造成死锁；工作流仍强制所有者、真实合并者和版本确认。
7. 待 main 的 quality 成功，按[发布手册](RELEASING.md)手动运行 Release 工作流。接入流程本身不构成发布授权。

套餐不支持或引导尚未完成期间，人工规范和本地 hook 只能防误操作，无法阻止具有写权限的人绕过。此时不得宣称“服务器已强制禁止直推”。

## 应用及核对服务器规则

准备已登录且有仓库管理权限的 GitHub CLI。默认预览不修改远端：

```powershell
python scripts/apply_repository_rules.py
# 套餐支持、配置审阅完成后：
python scripts/apply_repository_rules.py --apply
```

工具先读取规则集；权限或套餐失败时不写入。按固定名称新增或更新本仓库规则，并读回核对。过程中失败可能保留前面已成功的规则，应检查报告再重试，不能删除全部规则来恢复。

在 Settings → General 保留默认分支 main、允许 merge commits；关闭自动删除 head branch，避免删除 integration。在 Settings → Rules → Rulesets 确认规则为 Active、目标正确、没有额外 bypass。不要给日常开发令牌添加绕过权限。检查分支实际适用规则时可运行：

```powershell
gh api repos/yoshino-xiao7/ai_go_play/rules/branches/main
gh api repos/yoshino-xiao7/ai_go_play/rules/branches/integration
```

GitHub Actions 允许所用固定版本 actions；fork PR 在获准运行前可能等待维护者批准。审批不意味着授予 fork 写令牌或秘密。创建错误目标 PR 后应看到解释评论、失败的路由检查和关闭状态；正确改投 integration 后可以重新打开。发布来源正确但缺少版本的 PR 保持打开，等待补齐。

## 本地防误推

```powershell
git config --local core.hooksPath .githooks
```

如果已有自定义 hooksPath，先合并现有 hook，不直接覆盖其他项目约定。Linux / macOS 需要 `chmod +x .githooks/pre-push`。hook 按远端目标 ref 判断，拦截别名推送、删除 main / integration 和 v* 标签；它不联系 GitHub。用户可以绕过本地 hook，所以它不能替代服务端规则。

修改所有者、分支、检查名称或发布流程时，同步规范、脚本、规则集和测试，并重复检查实际远端状态。上游 GitHub API 定义见[规则集 API](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset)。

# 开发与发布流程验收记录

日期：2026-11-14。范围：分支规范、PR 策略、版本门禁、源码打包和开发者文档。没有发布 Release，也没有合并或推送 main。

## 仓库状态

- 远端 dev、integration 从既有 main 建立；本地已切换 dev，原有未提交修改保留。
- 本次流程文件、文档和工具仍在本地工作区，未提交或推送；自动关闭 PR 与 Release 工作流尚未上线。
- GitHub 私有仓库规则集接口返回 403，要求升级套餐或公开仓库；保持私有，没有更改套餐或可见性。
- 本地 core.hooksPath 已设为 .githooks，通过真实 Git hook 调用确认禁止 dev 别名直推 main。检查没有发起网络推送。
- 实际启用状态、规则导入与首次接入顺序见 [仓库配置](../docs/REPOSITORY-SETUP.md)。

## 已执行验证

| 检查 | 结果 |
| --- | --- |
| 完整后端回归 `pytest -q` | 555 通过、1 跳过；约 309 秒。跳过为既有 Windows 符号链接权限场景 |
| `tests/test_governance.py` | 22 通过；隔离临时仓库覆盖版本不一致、未就绪、证据缺失、误推、脏工作树、私人文件和 ZIP 校验 |
| `node --test tests/governance.test.cjs` | 14 通过；覆盖 fork 来源、错误目标解释并关闭、精确 SHA 审核、版本确认、并发 head 变化及发布附件哈希 |
| 前端 TypeScript 与 Vite 构建 | 通过；输出到 .qa/governance/frontend-dist，未替换正在使用的网页构建 |
| 开发代理 | MANJU_DEV_API=8780 配置被 Vite 正确读取 |
| 文档校验 | Markdown 链接及 HTML 图片 / 链接的本地目标存在；中英文 README 头图已在浏览器渲染检查 |
| 配置格式 | 六份 YAML、治理与四份规则集 JSON 解析通过 |
| 普通版本检查 | 0.1.0 元数据一致；不代表发布授权 |
| 正式发布检查 | 按预期拒绝：缺少已确认版本的 dated changelog；ready 状态保持 false |

PR API 测试使用模拟响应；打包测试使用临时仓库与虚构版本，不创建真实 PR、标签或 Release。后端回归后，仅修改了文档 / 文档检查和治理脚本；相应针对性测试已重新执行。

前端仍有既有大 chunk 提示，测试有 Starlette/httpx 弃用提示。本轮没有改变推理依赖或重新运行 GPU 验收。

## 未验证范围

GitHub 托管 runner 上的首次工作流、真实 fork PR 的自动关闭、规则集服务器执行及真实 Release 附件下载尚未验证。需先按正常 dev → integration → main 流程接入，并解决套餐限制。不能将本地通过写成远端已经强制执行。

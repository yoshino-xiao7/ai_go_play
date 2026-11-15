# API 与 CLI 约定

启动后访问 `/docs` 和 `/openapi.json` 获取当前版本的接口定义；以运行版本 schema 和实现为准，不另维护一份容易失效的完整接口清单。

```powershell
.\.venv\Scripts\python -m manju --help
.\.venv\Scripts\python -m manju --url http://127.0.0.1:8780 project --help
Invoke-RestMethod http://127.0.0.1:8780/api/health
```

以上使用隔离服务，见 [开发环境](DEVELOPMENT.md)。

| 路径域 | 用途 |
| --- | --- |
| /api/health | 健康和运行版本 |
| /api/about | 应用身份、运行摘要和最近更新检查（仅本机读取） |
| /api/about/updates/check | POST，显式检查 GitHub 正式 Releases |
| /api/projects、/api/assets | 项目、画布、素材与版本 |
| /api/generations、/api/tasks | 生成和后台任务 |
| /api/workflows、/api/comfy | 工作流与本机引擎 |
| /api/setup | 引导与模型准备 |
| /api/share | 用户授权的账号和分享 |
| /api/system/shutdown | 退出预检与显式确认 |
| /api/events | SSE 变化通知 |

服务不应直接暴露公网，浏览器跨站请求受来源检查。写入前读取现有文档并遵循 revision / request ID；冲突后处理差异。HTTP 成功不一定表示后台生成完成，应跟踪任务状态。

错误通常含 detail.code、detail.message 及相关字段；调用方按状态和错误码处理，不仅匹配中文文案。上传使用 multipart，素材路径由服务管理。CLI 的非零退出码不能忽略。

接口路径、字段、默认值、错误码或状态机变化须说明迁移方式并测试。旧后端与新前端并存要提供明确兼容或更新提示；退出先保存，有任务时拒绝，不用强杀替代。

## GitHub 更新检查

`GET /api/about` 不访问外网；当前版本来自 `manju.__version__`，与 health 及发布校验一致。运行摘要只含系统类型、架构、Python 与应用版本，不含主机名、资料库路径或账号。

`POST /api/about/updates/check` 由本机服务匿名读取固定上游 `yoshino-xiao7/ai_go_play` 的 `/releases/latest`，不接收自定义地址或令牌，不上传工程信息。接口只返回正式的 `X.Y.Z` / `vX.Y.Z` 发布，按数字比较版本，不把分支提交或预发布视为更新。

返回 `status` 为 `available`、`up_to_date`、`ahead` 或 `unavailable`，并提供 `checked_at`、`cached`、`retry_after_seconds` 和可空的 `latest`（版本、日期、说明、官方发布链接）。上游错误也以 HTTP 200 返回检查结果，调用方必须判断 `status`；404 表示无可公开访问的 Release，无法区分未发布与私有仓库，不能展示“已是最新版”。网络、超时、限流、格式错误均有独立 `reason`。

单次连接超时 10 秒，响应上限 1 MiB，说明上限 20,000 字符，以纯文本显示。每个服务实例串行合并并发检查，成功缓存 5 分钟，失败至少缓存 1 分钟，限流按响应头最多等待 1 小时；缓存只在内存，不进行后台轮询。此接口不下载、不执行、不安装更新。GitHub API 约定参见 [官方 Releases 文档](https://docs.github.com/en/rest/releases/releases#get-the-latest-release)。

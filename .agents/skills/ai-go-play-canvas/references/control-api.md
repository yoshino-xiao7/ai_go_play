# 运行接口与画布文档

本参考描述 ai-go-play 的控制路径。运行服务的 `/openapi.json` 和 CLI `--help` 是当前字段与能力的依据。以下 CLI 使用用户会话中确认的 `$CanvasUrl`、`$ProjectId`，不要直接套用上一次会话的值。

示例中的 `manju` 若不在 PATH，替换为项目根目录的 `.venv/Scripts/python.exe -m manju`；可直接调用 HTTP API，不要求全局安装 CLI。

## 发现能力

```powershell
manju --help
manju --url "$CanvasUrl" doctor --json
manju --url "$CanvasUrl" project list --json
manju --url "$CanvasUrl" project get "$ProjectId" --json
manju --url "$CanvasUrl" canvas inspect --project "$ProjectId" --json
```

| HTTP 路径 | 用途 |
| --- | --- |
| `GET /api/health` | 服务运行版本与健康 |
| `GET /openapi.json` | 当前接口定义 |
| `GET /api/projects` | 项目清单；定位用户指定的工程 |
| `GET /api/projects/{project_id}/canvas` | `revision / nodes / edges / viewport` |
| `PUT /api/projects/{project_id}/canvas` | 提交完整画布文档 |
| `GET /api/comfy` | 实际 `base_url`、运行状态及 `queue.running / queue.pending` |

不要绕过服务直接写 SQLite、复制活动数据库作为操作方式，或把工作站的物理数据路径写进通用请求。

## 更新完整画布

保存结构为：

```json
{
  "revision": 17,
  "request_id": "unique-operation-id",
  "nodes": [],
  "edges": [],
  "viewport": {"x": 0, "y": 0, "zoom": 1}
}
```

这里的空数组只展示字段，不能直接用来更新已有项目。先读取全文、按 ID 修改目标节点，再提交所有保留内容。

- 独立操作用新的 `request_id`。同一次操作的网络重试保持 ID 和请求内容一致。
- 成功响应包含新修订，后续写入使用新值。
- `409 revision_conflict` 表示用户、任务交付或另一入口修改了同一项目。回读最新文档并合并本次变化；不要自动重放旧整份文档。
- `canvas`、`production`、`timeline` 都保存在同一画布状态中，任一写入都会改变共享修订。
- `data.locked` 和关联边受服务锁定检查。用户已授权的修改需要先按实际能力解锁，不能靠删除重建绕过。

CLI `canvas apply --project "$ProjectId" <file>` 接收同一完整结构；文件须含整数 `revision`。需要避免独立记录文件时，直接在内存构造 HTTP 请求。

## 卡片与分组

普通卡片的核心字段是 `id / type / position / style / data`；通过运行版本 schema 和同类现有节点核对具体结构。常用内容如下：

- 媒体：`type: media`，`data.kind` 和固定 `data.asset_version_id`。
- 文字：`type: text`，`data.title / data.text`。
- 主体：`type: subject`，使用固定图片版本及可选音色，按主体 API 规范保存。
- 原生分镜：由 production 接口维护的 frame，`data.shot` 保存镜头信息。
- 分组：使用 `parentId` 的节点位置相对父节点；不是绝对坐标。

移动、删除父框时先核对其子节点。保留子节点而移除父框时，将坐标换算为应有的位置，解除失效的 `parentId / extent`。移除节点后只删除与它相连的边，确认没有悬空端点。

连线 `data.role: reference` 表示生成输入；`data.role: relation` 表示说明、研究、来源或合成关系。关系边不会把素材自动送入生成器。

## 按范围清理

先确定要保留、删除的节点 ID 及仍在运行的任务。区分：

1. 删除画布节点：改变画布组织，不等于删除资产原件。
2. 清空分镜或时间线：还需处理相应原生文档与隐藏状态，避免旧采用关系继续起效。
3. 删除资产或永久删除项目：独立且范围更大的操作，不从“清理试镜卡”推导授权。

清理完成后回读画布、production、timeline，检查保留项、编排、连线和当前视图。不要把“隐藏”当作用户要求的删除。

接口实现可在对应版本的 `backend/manju/app.py`、`cli.py`、`store.py` 中核对。

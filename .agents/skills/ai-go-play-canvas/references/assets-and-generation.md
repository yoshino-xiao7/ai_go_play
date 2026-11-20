# 素材、参考与生成任务

按任务使用本参考；模型提示词正文由对应收录技能提供，这里只维护真实输入、请求与结果关系。

## 导入固定版本

```powershell
manju --url "$CanvasUrl" asset import "$MediaFile" --project "$ProjectId" --json
manju --url "$CanvasUrl" canvas add-asset --project "$ProjectId" --version "$VersionId" --x 0 --y 0 --json
```

HTTP 上传为 `POST /api/assets/upload`，使用 multipart 的 `file`、可选 `project_id`、可选 `asset_id`，以及可选 `X-Request-ID`。

- 新文件或同资产新版本均使用响应的 `imported_version_id`。不要依赖 `current_version_id` 恰好等于本次导入版本。
- `GET /api/versions/{version_id}` 返回 `version` 与所属 `asset`，可核对类型、哈希、尺寸、时长及原件是否缺失。
- 上传关联到项目，不会自动建立所需画布媒体卡。使用 `canvas add-asset` 或完整画布写入添加卡片。
- 媒体原件路径由服务管理。外部工具的输出保留原件，导入服务后才作为项目固定版本使用。

## 保存生成草稿与输入

在媒体卡的 `data.generation` 保存实际完整草稿。具体工作流字段以服务返回的能力为准；常见组成如下：

```json
{
  "workflow_id": "chosen-workflow-id",
  "prompt": "本次实际提交的完整提示词",
  "parameters": {},
  "references": [{
    "id": "input-identity",
    "edge_id": "input-edge-id",
    "node_id": "actual-source-card-id",
    "version_id": "pinned-input-version-id",
    "source": "connection",
    "role": "reference",
    "media_type": "image",
    "use_description": false
  }],
  "reference_order": ["pinned-input-version-id"],
  "result_policy": "review"
}
```

这只是结构说明，不是可直接提交的工作流配置。实际参考边的 `source` 指向来源卡、`target` 指向目标创作卡，边的 `data.role` 为 `reference`。首尾帧、音频、视频、蒙版与定帧等输入角色须与所选工作流匹配。

有主体描述时明确是否启用 `use_description`。使用结构化 `prompt_parts` 或素材提及时，回读实际编译文本及参考编号；不要只靠素材标题推断输入顺序。调用 API 时从已保存草稿构造受支持的请求字段，不把画布专用字段全部当成生成 API 字段。

## 预检与队列

```powershell
manju --url "$CanvasUrl" workflow list --json
manju --url "$CanvasUrl" workflow get "$WorkflowId" --json
manju --url "$CanvasUrl" comfy status --json
manju --url "$CanvasUrl" job list --project "$ProjectId" --json
```

- 自定义工作流可用 `workflow validate` / `POST /api/workflows/{workflow_id}/validate`。
- 内置功能的检查入口不同。用户选择 H3 时读取 `GET /api/video/settings`、`GET /api/video/workflow?mode=...&engine=...` 的实际能力；不要把自定义工作流验证假定为 H3 的通用就绪检查。
- `/api/comfy` 返回真实后端地址与队列计数。需要底层查询时使用返回地址，不猜测另一个引擎端口。
- 已有其他 GPU 工作时等待；无法确认队列时不声称它空闲。

## 单卡任务

保存草稿后 `POST /api/generations`，传真实 `project_id / source_node_id`、实际配置和明确的 `result_policy: review`。用 `request_id` 对本次提交去重。

```powershell
manju --url "$CanvasUrl" job show "$JobId" --json
manju --url "$CanvasUrl" job wait "$JobId" --max-wait 30 --json
manju --url "$CanvasUrl" job cancel "$JobId" --json
```

等待超时只表示此次等待结束，任务可能仍在后台。用 `GET /api/generations/{job_id}` 回读状态，直到成功、失败或取消；失败、未知或连接故障不能报告为完成。

成功后核对实际请求、编译后提示词（若存在）、`workflow_snapshot`、实际参数和 `outputs[].version_id`，再回读源卡及实际媒体。原生任务会保留其任务 ID；不要伪造模型已收到的输入或参数。

`review` 用于候选管理，但空卡的第一个结果仍可能直接显示为当前版本。显示结果、绑定供审片、用户确认和最终采用应在制作记录里分别标明。

用户拒绝结果时保留该候选和任务，解除错误的分镜或时间线采用绑定。后续镜头只在已授权范围内推进，不因任务成功自动取得续作授权。

## 有范围的取消与重试

`POST /api/generations/{job_id}/cancel` 默认 `interrupt_running: false`。只有需要停止本授权任务正在执行的部分时，才提交 `interrupt_running: true`，并回读终态。

重试使用原生任务 `/retry` 或 CLI `job retry`，明确所复用的请求及新的请求 ID。修订提示词或输入是新候选，先保留上一轮记录，再保存新草稿。不要用 ComfyUI 全局中断、杀进程或停止服务替代定向取消。

## 外部工具回导

用户指定 Codex 内置绘图等工具时：

1. 按真实工具使用输入并保留实际输出原件。
2. 导入输出取得固定版本，建立或更新目标媒体卡。
3. 在本卡 `data.note` 或关联文字卡保存真实工具、完整实际提示词、参考用途与固定版本、输出来源、导入版本及检查结论。
4. 后期编辑另记衍生版本、输入与参数；不把修订结果冒充原始输出。

这是外部生成记录，不创建虚假的本地 `generation_id`，也不声称它使用了某个未实际调用的 API 模型。用户要求记录只留画布时，不另建 JSON/Markdown 记录副本。

对应实现：`app.py`、`generation.py`、`reference_contract.py`、`video_inputs.py`、`store.py`。

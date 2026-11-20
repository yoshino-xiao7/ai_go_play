# 原生分镜、编排、时间线和导出

这些文档与画布共用项目修订号。操作前读取当前对象，保留本次范围外内容及设置。

## 原生分镜

```powershell
manju --url "$CanvasUrl" production inspect --project "$ProjectId" --json
manju --url "$CanvasUrl" production apply --project "$ProjectId" --file "$ProductionFile" --json
```

HTTP 为 `GET / PUT /api/projects/{project_id}/production`。保存正文含 `revision / request_id / settings / shots`；不是逐镜 patch。CLI apply 需要文件，直接 API 可在内存组织同一正文。

| 字段 | 操作用途 |
| --- | --- |
| `id` | 稳定镜头 ID，对应原生画布 frame；已有镜头保留 ID |
| `title / scene / characters` | 本镜标题、场景与人物 |
| `dialogue / speaker / notes` | 已确定的原句、发声归属和制作说明；不由控制技能改写 |
| `duration / trim_start` | 当前实际剪辑秒数和入点；原生成长度另记 |
| `video_node_id / video_version_id` | 真实视频来源卡及固定版本 |
| `audio_node_id / audio_version_id` | 独立音轨来源卡及固定版本，需要时才填 |
| `video_volume / audio_volume / audio_offset` | 实际音轨使用方式与偏移 |
| `status` | `draft / ready / approved`；用户确认与内部检查分别记清 |

未生成计划设为 `draft`，不填预期 ID。供审候选和用户采用不能混同；拒绝后解除采用绑定，并把候选留在来源卡或明确的历史记录中。

`POST /api/projects/{project_id}/production/generate` 可限定 `shot_ids / kinds / only_missing / revision`。先检查实际生成范围，不将“制作一镜”变成全片批量提交。`production render` 当前合成整个原生分镜清单，不支持假定存在的单镜 `shot_ids` 渲染筛选。

## 依赖图编排

```powershell
manju --url "$CanvasUrl" canvas-run plan --project "$ProjectId" --scope downstream --node "$NodeId" --revision $Revision --json
manju --url "$CanvasUrl" canvas-run start --project "$ProjectId" --scope downstream --node "$NodeId" --revision $Revision --json
manju --url "$CanvasUrl" canvas-run show "$RunId" --json
```

HTTP 路径：

- `POST /api/projects/{project_id}/canvas-runs/plan`：查看计划。
- `POST /api/projects/{project_id}/canvas-runs`：按修订提交。
- `GET /api/canvas-runs/{run_id}`：跟踪实际节点状态。
- `POST /api/canvas-runs/{run_id}/cancel` 或 `/retry`：控制对应运行。

预检会读取媒体卡的 `data.generation` 与参考边，建立输入依赖。`scope: downstream` 从选定节点找下游，并补齐必需祖先；不是“仅运行这个节点”。检查计划中的执行节点、依赖、缓存、错误及警告，不只判断 HTTP 成功。

已有通过素材要作为固定输入复用时，使用没有生成草稿的固定素材卡，以关系边追溯原创作卡。避免编排将原创作卡当作可执行上游。`force` 会改变缓存使用行为，不作为默认重试选项。

## 多轨时间线

```powershell
manju --url "$CanvasUrl" timeline inspect --project "$ProjectId" --json
manju --url "$CanvasUrl" timeline apply --project "$ProjectId" --file "$TimelineFile" --json
```

HTTP 为 `GET / PUT /api/projects/{project_id}/timeline`，保存 `revision / request_id / settings / tracks / clips`。轨道类型为 `video / audio / text`。

片段使用稳定 `id / track_id`，通过 `start / duration / trim_start` 指定位置与入出点；媒体片段绑定 `source_node_id / asset_version_id`。`transform` 管位置、缩放与透明度，`volume / audio_preset / fade_in / fade_out` 等按实际 schema 设置。文本片段用 `text / text_style`。

保留轨道、片段及锁定状态；不要为修改一镜覆盖整个时间线。`latest_*` 与 `stale` 表示来源已改变时，仍需明确选择是否更新固定采用版本，不自动切到最新结果。

## 原生渲染

保存所采用的分镜或时间线，再提交：

```powershell
manju --url "$CanvasUrl" timeline render --project "$ProjectId" --revision $Revision --name "$RenderName" --json
manju --url "$CanvasUrl" production show "$RenderId" --json
```

原生入口为 `POST /api/projects/{project_id}/timeline/render` 或 `/production/render`；返回持久化渲染任务，使用 `GET /api/production/renders/{render_id}` 跟踪。不能把提交响应或外部预演当作完成的项目原生合成。

完成后记录实际输出卡、版本和渲染 ID，核对源素材、剪辑长度、切入首帧、切点和音轨。技术检查、实际看过的画面、自动转写、人工试听和用户审片分别记录，不报告未执行的检查。

## 清理与工程导出

清理编排时，检查原生分镜、时间线及其隐藏设置是否仍有旧采用关系。删节点、清空编排不自动授权删除资产。仍有任务使用内容时，先按用户范围等待或取消对应任务。

```powershell
manju --url "$CanvasUrl" project export --project "$ProjectId" --output "$ArchivePath" --json
```

HTTP 为 `GET /api/projects/{project_id}/export`，得到可编辑 `.manju`。按用户指定目的地保存；检查保留的卡片、固定素材和制作记录，不把服务数据库里的全部任务历史假定为已包含在项目包里。必要的追溯信息先写进要保留的画布卡片。

对应实现：`cli.py`、`orchestration.py`、`production.py`、`timeline.py` 及 `app.py`。

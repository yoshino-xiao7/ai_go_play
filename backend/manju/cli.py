"""Scriptable client for the same local API used by the canvas."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
import uuid

import httpx


class CliError(Exception):
    def __init__(self, message: str, code: str = "invalid_arguments", **details):
        self.detail = {"code": code, "message": message, **details}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError(message)


def common(parser):
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="输出稳定 JSON，诊断写入 stderr")
    parser.add_argument("--url", default=argparse.SUPPRESS, help="本地服务 URL，默认 http://127.0.0.1:8765")
    parser.add_argument("--timeout", type=float, default=argparse.SUPPRESS, help="HTTP 超时秒数，默认 1800")
    return parser


def build_parser():
    parser = common(Parser(prog="manju", description="Manju 本地创作工作台"))
    commands = parser.add_subparsers(dest="command", required=True)
    serve = common(commands.add_parser("serve", help="启动本地服务"))
    serve.add_argument("--data-dir", help="初始资产根目录，已有配置中的迁移目标优先")
    serve.add_argument("--config-file", help="独立配置文件路径")
    serve.add_argument("--port", type=int, default=8765)
    common(commands.add_parser("doctor", help="检查服务、存储和 FFmpeg"))
    project = common(commands.add_parser("project"))
    projects = project.add_subparsers(dest="action", required=True)
    create = common(projects.add_parser("create"))
    create.add_argument("name", nargs="?")
    create.add_argument("--name", dest="name_option")
    create.add_argument("--aspect", choices=["free", "16:9", "9:16"], default="free")
    listing = common(projects.add_parser("list"))
    listing.add_argument("--trash", action="store_true")
    listing.add_argument("--search", default="")
    for action in ("get", "duplicate", "trash", "restore", "purge", "rename", "export", "link", "unlink"):
        sub = common(projects.add_parser(action))
        sub.add_argument("project_id", nargs="?" if action == "export" else None)
        if action == "rename":
            sub.add_argument("name")
        if action == "export":
            sub.add_argument("file", type=Path, nargs="?")
            sub.add_argument("--project", dest="project_id_option")
            sub.add_argument("--output", dest="file_option", type=Path)
            sub.add_argument("--force", action="store_true")
        if action in ("link", "unlink"):
            sub.add_argument("asset_id")
        if action == "unlink":
            sub.add_argument("--remove-nodes", action="store_true")
    imported = common(projects.add_parser("import"))
    imported.add_argument("file", type=Path)
    asset = common(commands.add_parser("asset"))
    assets = asset.add_subparsers(dest="action", required=True)
    listing = common(assets.add_parser("list"))
    for name in ("search", "type", "tag", "source"):
        listing.add_argument("--" + name, default="")
    listing.add_argument("--project", dest="project_id")
    listing.add_argument("--trash", action="store_true")
    listing.add_argument("--offset", type=int, default=0)
    listing.add_argument("--limit", type=int, default=60)
    imported = common(assets.add_parser("import"))
    imported.add_argument("file", type=Path, nargs="?")
    imported.add_argument("--file", dest="file_option", type=Path)
    imported.add_argument("--project", dest="project_id")
    imported.add_argument("--request-id")
    for action in ("show", "trash", "restore", "purge", "reveal", "repair", "version", "tag", "rename"):
        sub = common(assets.add_parser(action))
        sub.add_argument("asset_id")
        if action == "tag":
            sub.add_argument("tags", nargs="*", help="用这些标签替换完整标签列表，留空则清除")
        if action == "rename":
            sub.add_argument("name")
        if action == "version":
            sub.add_argument("file", type=Path, nargs="?")
            sub.add_argument("--select", dest="version_id", help="选择已有版本作为资产当前版本")
            sub.add_argument("--request-id")
        if action == "repair":
            sub.add_argument("file", type=Path)
        if action in ("repair", "reveal"):
            sub.add_argument("--version", dest="version_id")
    canvas = common(commands.add_parser("canvas"))
    canvases = canvas.add_subparsers(dest="action", required=True)
    for action in ("inspect", "add-asset", "apply", "render-frame"):
        sub = common(canvases.add_parser(action))
        sub.add_argument("project_id", nargs="?")
        sub.add_argument("--project", dest="project_id_option")
        if action != "inspect":
            sub.add_argument("--request-id")
        if action == "apply":
            sub.add_argument("file", type=Path, help="含 revision、nodes、edges、viewport 的完整画布 JSON")
        if action == "render-frame":
            sub.add_argument('--frame', dest='frame_id', required=True)
            sub.add_argument('--name')
            sub.add_argument('--scale', type=float, default=1)
        if action == "add-asset":
            sub.add_argument("asset_id", nargs="?")
            sub.add_argument("--version", "--asset-version", dest="version_id")
            sub.add_argument("--x", type=float, default=0)
            sub.add_argument("--y", type=float, default=0)
            sub.add_argument("--revision", type=int, help="要求画布仍处于此修订号")
    task = common(commands.add_parser("task"))
    tasks = task.add_subparsers(dest="action", required=True)
    common(tasks.add_parser("list"))
    retry = common(tasks.add_parser("retry"))
    retry.add_argument("task_id")
    storage = common(commands.add_parser("storage"))
    storages = storage.add_subparsers(dest="action", required=True)
    for action in ("inspect", "migrate", "resume", "cancel"):
        sub = common(storages.add_parser(action))
        if action == "migrate":
            sub.add_argument("target", type=Path)
    comfy = common(commands.add_parser("comfy", help="管理本机 ComfyUI"))
    comfy_commands = comfy.add_subparsers(dest="action", required=True)
    for action in ("scan", "status", "configure", "start", "stop", "logs"):
        sub = common(comfy_commands.add_parser(action))
        if action == "scan":
            sub.add_argument("--path", type=Path, help="扫描指定安装目录或其父目录")
        if action == "configure":
            sub.add_argument("--installation-path", "--path", dest="installation_path", type=Path, required=True)
            sub.add_argument("--port", type=int, default=8188)
        if action == "stop":
            sub.add_argument("--force", action="store_true", help="明确允许停止仍有任务的托管实例")
        if action == "logs":
            sub.add_argument("--limit", type=int, default=200, help="最近日志行数，最多 1000")
    workflow = common(commands.add_parser("workflow", help="注册和验证 ComfyUI API 工作流"))
    workflow_commands = workflow.add_subparsers(dest="action", required=True)
    for action in ("list", "get", "create", "import", "update", "duplicate", "delete", "validate"):
        sub = common(workflow_commands.add_parser(action))
        if action in ("get", "update", "duplicate", "delete", "validate"):
            sub.add_argument("workflow_id")
        if action in ("create", "import", "update"):
            sub.add_argument("--file", type=Path, required=True)
        if action in ("list", "import"):
            sub.add_argument("--mode", choices=["text_to_image", "reference", "edit"] + (["video","audio"] if action=="list" else []))
        if action == "import":
            sub.add_argument("--name")
    subject = common(commands.add_parser("subject", help="管理人物、场景、道具的固定图片与音色版本"))
    subject_commands = subject.add_subparsers(dest="action", required=True)
    for action in ("list", "show", "create", "update", "delete"):
        sub = common(subject_commands.add_parser(action))
        if action == "list":
            sub.add_argument("--search", default="")
            sub.add_argument("--offset", type=int, default=0)
            sub.add_argument("--limit", type=int, default=60)
        elif action != "create":
            sub.add_argument("subject_id")
        if action in ("create", "update"):
            sub.add_argument("--name", required=action == "create")
            sub.add_argument("--description", default="" if action == "create" else None)
            image_options = sub.add_mutually_exclusive_group(required=action == "create")
            if action == "create":
                image_options.add_argument("--version", "--asset-version", dest="version_id", help="兼容单图版本")
            image_options.add_argument("--image", "--image-version", dest="image_version_ids", action="append", help="固定图片版本，可重复；完整替换有序图片列表，第一张为主图")
            voice_options = sub.add_mutually_exclusive_group()
            voice_options.add_argument("--voice-version", dest="voice_version_id", help="人物音色的固定音频版本")
            voice_options.add_argument("--clear-voice", action="store_true", help="同时清空音频、音色名称和参考文本")
            sub.add_argument("--voice-name")
            sub.add_argument("--voice-transcript")
        if action in ("list", "create", "update"):
            sub.add_argument("--kind", choices=["character", "scene", "prop"])
        if action == "create":
            sub.add_argument("--request-id")
    generate = common(commands.add_parser("generate", help="创建持久化图片、视频或人物配音任务"))
    generate.add_argument("--kind", choices=("image","video","audio"))
    generate.add_argument("--subject-node", help="配音人物主体的画布节点 ID", dest="subject_node_id")
    generate.add_argument("--language", choices=("zh","en","ja","es","ar"))
    generate.add_argument("--speed", type=float)
    generate.add_argument("--emotion", choices=("reference","neutral","happy","angry","sad","afraid","disgusted","melancholic","surprised","calm"))
    generate.add_argument("--emotion-intensity", type=float)
    generate.add_argument("--video-mode", choices=("text","frames","reference"))
    generate.add_argument("--video-engine", choices=("native","director","turbo"), help="H3 原生流程、Director 镜头组或 Turbo 8 步全参考")
    generate.add_argument("--ref-image-size", choices=("match","1024","1280","1536","max"), help="独立参考图处理分辨率")
    generate.add_argument("--duration", type=int)
    generate.add_argument("--silent", action="store_true", help="视频不包含音轨")
    generate.add_argument("--first-frame", help="首帧图片的固定版本 ID")
    generate.add_argument("--last-frame", help="尾帧图片的固定版本 ID")
    generate.add_argument("--file", type=Path, help="完整生成请求 JSON")
    generate.add_argument("--project", dest="project_id")
    generate.add_argument("--workflow", dest="workflow_id")
    generate.add_argument("--prompt")
    generate.add_argument("--negative-prompt", help="省略时使用工作流默认负面提示词，空字符串明确清空")
    generate.add_argument("--source-node", dest="source_node_id")
    generate.add_argument("--reference", action="append", default=[], help="固定的输入图片版本 ID，可重复")
    generate.add_argument("--mask", dest="mask_version_id")
    generate.add_argument("--request-id")
    for name in ("seed", "width", "height", "steps"):
        generate.add_argument("--" + name, type=int)
    for name in ("cfg", "denoise", "x", "y"):
        generate.add_argument("--" + name, type=float)
    video = common(commands.add_parser("video", help="维护本地 H3 模型配置"))
    video_commands = video.add_subparsers(dest="action", required=True)
    common(video_commands.add_parser("status"))
    video_settings = common(video_commands.add_parser("configure"))
    video_settings.add_argument("--file", type=Path, required=True, help="含 revision 和 models 的 JSON 文件")
    jobs = common(commands.add_parser("job", help="查询和控制图片及视频生成任务"))
    job_commands = jobs.add_subparsers(dest="action", required=True)
    for action in ("list", "show", "cancel", "retry", "wait"):
        sub = common(job_commands.add_parser(action))
        if action == "list":
            sub.add_argument("--project", dest="project_id")
            sub.add_argument("--limit", type=int, default=100)
        else:
            sub.add_argument("job_id")
        if action == "cancel":
            sub.add_argument("--interrupt-running", action="store_true")
        if action == "retry":
            sub.add_argument("--request-id")
        if action == "wait":
            sub.add_argument("--interval", type=float, default=1)
            sub.add_argument("--max-wait", type=float, default=1800)
    production = common(commands.add_parser('production', help='镜头编排、批量生成、字幕和成片导出'))
    production_commands = production.add_subparsers(dest='action', required=True)
    for action in ('inspect', 'apply', 'generate', 'render', 'show', 'wait', 'retry', 'subtitles', 'handoff'):
        sub = common(production_commands.add_parser(action))
        if action in ('show', 'wait', 'retry'):
            sub.add_argument('job_id')
        else:
            sub.add_argument('--project', dest='project_id', required=True)
        if action in ('apply', 'generate', 'render'):
            sub.add_argument('--request-id')
        if action == 'apply':
            sub.add_argument('--file', type=Path, required=True, help='包含revision/settings/shots的JSON')
        if action == 'generate':
            sub.add_argument('--shot', dest='shot_ids', action='append')
            sub.add_argument('--revision', type=int, help='要求镜头清单仍处于指定修订号')
            sub.add_argument('--kind', dest='kinds', action='append', choices=['video','audio'])
            sub.add_argument('--redo', action='store_true', help='重做指定镜头，保留已采用版本')
        if action == 'render':
            sub.add_argument('--name')
            sub.add_argument('--revision', type=int)
            sub.add_argument('--no-subtitles', action='store_true')
        if action in ('subtitles', 'handoff'):
            sub.add_argument('--output', type=Path, required=True)
        if action == 'wait':
            sub.add_argument('--interval', type=float, default=2)
            sub.add_argument('--max-wait', type=float, default=1800)
    timeline = common(commands.add_parser('timeline', help='自由多轨编辑与成片'))
    timeline_commands = timeline.add_subparsers(dest='action', required=True)
    for action in ('inspect','apply','import-production','render','show','wait','retry'):
        sub = common(timeline_commands.add_parser(action))
        if action in ('show','wait','retry'):
            sub.add_argument('job_id')
        else:
            sub.add_argument('--project', dest='project_id', required=True)
        if action == 'apply':
            sub.add_argument('--file', type=Path, required=True)
        if action in ('apply','import-production','render'):
            sub.add_argument('--request-id')
        if action in ('import-production','render'):
            sub.add_argument('--revision', type=int, required=True)
        if action == 'render':
            sub.add_argument('--name')
        if action == 'wait':
            sub.add_argument('--interval', type=float, default=1)
            sub.add_argument('--max-wait', type=float, default=1800)
    run = common(commands.add_parser('canvas-run', help='全画布依赖图计划与执行'))
    run_commands = run.add_subparsers(dest='action', required=True)
    for action in ('plan','start','list','show','wait','retry','cancel'):
        sub = common(run_commands.add_parser(action))
        if action in ('show','wait','retry','cancel'):
            sub.add_argument('run_id')
        else:
            sub.add_argument('--project', dest='project_id', required=True)
        if action in ('plan','start'):
            sub.add_argument('--scope',choices=['all','downstream'],default='all')
            sub.add_argument('--node',dest='node_ids',action='append')
            sub.add_argument('--force',action='store_true')
            sub.add_argument('--revision',type=int)
            sub.add_argument('--file',type=Path)
        if action=='start':sub.add_argument('--request-id')
        if action=='wait':
            sub.add_argument('--interval',type=float,default=2)
            sub.add_argument('--max-wait',type=float,default=3600)
    lip = common(commands.add_parser('lipsync',help='本地音频驱动口型'))
    lips = lip.add_subparsers(dest='action',required=True)
    common(lips.add_parser('settings'))
    create_lip=common(lips.add_parser('create'))
    create_lip.add_argument('--file',type=Path,required=True)
    create_lip.add_argument('--request-id')
    return parser


def normalize_arguments(args):
    """Keep positional and named forms under one required-field check."""
    for name in ("name", "file", "project_id"):
        option = getattr(args, name + "_option", None)
        if option is None:
            continue
        positional = getattr(args, name, None)
        if positional is not None and positional != option:
            raise CliError(f"{name} 的位置参数与命名参数内容不一致。")
        setattr(args, name, option)
    required = []
    if args.command == "project" and args.action == "create":
        required = ["name"]
    elif args.command == "project" and args.action == "export":
        required = ["project_id", "file"]
    elif args.command == "asset" and args.action == "import":
        required = ["file"]
    elif args.command == "canvas":
        required = ["project_id"]
        if args.action == "add-asset" and not args.asset_id and not args.version_id:
            raise CliError("添加卡片需要资产 ID 或 --asset-version VERSION_ID。")
    for name in required:
        if getattr(args, name, None) is None:
            raise CliError(f"缺少必要参数 {name}。")


def response_data(response):
    try:
        data = response.json()
    except ValueError:
        raise CliError("本地服务未返回 JSON，请确认 URL 和服务版本。", "invalid_response", status=response.status_code)
    if response.is_error:
        detail = data.get("detail", data) if isinstance(data, dict) else data
        if isinstance(detail, dict):
            detail = dict(detail)
            message = detail.pop("message", "本地服务拒绝请求。")
            code = detail.pop("code", "http_error")
            raise CliError(message, code, status=response.status_code, **detail)
        raise CliError("请求参数或操作无效。", "http_error", status=response.status_code, detail=detail)
    return data


def request(client, method, path, **kwargs):
    return response_data(client.request(method, path, **kwargs))


def upload(client, endpoint, file, *, data=None, request_id=None):
    with file.open("rb") as source:
        return request(client, "POST", endpoint, files={"file": (file.name, source)}, data=data or {}, headers={"X-Request-ID": request_id or uuid.uuid4().hex})


def project_command(client, args):
    base = "/api/projects"
    if args.action == "create":
        return request(client, "POST", base, json={"name": args.name, "aspect_ratio": args.aspect})
    if args.action == "list":
        return request(client, "GET", base, params={"trash": args.trash, "search": args.search})
    if args.action == "import":
        return upload(client, base + "/import", args.file)
    path = f"{base}/{args.project_id}"
    if args.action == "export":
        destination = args.file.expanduser().resolve()
        if destination.exists() and not args.force:
            raise CliError("目标文件已存在。如需覆盖，请传入 --force。", "file_exists", path=str(destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".part")
        try:
            with client.stream("GET", path + "/export") as response:
                if response.is_error:
                    response.read()
                    response_data(response)
                with temporary.open("xb") as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return {"path": str(destination), "size": destination.stat().st_size}
    if args.action == "rename":
        return request(client, "PATCH", path, json={"name": args.name})
    if args.action == "link":
        return request(client, "POST", path + "/assets", json={"asset_id": args.asset_id})
    if args.action == "unlink":
        return request(client, "DELETE", path + "/assets/" + args.asset_id, params={"remove_nodes": args.remove_nodes})
    method, suffix = {"get": ("GET", ""), "trash": ("DELETE", ""), "restore": ("POST", "/restore"), "purge": ("DELETE", "/permanent"), "duplicate": ("POST", "/duplicate")}[args.action]
    return request(client, method, path + suffix)


def asset_command(client, args):
    base = "/api/assets"
    if args.action == "list":
        names = ("search", "type", "tag", "source", "project_id", "trash", "offset", "limit")
        return request(client, "GET", base, params={name: getattr(args, name) for name in names if getattr(args, name) is not None})
    if args.action == "import":
        return upload(client, base + "/upload", args.file, data={"project_id": args.project_id} if args.project_id else {}, request_id=args.request_id)
    path = base + "/" + args.asset_id
    if args.action == "version":
        if bool(args.file) == bool(args.version_id):
            raise CliError("提供新版本文件，或使用 --select 选择已有版本。")
        if args.version_id:
            return request(client, "PATCH", path, json={"current_version_id": args.version_id})
        return upload(client, base + "/upload", args.file, data={"asset_id": args.asset_id}, request_id=args.request_id)
    if args.action == "repair":
        return upload(client, path + "/repair", args.file, data={"version_id": args.version_id} if args.version_id else {})
    if args.action == "reveal":
        return request(client, "POST", path + "/reveal", json={"version_id": args.version_id})
    if args.action == "tag":
        return request(client, "PATCH", path, json={"tags": args.tags})
    if args.action == "rename":
        return request(client, "PATCH", path, json={"name": args.name})
    method, suffix = {"show": ("GET", ""), "trash": ("DELETE", ""), "restore": ("POST", "/restore"), "purge": ("DELETE", "/permanent")}[args.action]
    return request(client, method, path + suffix)


def canvas_command(client, args):
    path = f"/api/projects/{args.project_id}/canvas"
    if args.action == 'render-frame':
        body = {'request_id': args.request_id or uuid.uuid4().hex, 'scale': args.scale}
        if args.name:
            body['name'] = args.name
        return request(client, 'POST', f'/api/projects/{args.project_id}/frames/{args.frame_id}/render-image', json=body)
    if args.action == "inspect":
        return request(client, "GET", path)
    if args.action == "apply":
        payload = json.loads(args.file.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or not isinstance(payload.get("revision"), int):
            raise CliError("画布 JSON 必须包含整数 revision。请先 canvas inspect，再修改副本。", "missing_revision")
        if args.request_id:
            payload["request_id"] = args.request_id
        payload.setdefault("request_id", uuid.uuid4().hex)
        return request(client, "PUT", path, json=payload)
    if args.asset_id:
        asset = request(client, "GET", "/api/assets/" + args.asset_id)
    else:
        asset = request(client, "GET", "/api/versions/" + args.version_id)["asset"]
    version_id = args.version_id or asset["current_version_id"]
    if not any(version["id"] == version_id for version in asset["versions"]):
        raise CliError("所选版本属于其他资产。", "version_mismatch")
    request_id = args.request_id or uuid.uuid4().hex
    node_id = uuid.uuid5(uuid.NAMESPACE_URL, f"manju:{args.project_id}:{request_id}").hex
    node = {"id": node_id, "type": "media", "position": {"x": args.x, "y": args.y}, "data": {"asset_version_id": version_id}}
    canvas = request(client, "GET", path)
    existing = next((item for item in canvas["nodes"] if item["id"] == node_id), None)
    if existing:
        if existing != node:
            raise CliError("此 request-id 对应的卡片已存在且内容不同。请检查卡片或使用新标识。", "idempotency_conflict")
        return canvas
    if args.revision is not None and args.revision != canvas["revision"]:
        raise CliError("画布修订号已变化，请重新 inspect 并合并修改。", "revision_conflict", revision=canvas["revision"])
    canvas["nodes"].append(node)
    canvas["request_id"] = request_id
    return request(client, "PUT", path, json=canvas)


def run_command(client, args):
    if args.command == "doctor":
        return {"health": request(client, "GET", "/api/health"), "storage": request(client, "GET", "/api/settings/storage")}
    if args.command == "project":
        return project_command(client, args)
    if args.command == "asset":
        return asset_command(client, args)
    if args.command == "canvas":
        return canvas_command(client, args)
    if args.command == 'production':
        return production_command(client, args)
    if args.command == 'timeline':
        return timeline_command(client, args)
    if args.command == 'canvas-run':
        return canvas_run_command(client, args)
    if args.command == 'lipsync':
        if args.action == 'settings':
            return request(client,'GET','/api/lipsync/settings')
        body=json.loads(args.file.read_text(encoding='utf-8-sig'))
        body.update(kind='video',workflow_id='builtin-latentsync15-local')
        body['request_id']=args.request_id or body.get('request_id') or uuid.uuid4().hex
        return request(client,'POST','/api/generations',json=body)
    if args.command == "subject":
        return subject_command(client, args)
    if args.command == "workflow":
        return workflow_command(client, args)
    if args.command == "generate":
        return generate_command(client, args)
    if args.command == "video":
        if args.action == "status":
            return request(client, "GET", "/api/video/settings")
        return request(client, "PUT", "/api/video/settings", json=json.loads(args.file.read_text(encoding="utf-8-sig")))
    if args.command == "job":
        return job_command(client, args)
    if args.command == "task":
        if args.action == "list":
            return request(client, "GET", "/api/tasks")
        return request(client, "POST", f"/api/tasks/{args.task_id}/retry")
    if args.command == "comfy":
        if args.action == "status":
            return request(client, "GET", "/api/comfy")
        if args.action == "scan":
            payload = {"path": str(args.path.expanduser().resolve())} if args.path else {}
            return request(client, "POST", "/api/comfy/scan", json=payload)
        if args.action == "configure":
            return request(client, "PUT", "/api/comfy/settings", json={"installation_path": str(args.installation_path.expanduser().resolve()), "port": args.port})
        if args.action == "logs":
            return request(client, "GET", "/api/comfy/logs", params={"limit": args.limit})
        if args.action == "stop":
            return request(client, "POST", "/api/comfy/stop", json={"force": args.force})
        return request(client, "POST", "/api/comfy/start", json={})
    base = "/api/settings/storage"
    if args.action == "inspect":
        return request(client, "GET", base)
    if args.action == "migrate":
        return request(client, "POST", base + "/migrate", json={"target": str(args.target.expanduser().resolve())})
    return request(client, "POST", base + "/migration/" + args.action)


def subject_command(client, args):
    base = "/api/subjects"
    if args.action == "list":
        return request(client, "GET", base, params={"search": args.search, "offset": args.offset, "limit": args.limit, **({"kind": args.kind} if args.kind else {})})
    if args.action in ("create", "update"):
        changes = {key: getattr(args, key) for key in ("name", "description", "kind", "image_version_ids", "voice_version_id", "voice_name", "voice_transcript") if getattr(args, key) is not None}
        if args.clear_voice:
            if args.voice_name or args.voice_transcript:
                raise CliError("--clear-voice 不能同时设置非空音色名称或文本。")
            changes.update(voice_version_id=None, voice_name="", voice_transcript="")
        if args.action == "create":
            if args.version_id:
                changes["version_id"] = args.version_id
            return request(client, "POST", base, json=changes, headers={"X-Request-ID": args.request_id or uuid.uuid4().hex})
        if not changes:
            raise CliError("请提供主体名称、描述、类型、完整图片列表或音色修改。")
        return request(client, "PATCH", base + "/" + args.subject_id, json=changes)
    path = base + "/" + args.subject_id
    return request(client, "GET" if args.action == "show" else "DELETE", path)


def workflow_command(client, args):
    base = "/api/workflows"
    if args.action == "list":
        return request(client, "GET", base, params={"include_video":True,"include_audio":True, **({"mode": args.mode} if args.mode else {})})
    if args.action in ("create", "import", "update"):
        payload = json.loads(args.file.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise CliError("工作流 JSON 需要是对象。")
        if args.action == "import":
            if "api_graph" not in payload:
                payload = {"api_graph": payload}
            payload["name"] = args.name or payload.get("name") or args.file.stem
            payload["mode"] = args.mode or payload.get("mode", "text_to_image")
            return request(client, "POST", base + "/import", json=payload)
        if args.action == "create":
            return request(client, "POST", base, json=payload)
        return request(client, "PUT", base + "/" + args.workflow_id, json=payload)
    method, suffix = {"get": ("GET", ""), "duplicate": ("POST", "/duplicate"), "delete": ("DELETE", ""), "validate": ("POST", "/validate")}[args.action]
    return request(client, method, base + "/" + args.workflow_id + suffix)


def generate_command(client, args):
    speech_options = any(getattr(args,key,None) is not None for key in ("subject_node_id","language","speed","emotion","emotion_intensity"))
    if speech_options and args.kind != "audio":
        raise CliError("配音参数须与 --kind audio 一起使用。")
    video_options = args.kind == "video" or args.video_mode is not None or args.video_engine is not None or args.ref_image_size is not None or args.duration is not None or args.silent or args.first_frame or args.last_frame
    if args.file:
        payload = json.loads(args.file.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise CliError("生成请求 JSON 需要是对象。")
        if args.kind is not None or video_options or args.project_id or args.workflow_id or args.prompt or args.reference or args.mask_version_id or args.source_node_id or args.negative_prompt is not None or any(getattr(args, name) is not None for name in ("seed", "width", "height", "steps", "cfg", "denoise", "x", "y")):
            raise CliError("使用 --file 时请在 JSON 中填写项目、提示词和输入版本。")
    else:
        if video_options:
            if args.kind != "video":
                raise CliError("视频参数须与 --kind video 一起使用。")
            args.workflow_id = args.workflow_id or "builtin-h3-local"
        if args.kind == "audio":
            args.workflow_id = args.workflow_id or "builtin-indextts25-local"
        if not args.project_id or not args.workflow_id or not args.prompt:
            raise CliError("请提供 --project、--workflow、--prompt，或通过 --file 读取完整请求。")
        payload = {"project_id": args.project_id, "workflow_id": args.workflow_id, "prompt": args.prompt, "references": [{"version_id": value} for value in args.reference], "parameters": {name: getattr(args, name) for name in ("seed", "width", "height", "steps", "cfg", "denoise") if getattr(args, name) is not None}}
        if args.kind == "audio":
            payload["kind"] = "audio"
            if args.subject_node_id:
                payload["subject_node_id"] = args.subject_node_id
            payload["speech_options"] = {key:value for key,value in (("language",args.language),("speed",args.speed),("emotion",args.emotion),("intensity",args.emotion_intensity)) if value is not None}
        if args.kind == "video":
            payload.update(kind="video", video_mode=args.video_mode or ("frames" if args.first_frame or args.last_frame else "reference" if args.reference else "text"), duration=args.duration if args.duration is not None else 4, audio=not args.silent)
            payload["video_options"]={key:value for key,value in (("engine",args.video_engine),("ref_image_size",args.ref_image_size)) if value is not None}
            for role, version in (("first_frame",args.first_frame),("last_frame",args.last_frame)):
                if version:
                    payload["references"].append({"version_id":version,"role":role})
        if args.negative_prompt is not None:
            payload["negative_prompt"] = args.negative_prompt
        if args.source_node_id:
            payload["source_node_id"] = args.source_node_id
        if args.mask_version_id:
            payload["mask_version_id"] = args.mask_version_id
        if args.x is not None or args.y is not None:
            if args.x is None or args.y is None:
                raise CliError("结果位置需要同时提供 --x 与 --y。")
            payload["placement"] = {"x": args.x, "y": args.y}
    if args.request_id:
        payload["request_id"] = args.request_id
    return request(client, "POST", "/api/generations", json=payload)


def job_command(client, args):
    base = "/api/generations"
    if args.action == "list":
        params = {"limit": args.limit}
        if args.project_id:
            params["project_id"] = args.project_id
        return request(client, "GET", base, params=params)
    path = base + "/" + args.job_id
    if args.action == "show":
        return request(client, "GET", path)
    if args.action == "cancel":
        return request(client, "POST", path + "/cancel", json={"interrupt_running": args.interrupt_running})
    if args.action == "retry":
        return request(client, "POST", path + "/retry", json={"request_id": args.request_id} if args.request_id else {})
    if args.interval <= 0 or args.max_wait <= 0:
        raise CliError("等待间隔和最长等待时间须大于零。")
    deadline = time.monotonic() + args.max_wait
    while True:
        job = request(client, "GET", path)
        if job["status"] == "succeeded":
            return job
        if job["status"] in ("failed", "cancelled"):
            raise CliError(job.get("message") or "生成任务已结束。", "generation_" + job["status"], job=job)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CliError("等待达到时限，任务保留在后台。", "generation_wait_timeout", job=job)
        time.sleep(min(args.interval, remaining))


def production_command(client, args):
    action = args.action
    if action in ('show', 'wait', 'retry'):
        path = f'/api/production/renders/{args.job_id}'
        if action == 'show':
            return request(client, 'GET', path)
        if action == 'retry':
            return request(client, 'POST', path + '/retry')
        if args.interval <= 0 or args.max_wait <= 0:
            raise CliError('等待间隔和最长等待时间须大于零。')
        deadline = time.monotonic() + args.max_wait
        while True:
            result = request(client, 'GET', path)
            if result['status'] == 'succeeded':
                return result
            if result['status'] in ('failed', 'cancelled'):
                raise CliError('成片渲染未完成。', 'production_render_failed', job=result)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CliError('等待达到时限，成片任务保留在后台。', 'production_wait_timeout', job=result)
            time.sleep(min(args.interval, remaining))
    path = f'/api/projects/{args.project_id}/production'
    if action == 'inspect':
        return request(client, 'GET', path)
    if action == 'apply':
        body = json.loads(args.file.read_text(encoding='utf-8-sig'))
        if not isinstance(body, dict) or type(body.get('revision')) is not int:
            raise CliError('分镜JSON须包含整数revision；先production inspect再修改副本。', 'missing_revision')
        body['request_id'] = args.request_id or body.get('request_id') or uuid.uuid4().hex
        return request(client, 'PUT', path, json=body)
    if action == 'generate':
        body = {'request_id':args.request_id or uuid.uuid4().hex,'only_missing':not args.redo,'kinds':args.kinds or ['video','audio']}
        if args.revision is not None:
            body['revision'] = args.revision
        if args.shot_ids is not None:
            body['shot_ids'] = args.shot_ids
        return request(client, 'POST', path + '/generate', json=body)
    if action == 'render':
        body = {'request_id':args.request_id or uuid.uuid4().hex,'burn_subtitles':not args.no_subtitles}
        if args.name:
            body['name'] = args.name
        if args.revision is not None:
            body['revision'] = args.revision
        return request(client, 'POST', path + '/render', json=body)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise CliError('目标文件已存在，请使用新的文件名。', 'file_exists')
    with client.stream('GET', path + '/' + action) as response:
        if response.is_error:
            response.read()
            response_data(response)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('xb') as stream:
            for chunk in response.iter_bytes():
                stream.write(chunk)
    return {'path':str(output),'size':output.stat().st_size}


def timeline_command(client,args):
    if args.action in ('show','wait','retry'):
        return production_command(client,args)
    path=f'/api/projects/{args.project_id}/timeline'
    if args.action=='inspect':return request(client,'GET',path)
    if args.action=='apply':
        body=json.loads(args.file.read_text(encoding='utf-8-sig'))
        if not isinstance(body,dict) or type(body.get('revision')) is not int:
            raise CliError('多轨JSON须包含整数revision。','missing_revision')
        body['request_id']=args.request_id or body.get('request_id') or uuid.uuid4().hex
        return request(client,'PUT',path,json=body)
    body={'revision':args.revision,'request_id':args.request_id or uuid.uuid4().hex}
    if args.action=='render' and args.name:body['name']=args.name
    return request(client,'POST',path+'/'+args.action,json=body)


def canvas_run_command(client,args):
    if args.action in ('show','wait','retry','cancel'):
        path=f'/api/canvas-runs/{args.run_id}'
        if args.action=='show':return request(client,'GET',path)
        if args.action in ('retry','cancel'):return request(client,'POST',path+'/'+args.action)
        if args.interval<=0 or args.max_wait<=0:raise CliError('等待参数须大于零。')
        deadline=time.monotonic()+args.max_wait
        while True:
            result=request(client,'GET',path)
            if result['status']=='succeeded':return result
            if result['status'] in ('failed','cancelled'):raise CliError('画布执行未完成。','canvas_run_failed',run=result)
            remaining=deadline-time.monotonic()
            if remaining<=0:raise CliError('等待达到时限，画布任务保留在后台。','canvas_run_timeout',run=result)
            time.sleep(min(args.interval,remaining))
    path=f'/api/projects/{args.project_id}/canvas-runs'
    if args.action=='list':return request(client,'GET',path)
    body=json.loads(args.file.read_text(encoding='utf-8-sig')) if args.file else {'scope':args.scope,'force':args.force}
    if args.node_ids:body['node_ids']=args.node_ids
    if args.revision is not None:body['revision']=args.revision
    if args.action=='start':body['request_id']=args.request_id or body.get('request_id') or uuid.uuid4().hex
    return request(client,'POST',path+('/plan' if args.action=='plan' else ''),json=body)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        args = build_parser().parse_args(arguments)
        normalize_arguments(args)
        if args.command == "serve":
            import uvicorn
            if args.data_dir:
                os.environ["MANJU_DATA_DIR"] = str(Path(args.data_dir).expanduser().resolve())
            if args.config_file:
                os.environ["MANJU_CONFIG_FILE"] = str(Path(args.config_file).expanduser().resolve())
            uvicorn.run("manju.app:create_app", factory=True, host="127.0.0.1", port=args.port, access_log=False)
            return 0
        url = getattr(args, "url", os.environ.get("MANJU_URL", "http://127.0.0.1:8765"))
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise CliError("URL 必须是本机 HTTP 回环地址，例如 http://127.0.0.1:8765。", "invalid_url")
        with httpx.Client(base_url=url, timeout=getattr(args, "timeout", 1800), trust_env=False) as client:
            result = run_command(client, args)
        print(json.dumps(result, ensure_ascii=False, indent=None if getattr(args, "json", False) else 2, allow_nan=False))
        return 0
    except CliError as error:
        detail = error.detail
    except httpx.HTTPError as error:
        detail = {"code": "connection_error", "message": f"无法完成本地服务请求。请先运行 manju serve，或双击 start.cmd。{error}"}
    except (OSError, ValueError) as error:
        detail = {"code": "local_file_error", "message": str(error)}
    print(json.dumps({"error": detail}, ensure_ascii=False), file=sys.stderr)
    return 1

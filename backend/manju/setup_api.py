"""Small API surface for the local first-run controller."""
from fastapi import APIRouter, Body, Request
from fastapi.responses import PlainTextResponse
from pathlib import Path
from .setup_service import POLICY_VERSION

router = APIRouter(prefix='/api/setup', tags=['setup'])


@router.get('')
def state(request: Request):
    return request.app.state.setup.status()


@router.patch('')
def configure(request: Request, body: dict = Body(...)):
    return request.app.state.setup.select(body)


@router.get('/catalog')
def catalog(request: Request):
    return request.app.state.setup.catalog


@router.get('/directories')
def directories(request: Request, path: str | None = None):
    return request.app.state.setup.browse(path)


@router.get('/models')
def models(request: Request):
    return request.app.state.setup.model_scan()


@router.post('/jobs', status_code=202)
def start_job(request: Request, body: dict = Body(...)):
    return request.app.state.setup.start(body.get('kind'), body)


@router.post('/jobs/cancel')
def cancel_job(request: Request):
    return request.app.state.setup.jobs.cancel()


@router.get('/readiness')
def readiness(request: Request):
    return request.app.state.setup.readiness()


@router.post('/complete')
def complete(request: Request, body: dict = Body(...)):
    return request.app.state.setup.complete(body)


@router.get('/documents')
def documents():
    return {'version': POLICY_VERSION, 'privacy': [
        {'title': '本机保存', 'text': '项目、画布、素材、模型位置和准备进度保存在本机。基础画布和游客模式不要求云端账号。浏览目录和导入模型只在你选择的位置执行。'},
        {'title': '联网行为', 'text': '首次准备会从官方分发源下载 Python、Node.js、ComfyUI、依赖和媒体工具；扫描模型分享会访问夸克。使用在线模型或发布分享时，相关内容会发送给你选择的服务。'},
        {'title': '账号与分享', 'text': '亦可账号通过官方网页授权连接，本项目不接收你的账号密码。连接凭证保存在本机配置中；连接账号不会自动上传素材，发布分享需要你主动操作。夸克下载遵循其官方网页规则。'},
        {'title': '控制与记录', 'text': '你可以使用游客模式、断开亦可账号、取消安装任务和修改存储位置。系统记录你在本机确认的说明版本与时间。安装日志可能包含本机路径，向他人反馈问题前请自行检查。'},
    ], 'manual': [
        {'title': '准备与进入', 'text': '先选择 ComfyUI，再选择需要的模型分类。下载夸克分享后选择下载目录，导入到默认或自定义模型位置，执行完整校验。所选模型和组件通过检查后即可进入画布；也可以明确选择仅使用基础画布。'},
        {'title': '模型与组件', 'text': '模型权重、配置和 tokenizer 缺一不可。文件大小正确只代表待校验，SHA256 通过后才算完整。语音和口型使用独立运行环境；新增节点或模型路径后需要重启 ComfyUI。'},
        {'title': '模型许可', 'text': '项目源码的 MIT 不代表模型可以任意商用。Qwen Image 使用研究用途许可，MiniMax H3 有地区及商业服务条件，Remacri 限非商业用途。下载前请阅读模型步骤中的来源与许可证说明；完整文件位于 release/MODEL-LICENSES.md。'},
        {'title': '画布与素材', 'text': '在画布中添加文本、图片、音频和视频，连接素材并选择工作流生成。生成耗时与显存有关，失败时可查看任务原因。游客也能使用本地创作功能。'},
        {'title': '备份与外部服务', 'text': '定期导出项目并备份素材。删除原始文件可能导致引用失效；移动 Python 环境或项目路径后需重新准备环境。夸克和亦可的网页注册、登录与下载由相应服务处理。'},
    ]}


@router.get('/model-licenses', response_class=PlainTextResponse)
def model_licenses():
    return (Path(__file__).resolve().parents[2] / 'release' / 'MODEL-LICENSES.md').read_text(encoding='utf-8')

"""Explicit, local-only graceful shutdown for the CLI-owned server."""
from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from .store import DomainError

router = APIRouter(prefix='/api/system')


def shutdown_status(request: Request):
    state = request.app.state
    counts = {}
    with state.store.lock:
        for table, statuses, label in (
            ('generation_jobs', ('pending', 'submitting', 'queued', 'running', 'collecting', 'unknown'), '生成任务'),
            ('production_renders', ('pending', 'running'), '视频合成'),
            ('canvas_runs', ('pending', 'running', 'cancelling'), '画布编排'),
            ('tasks', ('pending', 'running'), '素材处理'),
        ):
            marks = ','.join('?' for _ in statuses)
            count = state.store.conn.execute(f'SELECT COUNT(*) FROM {table} WHERE status IN ({marks})', statuses).fetchone()[0]
            if count:
                counts[label] = count
    if state.setup.jobs.busy:
        counts['安装或模型准备'] = 1
    if state.store.maintenance:
        counts['存储迁移'] = 1
    if state.active_writes:
        counts['保存或文件传输'] = state.active_writes
    return {
        'supported': callable(getattr(state, 'request_shutdown', None)),
        'shutting_down': state.shutting_down,
        'busy': counts,
        'comfy': state.comfy.status(),
    }


@router.get('/shutdown')
def status(request: Request):
    return shutdown_status(request)


@router.post('/shutdown', status_code=202)
async def shutdown(request: Request, body: dict = Body(...)):
    from fastapi.concurrency import run_in_threadpool

    if body.get('confirm') is not True or type(body.get('stop_comfy', True)) is not bool:
        raise DomainError(422, '请确认退出程序。', 'shutdown_confirmation_required')
    state = request.app.state
    # Set the gate on the event loop before awaiting: new writes and a second
    # shutdown cannot race the final busy check. Existing writes remain counted.
    if state.shutting_down:
        raise DomainError(409, '程序正在退出。', 'shutdown_in_progress')
    state.shutting_down = True
    try:
        current = await run_in_threadpool(shutdown_status, request)
        if not current['supported']:
            raise DomainError(409, '当前服务不支持网页退出，请通过项目 start.cmd 重新启动一次。', 'shutdown_unmanaged')
        if current['busy']:
            raise DomainError(409, '仍有任务或保存请求未结束，请完成后再退出。', 'shutdown_busy', busy=current['busy'])
        stopped_comfy = False
        if body.get('stop_comfy', True) and current['comfy']['managed']:
            # ComfyManager independently verifies ownership and queue state.
            # Never stop an external instance or force-cancel its work.
            await run_in_threadpool(state.comfy.stop, False)
            thread = state.comfy.operation_thread
            if thread:
                await run_in_threadpool(thread.join, 15)
            remaining = await run_in_threadpool(state.comfy.status)
            if remaining['managed']:
                raise DomainError(409, 'ComfyUI 尚未停止，请检查本地服务后重试。', 'shutdown_comfy_pending')
            stopped_comfy = True
        return JSONResponse({'accepted': True, 'stopped_comfy': stopped_comfy}, status_code=202,
                            background=BackgroundTask(state.request_shutdown))
    except BaseException:
        state.shutting_down = False
        raise

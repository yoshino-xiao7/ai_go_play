"""One persistent, cancellable setup operation at a time; refreshes only observe it."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import threading
import time
import uuid
import psutil
from .comfy import identity_process, process_identity
from .store import DomainError, now


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        for attempt in range(8):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 7: raise
                time.sleep(.025 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


class SetupCancelled(Exception):
    pass


class SetupJobs:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'job.json'
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.thread = None
        self.job = None
        runner = self.directory / 'runner.json'
        if runner.is_file():
            # Only recover children with the exact recorded PID, creation time,
            # executable and command line; never stop an unrelated process.
            for identity in json.loads(runner.read_text()).get('processes', []):
                process = identity_process(identity)
                if process:
                    try:
                        children = process.children(recursive=True)
                        for child in reversed(children): child.kill()
                        process.kill()
                        psutil.wait_procs([process, *children], timeout=5)
                    except psutil.Error: pass
            runner.unlink(missing_ok=True)
        if self.path.is_file():
            self.job = json.loads(self.path.read_text(encoding='utf-8'))
            if self.job['status'] in ('queued', 'running'):
                self.job.update(status='interrupted', message='服务已重启。已完成文件会保留，请重试继续。', finished_at=now())
                atomic_json(self.path, self.job)
        self.last_save = 0.

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.job)

    @property
    def busy(self):
        with self.lock:
            return bool(self.thread and self.thread.is_alive())

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise SetupCancelled()

    def track_process(self, pid):
        try:
            process = psutil.Process(pid)
            identities = []
            for child in [process, *process.children(recursive=True)]:
                try: identities.append(process_identity(child))
                except psutil.Error: pass
            atomic_json(self.directory / 'runner.json', {'processes': identities})
        except psutil.NoSuchProcess: pass

    def clear_process(self):
        (self.directory / 'runner.json').unlink(missing_ok=True)

    def update(self, **values):
        with self.lock:
            self.job.update(values, updated_at=now())
            if time.monotonic() - self.last_save > .5 or values.get('status'):
                atomic_json(self.path, self.job)
                self.last_save = time.monotonic()

    def start(self, kind, operation):
        with self.lock:
            if self.busy:
                raise DomainError(409, '另一个准备任务正在执行，请等待或取消。', 'setup_busy')
            self.cancelled.clear()
            self.job = {'id': uuid.uuid4().hex, 'kind': kind, 'status': 'queued', 'progress': 0,
                        'message': '准备开始', 'started_at': now(), 'error': None, 'result': None}
            atomic_json(self.path, self.job)
            def execute():
                try:
                    self.update(status='running')
                    result = operation(self)
                    self.update(status='succeeded', progress=1, message='已完成', result=result, finished_at=now())
                except SetupCancelled:
                    self.update(status='cancelled', message='已取消，已完成的文件会保留。', finished_at=now())
                except Exception as error:
                    message = error.detail['message'] if isinstance(error, DomainError) else str(error)
                    code = error.detail.get('code') if isinstance(error, DomainError) else None
                    self.update(status='failed', error=message, error_code=code,
                                message='未完成，请检查原因后重试。', finished_at=now())
            self.thread = threading.Thread(target=execute, name='manju-setup-' + kind, daemon=True)
            self.thread.start()
            return self.snapshot()

    def cancel(self):
        self.cancelled.set()
        return self.snapshot()

    def close(self):
        self.cancelled.set()
        if self.thread:
            self.thread.join(timeout=15)

"""Discover local ComfyUI installations and manage only owned process trees."""
from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
import uuid

import httpx
import psutil

from .store import DomainError, now


INSTANCE_VARIABLE = "MANJU_COMFY_INSTANCE"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SKIP_SCAN_DIRECTORIES = {"models", "node_modules", ".git", ".venv", "venv", "python_embeded", "python_embedded", "site-packages", "windows", "program files", "program files (x86)", "$recycle.bin", "system volume information"}


def detect_installation(path: str | Path) -> dict | None:
    candidate = Path(path).expanduser().resolve()
    for comfy in (candidate, candidate / "ComfyUI"):
        if not (comfy / "main.py").is_file() or not (comfy / "server.py").is_file() or not (comfy / "comfy").is_dir():
            continue
        for container in (comfy.parent, comfy):
            for embedded in ("python_embeded", "python_embedded"):
                python = container / embedded / "python.exe"
                if python.is_file():
                    return {"path": str(container), "comfy_path": str(comfy), "python_path": str(python), "kind": "portable", "name": container.name}
        for container in (comfy, comfy.parent):
            for environment in (".venv", "venv"):
                for executable in (Path("Scripts/python.exe"), Path("bin/python")):
                    python = container / environment / executable
                    if python.is_file():
                        windowless = python.with_name("pythonw.exe")
                        if os.name == "nt" and windowless.is_file():
                            # A venv console redirector can give its base-Python
                            # child a new console despite CREATE_NO_WINDOW.
                            python = windowless
                        return {"path": str(comfy), "comfy_path": str(comfy), "python_path": str(python), "kind": "venv", "name": comfy.name}
    return None


def common_scan_roots() -> list[Path]:
    roots = [Path.cwd().parent, Path.home() / "Desktop", Path.home() / "Downloads", Path.home() / "Documents", Path.home() / "ComfyUI"]
    if os.name == "nt":
        roots.extend(Path(path) for path in ("D:/github", "C:/github", "C:/AI", "D:/AI", "E:/AI", "F:/AI", "C:/ComfyUI", "D:/ComfyUI"))
    return list(dict.fromkeys(root.resolve() for root in roots if root.is_dir()))


def scan_installations(path: str | None = None) -> dict:
    roots = [Path(path).expanduser().resolve()] if path else common_scan_roots()
    if path and not roots[0].is_dir():
        raise DomainError(404, "扫描目录不存在，请选择本机 ComfyUI 目录或其父目录。", "comfy_scan_path_missing")
    pending = deque((root, 0) for root in roots)
    visited, installations = set(), {}
    deadline = time.monotonic() + 4
    while pending and len(visited) < 2500 and time.monotonic() < deadline:
        current, depth = pending.popleft()
        if current in visited:
            continue
        visited.add(current)
        try:
            installation = detect_installation(current)
            if installation:
                installations[installation["comfy_path"]] = installation
                continue
            if depth >= 3:
                continue
            with os.scandir(current) as entries:
                children = [Path(entry.path) for entry in entries if entry.is_dir(follow_symlinks=False) and entry.name.casefold() not in SKIP_SCAN_DIRECTORIES and not entry.name.startswith(".")]
            pending.extend((child, depth + 1) for child in sorted(children)[:300])
        except (OSError, ValueError):
            continue
    return {"installations": sorted(installations.values(), key=lambda item: item["path"].casefold()), "scanned_roots": [str(root) for root in roots], "bounded": bool(pending)}


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DomainError(409, f"无法读取 ComfyUI 配置 {path.name}，请检查文件内容。", "comfy_config_invalid") from error
    if not isinstance(value, dict):
        raise DomainError(409, "ComfyUI 配置格式不正确。", "comfy_config_invalid")
    return value


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def process_identity(process: psutil.Process) -> dict:
    return {"pid": process.pid, "created": process.create_time(), "exe": process.exe(), "cmdline": process.cmdline()}


def identity_process(identity: dict, token: str | None = None) -> psutil.Process | None:
    try:
        process = psutil.Process(identity["pid"])
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return None
        if abs(process.create_time() - identity["created"]) > 0.001:
            return None
        if os.path.normcase(process.exe()) != os.path.normcase(identity["exe"]) or process.cmdline() != identity["cmdline"]:
            return None
        if token is not None and process.environ().get(INSTANCE_VARIABLE) != token:
            return None
        return process
    except (psutil.Error, KeyError, TypeError, ValueError, OSError):
        return None


class ComfyManager:
    def __init__(self, bootstrap_config: Path):
        parent = bootstrap_config.parent.expanduser()
        parent.mkdir(parents=True, exist_ok=True)
        directory = parent.resolve() / (bootstrap_config.stem + ".comfy")
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory.resolve()
        self.settings_path = self.directory / "settings.json"
        self.process_path = self.directory / "process.json"
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.monitor_thread = None
        self.operation_thread = None
        self.process = None
        self.startup_timeout = 180
        self.config_error = None
        try:
            self.settings = _read_json(self.settings_path)
            self.record = _read_json(self.process_path)
        except DomainError as error:
            self.settings, self.record = {}, {}
            self.config_error = str(error)
        self.client = httpx.Client(timeout=httpx.Timeout(0.7), trust_env=False, follow_redirects=False)

    def start_monitor(self) -> None:
        with self.lock:
            if self.record.get("status") == "stopping":
                if self._owned_processes():
                    self.operation_thread = threading.Thread(target=self._stop_worker, name="manju-comfy-stop-recovery", daemon=True)
                    self.operation_thread.start()
                else:
                    self.record.update(status="stopped", identity=None, descendants=[], error=None)
                    self._save_record()
        self.monitor_thread = threading.Thread(target=self._monitor, name="manju-comfy-monitor", daemon=True)
        self.monitor_thread.start()

    def close(self) -> None:
        self.stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=3)
        if self.operation_thread:
            self.operation_thread.join(timeout=10)
        self.client.close()

    def _monitor(self) -> None:
        while not self.stop_event.wait(1):
            try:
                with self.lock:
                    if self.record and self.record.get("status") in ("starting", "running", "error", "stopping"):
                        self._status_locked()
            except (OSError, DomainError, httpx.HTTPError, psutil.Error):
                continue

    def _owned_processes(self) -> list[psutil.Process]:
        token = self.record.get("token")
        if not token or not self.record.get("identity"):
            return []
        identities = [self.record["identity"], *self.record.get("descendants", [])]
        owned = {}
        for identity in identities:
            process = identity_process(identity, token)
            if process:
                owned[process.pid] = process
        for process in list(owned.values()):
            try:
                for child in process.children(recursive=True):
                    if child.create_time() >= process.create_time():
                        owned[child.pid] = child
            except psutil.Error:
                continue
        return list(owned.values())

    def _remember_descendants(self, processes: list[psutil.Process]) -> None:
        descendants = []
        root_pid = self.record.get("identity", {}).get("pid")
        for process in processes:
            if process.pid == root_pid:
                continue
            try:
                descendants.append(process_identity(process))
            except psutil.Error:
                continue
        descendants.sort(key=lambda item: item["pid"])
        if descendants != self.record.get("descendants", []):
            self.record["descendants"] = descendants
            self._save_record()

    def _save_record(self) -> None:
        _write_json(self.process_path, self.record)

    @property
    def port(self) -> int:
        value = self.settings.get("port", 8188)
        return value if isinstance(value, int) and 1024 <= value <= 65535 else 8188

    def _healthy(self, port: int) -> tuple[bool, dict | None]:
        try:
            response = self.client.get(f"http://127.0.0.1:{port}/system_stats")
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("system"), dict) or not isinstance(data.get("devices"), list):
                return False, None
        except (httpx.HTTPError, ValueError):
            return False, None
        queue = None
        try:
            response = self.client.get(f"http://127.0.0.1:{port}/queue")
            response.raise_for_status()
            data = response.json()
            if isinstance(data.get("queue_running"), list) and isinstance(data.get("queue_pending"), list):
                queue = {"running": len(data["queue_running"]), "pending": len(data["queue_pending"])}
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        return True, queue

    @staticmethod
    def _port_open(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.15)
            return connection.connect_ex(("127.0.0.1", port)) == 0

    @staticmethod
    def _owns_listener(processes: list[psutil.Process], port: int) -> bool:
        for process in processes:
            try:
                if any(connection.status == psutil.CONN_LISTEN and connection.laddr.port == port for connection in process.net_connections(kind="tcp")):
                    return True
            except psutil.Error:
                continue
        return False

    def status(self) -> dict:
        with self.lock:
            return self._status_locked()

    def _status_locked(self) -> dict:
        path = self.settings.get("installation_path")
        installation = detect_installation(path) if path else None
        processes = self._owned_processes()
        healthy, queue = self._healthy(self.port)
        managed = bool(processes)
        error = self.config_error
        status = "stopped" if installation else "not_configured"
        if managed:
            self._remember_descendants(processes)
            if self.record.get("status") == "stopping":
                status = "stopping"
            elif healthy and self._owns_listener(processes, self.port):
                status = "running"
                self.record["was_ready"] = True
            elif healthy:
                status, error = "port_conflict", "配置端口上的 ComfyUI 属于其他进程。请查看托管启动日志。"
            elif time.time() - self.record.get("started_epoch", 0) > self.startup_timeout:
                status, error = "error", "ComfyUI 尚未通过健康检查，请查看启动日志。可以继续等待或停止后重试。"
            else:
                status = "starting"
            if status != self.record.get("status") or error != self.record.get("error"):
                self.record.update(status=status, error=error)
                self._save_record()
        elif self.record.get("status") == "stopping":
            status = "stopping"
        elif healthy:
            status = "external"
            error = "这是已在外部启动的 ComfyUI，可打开使用。工作台只停止由自己启动的服务。"
        elif self._port_open(self.port):
            status, error = "port_conflict", f"端口 {self.port} 已被其他服务占用，请更换端口。"
        elif self.record.get("status") in ("starting", "running", "error", "port_conflict"):
            status = "error"
            code = self.process.poll() if self.process is not None else None
            error = f"托管 ComfyUI 已退出{f'（代码 {code}）' if code is not None else ''}，请查看日志后重试。"
            if error != self.record.get("error") or self.record.get("status") != "error":
                self.record.update(status="error", error=error)
                self._save_record()
        if path and not installation and not managed:
            status, error = "error", "保存的安装目录或配套 Python 已不存在，请重新扫描并选择。"
        if self.config_error:
            status = "error"
        return {"status": status, "installation": installation, "installation_path": path, "port": self.port, "base_url": f"http://127.0.0.1:{self.port}", "managed": managed, "pid": processes[0].pid if processes else None, "can_start": bool(installation and not managed and not healthy and status not in ("port_conflict", "stopping") and not self.config_error), "can_stop": bool(managed and status != "stopping"), "error": error, "queue": queue if healthy else None, "started_at": self.record.get("started_at") if managed else None}

    def configure(self, installation_path: str, port: int) -> dict:
        if not isinstance(installation_path, str) or not installation_path.strip():
            raise DomainError(422, "请选择 ComfyUI 安装目录。", "comfy_installation_required")
        if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
            raise DomainError(422, "端口须为 1024 至 65535 的整数。", "comfy_invalid_port")
        installation = detect_installation(installation_path)
        if not installation:
            raise DomainError(422, "目录中未找到完整 ComfyUI 和 portable / .venv Python 环境。", "comfy_installation_invalid")
        with self.lock:
            if self._owned_processes() or self.record.get("status") == "stopping":
                if self.settings.get("installation_path") == installation["path"] and self.port == port:
                    return self._status_locked()
                raise DomainError(409, "请先停止托管服务，再修改安装目录或端口。", "comfy_running")
            settings = {"installation_path": installation["path"], "port": port}
            _write_json(self.settings_path, settings)
            self.settings = settings
            self.config_error = None
            record = {"status": "stopped", "log_path": self.record.get("log_path")}
            _write_json(self.process_path, record)
            self.record = record
            return self._status_locked()

    def start(self) -> dict:
        with self.lock:
            state = self._status_locked()
            if state["managed"]:
                return state
            if state["status"] == "external":
                raise DomainError(409, "该端口已有外部 ComfyUI，请直接打开或选择其他端口。", "comfy_external")
            if state["status"] == "port_conflict":
                raise DomainError(409, state["error"], "comfy_port_conflict")
            if not state["can_start"]:
                raise DomainError(422, state["error"] or "请先扫描并保存 ComfyUI 安装目录。", "comfy_not_configured")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                if os.name == "nt":
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                try:
                    probe.bind(("127.0.0.1", self.port))
                except OSError as error:
                    raise DomainError(409, f"端口 {self.port} 无法使用，请选择其他端口。", "comfy_port_conflict") from error
            installation = state["installation"]
            token = uuid.uuid4().hex
            log_directory = self.directory / "logs"
            log_directory.mkdir(parents=True, exist_ok=True)
            log_path = log_directory / f"comfy-{time.strftime('%Y%m%d-%H%M%S')}-{token[:8]}.log"
            command = [installation["python_path"], "-s", "-u", str(Path(installation["comfy_path"]) / "main.py")]
            if installation["kind"] == "portable":
                command.append("--windows-standalone-build")
            command.extend(["--listen", "127.0.0.1", "--port", str(self.port), "--disable-auto-launch"])
            model_paths = self.directory / 'ai-go-play-model-paths.yaml'
            if model_paths.is_file():
                command.extend(['--extra-model-paths-config', str(model_paths)])
            environment = os.environ.copy()
            environment.pop("PYTHONHOME", None)
            environment.pop("PYTHONPATH", None)
            environment[INSTANCE_VARIABLE] = token
            environment["PYTHONIOENCODING"] = "utf-8"
            options = {"cwd": installation["path"], "stdin": subprocess.DEVNULL, "stderr": subprocess.STDOUT, "close_fds": True, "env": environment}
            if os.name == "nt":
                options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                options["start_new_session"] = True
            try:
                with log_path.open("ab", buffering=0) as output:
                    self.process = subprocess.Popen(command, stdout=output, **options)
                identity = process_identity(psutil.Process(self.process.pid))
                self.record = {"status": "starting", "error": None, "token": token, "identity": identity, "descendants": [], "started_at": now(), "started_epoch": time.time(), "log_path": str(log_path), "was_ready": False}
                self._save_record()
            except (OSError, psutil.Error) as error:
                if self.process is not None and self.process.poll() is None:
                    self.process.terminate()
                self.record = {"status": "error", "error": str(error), "log_path": str(log_path)}
                self._save_record()
                raise DomainError(500, f"无法启动 ComfyUI，请检查 Python 与安装路径。{error}", "comfy_start_failed") from error
            return {**state, "status": "starting", "managed": True, "pid": identity["pid"], "can_start": False, "can_stop": True, "error": None, "started_at": self.record["started_at"]}

    def stop(self, force: bool = False) -> dict:
        with self.lock:
            state = self._status_locked()
            if state["status"] == "stopping":
                return state
            if not state["managed"]:
                if state["status"] in ("external", "port_conflict"):
                    raise DomainError(409, "此服务由工作台之外的进程运行，无法在这里停止。", "comfy_external")
                recorded_pid = self.record.get("identity", {}).get("pid") if self.record.get("identity") else None
                if recorded_pid and psutil.pid_exists(recorded_pid):
                    raise DomainError(409, "进程身份与托管记录不符，停止操作已拒绝。", "comfy_ownership_lost")
                return state
            queue = state["queue"]
            busy = queue and (queue["running"] > 0 or queue["pending"] > 0)
            unknown_queue = queue is None and self.record.get("was_ready")
            if not force and (busy or unknown_queue):
                raise DomainError(409, "ComfyUI 仍有排队或运行任务，或暂时无法确认队列。强制停止会中断这些任务。", "comfy_queue_busy", queue=queue, requires_confirmation=True)
            self.record["status"] = "stopping"
            self._save_record()
            self.operation_thread = threading.Thread(target=self._stop_worker, name="manju-comfy-stop", daemon=True)
            self.operation_thread.start()
            return {**state, "status": "stopping", "can_stop": False}

    def _stop_worker(self) -> None:
        try:
            with self.lock:
                processes = self._owned_processes()
                self._remember_descendants(processes)
                identities = [process_identity(process) for process in processes]
            for identity in reversed(identities):
                process = identity_process(identity)
                if process:
                    try:
                        process.terminate()
                    except psutil.NoSuchProcess:
                        pass
            _, alive = psutil.wait_procs(processes, timeout=5)
            for process in alive:
                identity = next(item for item in identities if item["pid"] == process.pid)
                verified = identity_process(identity)
                if verified:
                    verified.kill()
            psutil.wait_procs(alive, timeout=3)
            deadline = time.monotonic() + 2
            while self._port_open(self.port) and time.monotonic() < deadline:
                time.sleep(0.05)
            with self.lock:
                if self._owned_processes():
                    raise RuntimeError("仍有托管子进程未退出，请查看进程权限。")
                error = "托管进程已停止，但端口仍被其他服务占用。" if self._port_open(self.port) else None
                self.record.update(status="stopped", identity=None, descendants=[], error=error)
                self._save_record()
        except (psutil.Error, OSError, RuntimeError) as error:
            with self.lock:
                self.record.update(status="error", error=f"停止失败：{error}")
                self._save_record()

    def logs(self, limit: int = 200) -> dict:
        with self.lock:
            path_value = self.record.get("log_path")
        if not path_value:
            return {"lines": [], "path": None, "truncated": False}
        path = Path(path_value).resolve()
        if not path.is_relative_to((self.directory / "logs").resolve()):
            raise DomainError(409, "保存的日志路径无效。", "comfy_log_path_invalid")
        if not path.is_file():
            return {"lines": [], "path": str(path), "truncated": False}
        with path.open("rb") as stream:
            size = stream.seek(0, 2)
            stream.seek(max(0, size - 256 * 1024))
            text = stream.read().decode("utf-8", errors="replace")
        lines = ANSI_ESCAPE.sub("", text).splitlines()
        if size > 256 * 1024 and lines:
            lines = lines[1:]
        return {"lines": lines[-limit:], "path": str(path), "truncated": size > 256 * 1024 or len(lines) > limit}

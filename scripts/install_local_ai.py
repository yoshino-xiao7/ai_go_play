"""Install pinned Windows speech/lip-sync runtimes without modifying ComfyUI packages."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zipfile
from urllib.parse import unquote, urlsplit


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'backend'))
from manju.download_sources import artifact_urls, managed_python_sources, run_from_registry
SUPPORT = PROJECT / "scripts" / "local_ai"
OWNER = "ai-go-play-local-ai-v1"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_media_settings(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def usable_media_binary(path, name, env):
    try:
        result = subprocess.run(
            [str(path), '-version'], env=env, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=8,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        return result.returncode == 0 and result.stdout.startswith(f'{name} version '.encode())
    except (OSError, subprocess.TimeoutExpired):
        return False


def find_system_media(env, saved_paths=None):
    names = ('ffmpeg', 'ffprobe')
    configured = {name: env.get(f'MANJU_{name.upper()}') for name in names}
    search_path = [Path(value.strip('"')) for value in env.get('PATH', '').split(os.pathsep) if value.strip('"')]
    winget = Path(env['LOCALAPPDATA']) / 'Microsoft/WinGet/Packages' if env.get('LOCALAPPDATA') else None
    found = {}
    for name, sibling in (names, names[::-1]):
        executable = name + '.exe'
        candidates = [configured[name]]
        if configured[sibling]:
            candidates.append(Path(configured[sibling]).with_name(executable))
        candidates.extend(folder / executable for folder in search_path)
        if winget:
            for package in sorted(winget.glob('*FFmpeg*')):
                candidates.extend(sorted(package.rglob(executable)))
        candidates.extend(Path(drive) / 'ffmpeg/bin' / executable for drive in ('C:/', 'D:/'))
        if saved_paths and isinstance(saved_paths.get(name), str):
            candidates.append(saved_paths[name])
        for path in dict.fromkeys(Path(item).absolute() for item in candidates if item):
            if path.is_file() and usable_media_binary(path, name, env):
                found[name] = str(path)
                break
        else:
            return None
    return found


def child_environment(root, ffmpeg=None, offline=False):
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE", "HF_DATASETS_CACHE"):
        env.pop(key, None)
    env.update(PYTHONNOUSERSITE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
               UV_CACHE_DIR=str(root / "cache" / "uv"), UV_PYTHON_INSTALL_DIR=str(root / "python"),
               UV_PYTHON_PREFERENCE="only-managed", UV_NO_CONFIG="1", UV_NO_PROJECT="1", UV_LINK_MODE="copy",
               HF_HOME=str(root / "cache" / "huggingface"), MODELSCOPE_CACHE=str(root / "cache" / "modelscope"),
               NUMBA_CACHE_DIR=str(root / "cache" / "numba"), XDG_CACHE_HOME=str(root / "cache" / "xdg"),
               TEMP=str(root / "tmp"), TMP=str(root / "tmp"))
    for directory in ("tmp", "cache/uv", "cache/huggingface", "cache/modelscope", "cache/numba", "cache/xdg"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    if ffmpeg:
        env["PATH"] = str(Path(ffmpeg).parent) + os.pathsep + env.get("PATH", "")
        env["IMAGEIO_FFMPEG_EXE"] = str(ffmpeg)
    if offline:
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    return env


def install_packages(command, *, log, env, cwd=None, timeout=3600):
    def attempt(child, host):
        print('Python package index:', host, flush=True)
        return run(command, log=log, env=child, cwd=cwd, timeout=timeout)
    return run_from_registry('pypi', env, attempt)


def run(command, *, log, env, cwd=None, timeout=3600):
    command = [str(item) for item in command]
    print("Running:", subprocess.list2cmdline(command), flush=True)
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as stream:
        stream.write(("\n$ " + subprocess.list2cmdline(command) + "\n").encode("utf-8"))
        stream.flush()
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            started = time.monotonic()
            while True:
                try:
                    code = process.wait(timeout=min(20, max(1, timeout - (time.monotonic() - started))))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() - started >= timeout:
                        raise TimeoutError(f"Timed out; read {log}")
                    print(f"  Still running ({int(time.monotonic() - started)}s); log: {log}", flush=True)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    if code:
        tail = log.read_text(encoding="utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"Command failed ({code}). Log: {log}\n{tail}")


def download(spec, cache, *, on_progress=None, timeout=90, env=None):
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (spec["sha256"] + ".zip")
    if target.is_file():
        if on_progress:
            on_progress("verify")
        if digest(target) == spec["sha256"]:
            return target
    part = target.with_suffix(".partial")
    urls = artifact_urls(spec, env)
    attempt_count = max(3, len(urls))
    failures = []
    # A failed download is never accepted as a finished archive.
    for attempt in range(attempt_count):
        url = urls[attempt % len(urls)]
        host = urlsplit(url).hostname
        print("Downloading from:", host, flush=True)
        try:
            if on_progress:
                on_progress("connect", attempt=attempt + 1, attempts=attempt_count, host=host)
            with urllib.request.urlopen(url, timeout=timeout) as response, part.open("wb") as output:
                length = response.headers.get("Content-Length", "")
                total = int(length) if length.isdecimal() and int(length) > 0 else None
                received, last_update = 0, time.monotonic()
                if on_progress:
                    on_progress("download", received=received, total=total)
                update_interval = 0.5 if on_progress else 15
                while chunk := response.read1(1024 * 1024):
                    output.write(chunk)
                    received += len(chunk)
                    if time.monotonic() - last_update >= update_interval:
                        if on_progress:
                            on_progress("download", received=received, total=total)
                        else:
                            print(f"  Downloaded {received / 1024**2:.1f} MiB", flush=True)
                        last_update = time.monotonic()
            if total is not None and received != total:
                raise OSError(f"下载提前结束：收到 {received} / {total} 字节")
            if on_progress:
                on_progress("download", received=received, total=total)
                on_progress("verify")
            if digest(part) != spec["sha256"]:
                raise ValueError("下载的压缩包 SHA-256 校验失败")
            part.replace(target)
            return target
        except (OSError, ValueError, http.client.HTTPException) as exc:
            failures.append(f'{host}: {exc}')
            part.unlink(missing_ok=True)
            if attempt + 1 == attempt_count:
                if len(urls) == 1:
                    raise
                raise RuntimeError('所有下载源均失败：\n' + '\n'.join(failures)) from exc
            print(f"  Download failed; switching to the next source: {exc}", flush=True)
            if on_progress:
                on_progress("retry", attempt=attempt + 2, attempts=attempt_count, host=host, error=str(exc))
            time.sleep(2)


def pinned_wheels(lock, cache, env):
    """Resolve direct wheel URLs locally while retaining the lock's hashes."""
    source = lock.read_text(encoding='utf-8')
    direct = re.compile(r'(?m)(^[\w-]+ @ )(https://[^\s]+)( \\\n[ \t]+--hash=sha256:([a-f0-9]{64}))')

    def local_wheel(match):
        url, expected = match[2], match[4]
        name = unquote(urlsplit(url).path.rsplit('/', 1)[-1])
        if not re.fullmatch(r'[A-Za-z0-9_+.-]+\.whl', name):
            raise ValueError('固定 wheel 的文件名无效。')
        source_file = download({'url': url, 'sha256': expected}, cache, env=env, timeout=45)
        named = cache / expected / name
        named.parent.mkdir(exist_ok=True)
        if not named.is_file() or digest(named) != expected:
            named.unlink(missing_ok=True)
            try:
                os.link(source_file, named)
            except OSError:
                shutil.copyfile(source_file, named)
        return match[1] + named.resolve().as_uri() + match[3]

    resolved = cache / ('verified-' + lock.name)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(direct.sub(local_wheel, source), encoding='utf-8')
    return resolved


def unpack(archive, destination, expected_hash):
    marker = destination / ".manju-source.json"
    if destination.exists():
        if not marker.is_file():
            raise ValueError(f"Refusing to overwrite an unmanaged source directory: {destination}")
        saved = json.loads(marker.read_text(encoding="utf-8"))
        if saved.get("archive_sha256") != expected_hash:
            raise ValueError(f"Source version changed; choose a new runtime root: {destination}")
        for name, sha in saved["files"].items():
            if not (destination / name).is_file() or digest(destination / name) != sha:
                raise ValueError(f"Source was edited or is incomplete: {destination / name}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    # TemporaryDirectory is created inside the owned parent and only cleans its own path.
    with tempfile.TemporaryDirectory(prefix="extract-", dir=destination.parent) as staging:
        stage = Path(staging)
        hashes = {}
        with zipfile.ZipFile(archive) as package:
            members = package.infolist()
            if sum(member.file_size for member in members) > 2 * 1024**3:
                raise ValueError("Source archive is unexpectedly large")
            prefix = members[0].filename.split("/")[0]
            for member in members:
                path = PurePosixPath(member.filename)
                if path.is_absolute() or ".." in path.parts or ":" in member.filename or "\\" in member.filename or path.parts[0] != prefix or stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError("Unsafe archive member: " + member.filename)
                relative = PurePosixPath(*path.parts[1:])
                if member.is_dir() or str(relative) == ".":
                    continue
                output = stage / relative.as_posix()
                output.parent.mkdir(parents=True, exist_ok=True)
                with package.open(member) as source, output.open("wb") as stream:
                    shutil.copyfileobj(source, stream)
                hashes[relative.as_posix()] = digest(output)
        write_json(stage / ".manju-source.json", {"archive_sha256": expected_hash, "files": hashes})
        stage.rename(destination)
    return destination


def validate_models(root, components, emotion):
    catalog = json.loads((PROJECT / "release/models.json").read_text(encoding="utf-8"))
    expected = {}
    for line in (PROJECT / "release/model-checksums.sha256").read_text(encoding="utf-8").splitlines():
        sha, name = line.split("  ", 1)
        expected[name] = sha
    packs = set()
    if "speech" in components:
        packs.add("05-indextts")
        if emotion:
            packs.add("06-indextts-emotion")
    if "lipsync" in components:
        packs.add("07-latentsync")
    files = [f for f in catalog["files"] if packs.intersection(f["packs"])]
    missing = [f["path"] for f in files if not (root / f["path"]).is_file()]
    if missing:
        raise ValueError("Missing model files (merge the downloaded models folders first):\n" + "\n".join(missing))
    for index, item in enumerate(files, 1):
        name = item["path"]
        print(f"Checking model {index}/{len(files)}: {name}", flush=True)
        if digest(root / name) != expected[name]:
            raise ValueError("Model SHA256 mismatch: " + name)
    return {"verified_files": len(files), "packs": sorted(packs)}


def comfy_installation(path):
    path = Path(path).expanduser().resolve()
    if (path / "ComfyUI/main.py").is_file():
        path = path / "ComfyUI"
    if not all((path / name).exists() for name in ("main.py", "server.py", "folder_paths.py", "comfy")):
        raise ValueError("Select the ComfyUI directory containing main.py, not the ai-go-play project directory")
    candidates = [parent / embedded / "python.exe" for parent in (path.parent, path) for embedded in ("python_embeded", "python_embedded")]
    candidates += [parent / folder / "Scripts/python.exe" for parent in (path, path.parent) for folder in (".venv", "venv")]
    python = next((p for p in candidates if p.is_file()), None)
    if not python:
        raise ValueError("ComfyUI Python not found (supported: Windows portable or .venv/venv installation)")
    return path, python


def probe(config, root):
    kind = config["kind"]
    request = root / "reports" / (kind + "-probe-request.json")
    result = root / "reports" / (kind + "-probe.json")
    write_json(request, config)
    run([config["python"], "-I", "-X", "utf8", "-u", SUPPORT / "runtime_probe.py", request, result],
        log=root / "logs" / (kind + "-probe.log"), env=child_environment(root, config["ffmpeg"], offline=True),
        cwd=root / "tmp", timeout=300)
    return json.loads(result.read_text(encoding="utf-8"))


def install_bridge(config, destination, root):
    kind = config["kind"]
    name = "comfyui_manju_" + kind
    target = destination / name
    target.mkdir(parents=True, exist_ok=True)
    source = PROJECT / "integrations" / name
    # Preserve the old bridge before replacing any files; never edit ComfyUI dependencies.
    if any((target / f).exists() for f in ("__init__.py", "worker.py", "runtime_env.py", "runtime.json")):
        backup = root / "backups" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + kind + "-" + uuid.uuid4().hex[:8])
        backup.mkdir(parents=True)
        for filename in ("__init__.py", "worker.py", "runtime_env.py", "runtime.json"):
            if (target / filename).is_file():
                shutil.copy2(target / filename, backup / filename)
    for filename in ("__init__.py", "worker.py", "runtime_env.py"):
        temporary = target / (filename + ".pending")
        shutil.copy2(source / filename, temporary)
        temporary.replace(target / filename)
    # Publish the config last, after environment/model checks and bridge copying succeed.
    write_json(target / "runtime.json", config)
    return str(target)


def prepare_runtime_media(configured, root, spec, env):
    if configured:
        ffmpeg = Path(configured).resolve()
        paths = ffmpeg, ffmpeg.with_name('ffprobe.exe')
    else:
        saved = load_media_settings(PROJECT / '.manju/local-ai-paths.json')
        binaries = find_system_media(env, saved)
        if binaries:
            return Path(binaries['ffmpeg']), Path(binaries['ffprobe'])
        archive = download(spec, root / 'downloads', env=env)
        folder = unpack(archive, root / 'ffmpeg', spec['sha256']) / 'bin'
        paths = folder / 'ffmpeg.exe', folder / 'ffprobe.exe'
    for path, name in zip(paths, ('ffmpeg', 'ffprobe'), strict=True):
        run([path, '-version'], log=root / 'logs/ffmpeg.log', env=env, timeout=30)
        if not usable_media_binary(path, name, env):
            raise ValueError(f'{path} did not return valid {name} version information')
    return paths


def install(args):
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("This installer supports Windows x64 with an NVIDIA GPU")
    root = Path(args.runtime_root).expanduser().resolve()
    models = Path(args.models_root).expanduser().resolve()
    comfy, comfy_python = comfy_installation(args.comfy)
    components = ["speech", "lipsync"] if args.components == "all" else [args.components]
    emotion_path = models / "tts/IndexTTS-2.5/qwen0.6bemo4-merge"
    emotion = args.emotion == "required" or (args.emotion == "auto" and emotion_path.is_dir())
    model_report = validate_models(models, components, emotion)
    root.mkdir(parents=True, exist_ok=True)
    env = child_environment(root)
    manifest = json.loads((SUPPORT / "sources.json").read_text(encoding="utf-8"))
    uv = Path(args.uv).resolve()
    if not uv.is_file():
        raise ValueError("uv executable missing; use install-local-ai.cmd")
    state_path = root / "installation.json"
    if args.check_only:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for kind in components:
            if kind not in state["components"]:
                raise ValueError("Not installed: " + kind)
            config = state["components"][kind]
            if Path(config["model_dir"]).resolve() != (models / ("tts/IndexTTS-2.5" if kind == "speech" else "lipsync/LatentSync-1.5")).resolve():
                raise ValueError("Selected models differ from installed configuration; rerun installation")
            state.setdefault("checks", {})[kind] = probe(config, root)
        write_json(root / "reports/check.json", {"models": model_report, "checks": state["checks"]})
        return state
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("owner") != OWNER:
            raise ValueError("Unmanaged installation state")
    else:
        state = {"owner": OWNER, "components": {}, "checks": {}}
    ffmpeg, ffprobe = prepare_runtime_media(args.ffmpeg, root, manifest['ffmpeg'], env)
    failures = []
    for mirror in managed_python_sources(env):
        try:
            run([uv, 'python', 'install', manifest['python_version'], '--no-bin', '--no-registry'],
                log=root / 'logs/python.log', env={**env, 'UV_PYTHON_INSTALL_MIRROR': mirror, 'UV_HTTP_TIMEOUT': '30'})
            break
        except RuntimeError as error:
            failures.append(str(error))
    else:
        raise RuntimeError('\n'.join(failures))
    result = subprocess.run([str(uv), "python", "find", manifest["python_version"]], env=env, capture_output=True, text=True, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    python = Path(result.stdout.strip()).resolve()
    if not python.is_relative_to((root / "python").resolve()):
        raise ValueError("Managed Python resolved outside the installation directory")
    if 'speech' in components:
        available = subprocess.run([str(comfy_python), '-s', '-c', 'import soundfile'], env=env, cwd=comfy,
                                  capture_output=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if available.returncode:
            # The official portable build doesn't include SoundFile. Add only
            # this lightweight bridge dependency; Torch/CUDA stay untouched.
            install_packages([uv, 'pip', 'install', '--python', comfy_python, '--only-binary', ':all:', 'soundfile==0.13.1'],
                log=root / 'logs/comfy-dependencies.log', env=env, cwd=comfy, timeout=300)
    run([comfy_python, "-X", "utf8", "-u", "-c", "import torch, numpy, yaml; assert torch.cuda.is_available(), 'ComfyUI cannot access an NVIDIA CUDA GPU'; print('ComfyUI bridge dependencies OK')"],
        log=root / "logs/comfy-dependencies.log", env=env, cwd=comfy, timeout=120)
    pending = {}
    for kind in components:
        spec = manifest[kind]
        repo = unpack(download(spec, root / "downloads"), root / "sources" / kind, spec["sha256"])
        environment = root / "envs" / kind
        ownership = environment / ".manju-environment.json"
        if environment.exists() and not ownership.is_file():
            raise ValueError(f"Refusing to modify an unmanaged environment: {environment}")
        if ownership.is_file() and json.loads(ownership.read_text(encoding="utf-8")).get("owner") != OWNER:
            raise ValueError("Environment belongs to another installer")
        if not environment.exists():
            run([uv, "venv", "--python", python, environment], log=root / "logs" / (kind + "-install.log"), env=env)
            write_json(ownership, {"owner": OWNER})
        runtime_python = environment / "Scripts/python.exe"
        lock = pinned_wheels(SUPPORT / (kind + ".lock"), root / "downloads", env)
        install_packages([uv, "pip", "sync", "--python", runtime_python, "--require-hashes", "--build-constraints", SUPPORT / "build-constraints.txt", lock],
            log=root / "logs" / (kind + "-install.log"), env=env)
        run([uv, "pip", "check", "--python", runtime_python], log=root / "logs" / (kind + "-install.log"), env=env, timeout=60)
        config = {"kind": kind, "python": str(runtime_python), "repo": str(repo),
                  "model_dir": str(models / ("tts/IndexTTS-2.5" if kind == "speech" else "lipsync/LatentSync-1.5")),
                  "ffmpeg": str(ffmpeg), "cache_dir": str(root / "cache" / kind),
                  "source_sha256": spec["sha256"], "requirements_sha256": digest(lock)}
        if kind == "speech":
            config["emotion"] = emotion
        else:
            config["face_detector"] = str(models / "detection/face_detection_yunet_2023mar.onnx")
        state["checks"][kind] = probe(config, root)
        pending[kind] = config
        write_json(root / "reports" / (kind + "-prepared.json"), config)
    destination = root / "staged-bridges" if args.stage_only else comfy / "custom_nodes"
    for kind, config in pending.items():
        config["bridge"] = install_bridge(config, destination, root)
        state["components"][kind] = config
    state.update(comfy=str(comfy), models_root=str(models), runtime_root=str(root), staged=args.stage_only,
                 model_check=model_report, checked_at=datetime.now(timezone.utc).isoformat())
    write_json(state_path, state)
    if not args.stage_only:
        write_json(PROJECT / ".manju/local-ai-paths.json", {"ffmpeg": str(ffmpeg), "ffprobe": str(ffprobe), "installation": str(state_path)})
    print("Installation prepared. Restart ComfyUI when its queue is idle, then check speech/lip-sync in Workflows.", flush=True)
    print("Installation report:", state_path, flush=True)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy", required=True)
    parser.add_argument("--models-root", required=True)
    parser.add_argument("--runtime-root", default=str(PROJECT / ".manju/local-ai"))
    parser.add_argument("--uv", required=True)
    parser.add_argument("--components", choices=["all", "speech", "lipsync"], default="all")
    parser.add_argument("--emotion", choices=["auto", "required", "off"], default="auto")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--stage-only", action="store_true", help="Validate using ComfyUI but stage bridges without installing them")
    args = parser.parse_args()
    try:
        install(args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError) as error:
        print("Installation failed:", error, file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

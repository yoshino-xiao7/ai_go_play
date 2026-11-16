"""Model location, SHA256 verification and non-destructive import from downloaded packs."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import shutil
import uuid
from .store import DomainError


def local_path(value, *, directory=False):
    if not isinstance(value, str) or not value.strip() or value.startswith(('\\\\', '//')) or '\0' in value:
        raise DomainError(422, '请输入本机绝对目录路径。', 'setup_path_invalid')
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise DomainError(422, '请使用完整的本机目录路径。', 'setup_path_invalid')
    path = path.resolve()
    if directory and not path.is_dir():
        raise DomainError(404, '这个目录不存在，请重新选择。', 'setup_path_missing')
    return path


def model_target(root, relative):
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()):
        raise DomainError(422, '模型目录包含指向外部位置的链接，请选择专用目录。', 'setup_path_escape')
    return target


def source_candidates(root, item):
    relative = Path(item['path'])
    # Handles both merged models and the unmodified ai-go-play Quark folder.
    for base in (root, root / 'models', root / 'ai-go-play'):
        yield base / relative
        for pack in item['packs']:
            yield base / pack / 'models' / relative


def locate(item, roots):
    for root in roots:
        for path in source_candidates(Path(root), item):
            try:
                if path.is_file() and path.stat().st_size == item['size']:
                    return path.resolve()
            except OSError:
                continue
    return None


def inspect_files(files, root, sources):
    rows = []
    for item in files:
        target = model_target(root, item['path'])
        try:
            state = 'unverified' if target.is_file() and target.stat().st_size == item['size'] else 'mismatch' if target.exists() else 'missing'
        except OSError:
            state = 'unreadable'
        source = locate(item, sources) if state != 'unverified' else target
        rows.append({**item, 'status': state, 'source': str(source) if source else None})
    return rows


def hash_file(path, job, report=None):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8 * 1024**2):
            job.check_cancelled()
            digest.update(block)
            if report: report(len(block))
    return digest.hexdigest()


def verify_files(files, root, job):
    total = sum(f['size'] for f in files) or 1
    done = 0
    rows = []
    def progress(amount):
        nonlocal done
        done += amount
        job.update(progress=min(.99, done / total), completed_bytes=done, total_bytes=total)
    for item in files:
        job.check_cancelled()
        job.update(message='校验 ' + item['path'])
        path = model_target(root, item['path'])
        before = done
        stamp = None
        try:
            if not path.is_file():
                status = 'missing'
            elif path.stat().st_size != item['size']:
                status = 'mismatch'
            else:
                initial = path.stat()
                status = 'verified' if hash_file(path, job, progress) == item['sha256'] else 'mismatch'
                final = path.stat()
                if (initial.st_size, initial.st_mtime_ns, initial.st_ino) != (final.st_size, final.st_mtime_ns, final.st_ino):
                    status = 'mismatch'
                if status == 'verified': stamp = final.st_mtime_ns
        except OSError:
            status = 'unreadable'
        progress(max(0, item['size'] - (done - before)))
        rows.append({'path': item['path'], 'status': status, 'packs': item['packs'], 'size': item['size'], 'mtime_ns': stamp})
    return {'files': rows, 'verified': sum(r['status'] == 'verified' for r in rows), 'total': len(rows),
            'missing': [r for r in rows if r['status'] != 'verified']}


def import_files(files, root, sources, job):
    root.mkdir(parents=True, exist_ok=True)
    resolved = [(f, locate(f, sources)) for f in files]
    required = sum(f['size'] for f, p in resolved if p and not (root / f['path']).exists())
    if shutil.disk_usage(root).free < required + 256 * 1024**2:
        raise DomainError(409, '目标磁盘空间不足，请更换目录或减少模型选择。', 'setup_disk_full')
    imported, conflicts, unavailable = [], [], []
    total = sum(f['size'] for f in files) or 1
    done = 0
    for item, source in resolved:
        job.check_cancelled()
        target = model_target(root, item['path'])
        job.update(message='导入 ' + item['path'], progress=min(.99, done / total))
        if target.exists():
            if not target.is_file() or target.stat().st_size != item['size'] or hash_file(target, job) != item['sha256']:
                conflicts.append(item['path'])
            done += item['size']
            continue
        if not source:
            unavailable.append(item['path'])
            done += item['size']
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + '.' + uuid.uuid4().hex + '.partial')
        digest = hashlib.sha256()
        try:
            with source.open('rb') as incoming, partial.open('xb') as outgoing:
                while chunk := incoming.read(8 * 1024**2):
                    job.check_cancelled()
                    outgoing.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    job.update(progress=min(.99, done / total), completed_bytes=done, total_bytes=total)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if digest.hexdigest() != item['sha256']:
                conflicts.append(item['path'])
                continue
            # Windows rename and POSIX hard-link both refuse to replace an existing file.
            if os.name == 'nt': partial.rename(target)
            else:
                os.link(partial, target)
                partial.unlink()
            imported.append(item['path'])
        finally:
            partial.unlink(missing_ok=True)
    return {'imported': imported, 'conflicts': conflicts, 'unavailable': unavailable}

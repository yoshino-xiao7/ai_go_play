"""Read or materialize a collected upstream skill without changing its bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def filesystem_path(path):
    """Use Windows' extended path syntax when the sandbox temp root is long."""
    path = Path(os.path.normpath(os.path.abspath(path)))
    value = str(path)
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        value = "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
        return Path(value)
    return path


def readable_path(path, files):
    """Keep ordinary Windows paths when all collected files fit comfortably."""
    value = str(path)
    plain = ("\\\\" + value[8:]) if value.startswith("\\\\?\\UNC\\") else value[4:] if value.startswith("\\\\?\\") else value
    if len(plain) + 1 + max(map(len, files), default=0) < 240:
        return Path(plain)
    return path


def safe_name(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or "\\" in name or ":" in name or any(p in ("", ".", "..") for p in name.split("/")):
        raise ValueError(f"Unsafe archive path: {name!r}")
    return path


def verified_files(package):
    package = Path(package).resolve()
    manifest = json.loads((package / "sources/manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not re.fullmatch(r"[a-z0-9-]+", manifest["name"]):
        raise ValueError("Invalid collection manifest")
    archive = package / manifest["archive"]
    if not archive.resolve().is_relative_to(package):
        raise ValueError("Archive must be inside the installed skill")
    if digest(archive.read_bytes()) != manifest["archive_sha256"]:
        raise ValueError("Archive checksum mismatch")
    entries = {entry["path"]: entry for entry in manifest["files"]}
    if len(entries) != len(manifest["files"]) or sum(e["size"] for e in entries.values()) > 256 * 1024 * 1024:
        raise ValueError("Invalid or oversized collection")
    files = {}
    with zipfile.ZipFile(archive) as source:
        infos = source.infolist()
        if len(infos) != len(entries) or {i.filename for i in infos} != set(entries):
            raise ValueError("Archive members differ from the manifest")
        for info in infos:
            safe_name(info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Archive symlinks are not supported")
            entry = entries[info.filename]
            if info.file_size != entry["size"]:
                raise ValueError("Archive member size mismatch")
            data = source.read(info)
            if digest(data) != entry["sha256"]:
                raise ValueError(f"Source checksum mismatch: {info.filename}")
            files[info.filename] = data
    if not all(entry in files for entry in manifest["entrypoints"]):
        raise ValueError("Missing original skill entrypoint")
    return manifest, files


def materialize(package, cache_dir=None):
    manifest, files = verified_files(package)
    cache = filesystem_path(Path(cache_dir) if cache_dir is not None else Path(tempfile.gettempdir()) / "ai-go-play-collected")
    cache.mkdir(parents=True, exist_ok=True)
    cache = cache.resolve()
    target = cache / (manifest["name"] + "-" + manifest["archive_sha256"][:12])
    valid = target.is_dir() and not target.is_symlink()
    if valid:
        for name, data in files.items():
            path = target / name
            if path.is_symlink() or not path.resolve().is_relative_to(target.resolve()) or not path.is_file() or digest(path.read_bytes()) != digest(data):
                valid = False
                break
    if not valid:
        # A changed cache may contain somebody's work: create a sibling, never overwrite it.
        if target.exists() or target.is_symlink():
            target = Path(tempfile.mkdtemp(prefix=manifest["name"] + "-", dir=cache))
        else:
            target.mkdir()
        for name, data in files.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.resolve().is_relative_to(target.resolve()):
                raise ValueError("Extraction escaped its new directory")
            path.write_bytes(data)
    target = readable_path(target, files)
    return {"root": str(target), "entrypoints": [str(target / name) for name in manifest["entrypoints"]],
            "repository": manifest["repository"], "commit": manifest["commit"],
            "upstream_url": manifest["upstream_url"], "scope": manifest.get("scope"), "verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("verify", "read", "materialize"))
    parser.add_argument("path", nargs="?")
    parser.add_argument("--cache-dir", type=Path, help="Optional writable cache root for materialize")
    args = parser.parse_args()
    package = Path(__file__).resolve().parents[1]
    if args.operation == "materialize":
        print(json.dumps(materialize(package, args.cache_dir), ensure_ascii=True, indent=2))
        return
    manifest, files = verified_files(package)
    if args.operation == "read":
        if args.path not in files:
            parser.error("Choose a file path listed in sources/manifest.json")
        sys.stdout.buffer.write(files[args.path])
    else:
        print(json.dumps({"name": manifest["name"], "files": len(files), "verified": True}))


if __name__ == "__main__":
    main()

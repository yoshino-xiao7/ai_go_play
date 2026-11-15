"""Read-only model inventory and Quark comparison; never uploads or moves weights.

Remote JSON: {"files": [{"path": "diffusion_models/example.safetensors",
"size": 123, "sha256": "optional 64 hex digits"}]}.
Paths are relative to the shared model root, without pack/category prefixes.
An absent remote inventory means unknown, never missing.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


CATALOG = Path(__file__).resolve().parents[1] / "release" / "models.json"


def relative_path(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Model path must be a nonempty relative path")
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or ":" in value or str(path) == ".":
        raise ValueError(f"Invalid model path: {value}")
    return path.as_posix()


def read_remote(path):
    if path is None:
        return None
    result = {}
    for item in json.loads(Path(path).read_text(encoding="utf-8-sig"))["files"]:
        name = relative_path(item["path"])
        if name in result:
            raise ValueError(f"Duplicate remote path: {name}")
        if type(item.get("size")) is not int or item["size"] < 0:
            raise ValueError(f"Invalid remote size: {name}")
        if item.get("sha256") and not re.fullmatch(r"[0-9a-fA-F]{64}", item["sha256"]):
            raise ValueError(f"Invalid remote SHA256: {name}")
        result[name] = item
    return result


def audit(root, catalog, remote=None, hash_files=False):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Model root must be a directory")
    records = []
    seen = set()
    for entry in catalog["files"]:
        name = relative_path(entry["path"])
        if name in seen:
            raise ValueError(f"Duplicate catalog path: {name}")
        seen.add(name)
        source = root / name
        present = source.is_file()
        record = {**entry, "path": name, "local_status": "present" if present else "missing",
                  "size": source.stat().st_size if present else None, "sha256": None}
        if present and hash_files:
            with source.open("rb") as stream:
                record["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        if remote is None:
            state = "unknown"
        elif name not in remote:
            state = "missing"
        elif not present:
            state = "local_missing_cannot_verify"
        elif remote[name]["size"] != record["size"]:
            state = "size_mismatch"
        elif record["sha256"] and remote[name].get("sha256"):
            state = "verified_sha256" if record["sha256"] == remote[name]["sha256"].lower() else "hash_mismatch"
        else:
            state = "same_size_unverified"
        record["remote_status"] = state
        records.append(record)
    packs = []
    for pack in catalog["packs"]:
        members = [r for r in records if pack["id"] in r["packs"]]
        packs.append({**pack, "file_count": len(members),
                      "local_bytes": sum(r["size"] or 0 for r in members),
                      "local_missing": [r["path"] for r in members if r["local_status"] == "missing"]})
    return {"schema_version": 1, "remote_inventory_provided": remote is not None,
            "hashes_computed": hash_files, "files": records, "packs": packs,
            "summary": {"file_count": len(records), "local_bytes": sum(r["size"] or 0 for r in records),
                        "local_status": dict(Counter(r["local_status"] for r in records)),
                        "remote_status": dict(Counter(r["remote_status"] for r in records))}}


def upload_plan(report, root):
    # Each shared file appears once. packs records every feature that uses it.
    return {"remote_inventory_provided": report["remote_inventory_provided"], "files": [
        {"source": str(Path(root).resolve() / r["path"]),
         "destination": r["packs"][0] + "/models/" + r["path"],
         "model_path": r["path"], "packs": r["packs"], "size": r["size"],
         "reason": r["remote_status"]}
        for r in report["files"] if r["local_status"] == "present"
        and r["remote_status"] in {"missing", "size_mismatch", "hash_mismatch"}
    ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-root", required=True)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--remote-inventory", type=Path)
    parser.add_argument("--sha256", action="store_true", help="Read every model in full; may take a long time")
    parser.add_argument("--output", type=Path, required=True, help="Report directory, preferably under .qa")
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    report = audit(args.models_root, catalog, read_remote(args.remote_inventory), args.sha256)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in (("model-audit.json", report), ("upload-plan.json", upload_plan(report, args.models_root))):
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=True, indent=2))
    return 1 if report["summary"]["local_status"].get("missing") else 0


if __name__ == "__main__":
    raise SystemExit(main())

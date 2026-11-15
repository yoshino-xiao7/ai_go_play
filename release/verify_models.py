"""Verify downloaded model packs against the publisher's local SHA256 manifest."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


def verify(root, manifest, catalog, pack=None):
    root = Path(root)
    if pack and pack not in {p["id"] for p in catalog["packs"]}:
        raise ValueError(f"Unknown model pack: {pack}")
    expected = {}
    for line in Path(manifest).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        p = PurePosixPath(name)
        if not re.fullmatch(r"[a-fA-F0-9]{64}", digest) or p.is_absolute() or ".." in p.parts or ":" in name or "\\" in name or name in expected:
            raise ValueError("Invalid or duplicate checksum entry")
        expected[name] = digest.lower()
    results = []
    for item in catalog["files"]:
        if pack and pack not in item["packs"]:
            continue
        name = item["path"]
        if name not in expected:
            raise ValueError(f"Missing checksum: {name}")
        file = root / name
        if not file.is_file():
            state = "MISSING"
        else:
            with file.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            state = "OK" if actual == expected[name] else "MISMATCH"
        results.append({"path": name, "status": state})
        print(state, name, flush=True)
    return results


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-root", required=True, type=Path)
    parser.add_argument("--pack", help="Optional pack id, such as 01-qwen-image")
    parser.add_argument("--manifest", type=Path, default=here / "model-checksums.sha256")
    parser.add_argument("--catalog", type=Path, default=here / "models.json")
    args = parser.parse_args()
    try:
        results = verify(args.models_root, args.manifest, json.loads(args.catalog.read_text(encoding="utf-8")), args.pack)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"Verification error: {error}\n")
    good = sum(r["status"] == "OK" for r in results)
    print(f"Verified {good}/{len(results)} files.")
    return 0 if good == len(results) and results else 1


if __name__ == "__main__":
    raise SystemExit(main())

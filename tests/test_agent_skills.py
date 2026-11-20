"""Check skill distributions as a fresh user, without site packages or media jobs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILLS = ROOT / ".agents/skills"
SOURCE_NAMES = (
    "ai-go-play-h3-official",
    "ai-go-play-h3-enhancer",
    "ai-go-play-maimai",
)


def windows_path(path):
    """Keep test-owned deep paths usable on Windows with MAX_PATH enabled."""
    value = str(Path(path).absolute())
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        value = "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
    return Path(value)


@pytest.fixture(scope="module")
def distribution(tmp_path_factory):
    # Copy archives once; all negative cases alter only small files or rename a
    # single archive, then restore them. No installed user skill is involved.
    base = tmp_path_factory.mktemp("agent-skills")
    target = base / "新用户 工作目录" / "创作资料" / "独立解压 项目"
    packages = target / ".agents/skills"
    packages.parent.mkdir(parents=True)
    shutil.copytree(SOURCE_SKILLS, packages, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (target / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/check_agent_skills.py", target / "scripts/check_agent_skills.py")
    checker = runpy.run_path(str(target / "scripts/check_agent_skills.py"), run_name="_test_skill_checker")
    return target, checker


def package_at(distribution, name):
    return distribution[0] / ".agents/skills" / name


def loader_at(package):
    return runpy.run_path(str(package / "scripts/source.py"), run_name="_test_source_reader")


def test_fresh_distribution_checks_with_stdlib_only_and_network_forbidden(distribution, tmp_path):
    root, _ = distribution
    # Long TEMP roots reproduce the Windows app sandbox, where extraction of
    # otherwise ordinary source paths previously exceeded MAX_PATH.
    temp_root = tmp_path / "沙盒 临时目录"
    while len(str(temp_root)) < 185:
        temp_root /= "deep temporary segment"
    windows_path(temp_root).mkdir(parents=True)
    environment = os.environ.copy()
    environment.update(TEMP=str(temp_root), TMP=str(temp_root), TMPDIR=str(temp_root),
                       PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                       PYTHONPATH=str(tmp_path / "no-third-party-modules"))
    # -I ignores local/user Python paths; -S disables site packages. An audit
    # hook also makes any attempted socket activity a hard failure.
    launcher = (
        "import runpy,sys; "
        "sys.addaudithook(lambda event,args: "
        "(_ for _ in ()).throw(RuntimeError('network forbidden during skill check')) "
        "if event.startswith('socket.') else None); "
        "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", launcher,
         str(root / "scripts/check_agent_skills.py"), "--root", str(root)],
        cwd=tmp_path, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["offline_source_check"] == "passed"
    assert {skill["name"] for skill in report["skills"]} == {
        "ai-go-play-canvas", *SOURCE_NAMES,
    }
    sources = {skill["name"]: skill for skill in report["skills"] if "source_files" in skill}
    assert len(sources) == 3
    assert all(skill["source_files"] > 0 for skill in sources.values())
    assert sources["ai-go-play-maimai"]["local_links_checked"] > 0
    assert len(sources["ai-go-play-maimai"]["source_entrypoints"]) == 2


def test_missing_source_archive_is_rejected(distribution):
    archive = package_at(distribution, "ai-go-play-h3-official") / "sources/upstream.zip"
    hidden = archive.with_suffix(".unavailable")
    archive.rename(hidden)
    try:
        with pytest.raises(ValueError, match="missing required file sources/upstream.zip"):
            distribution[1]["check"](distribution[0])
    finally:
        hidden.rename(archive)


def test_corrupt_source_archive_is_rejected_before_materialization(distribution):
    archive = package_at(distribution, "ai-go-play-h3-official") / "sources/upstream.zip"
    original = archive.read_bytes()
    try:
        archive.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with pytest.raises(ValueError, match="Archive checksum mismatch"):
            distribution[1]["check"](distribution[0])
    finally:
        archive.write_bytes(original)


def test_unexpected_fifth_entrypoint_is_rejected(distribution):
    extra = distribution[0] / ".agents/skills/old-merged-skill"
    extra.mkdir()
    entry = extra / "SKILL.md"
    entry.write_text("---\nname: old-merged-skill\n---\n", encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="Expected exactly four project skill entrypoints"):
            distribution[1]["check"](distribution[0])
    finally:
        entry.unlink()
        extra.rmdir()


def test_declared_skill_name_must_match_its_directory(distribution):
    entry = package_at(distribution, "ai-go-play-canvas") / "SKILL.md"
    original = entry.read_bytes()
    try:
        entry.write_bytes(original.replace(b"name: ai-go-play-canvas", b"name: different-canvas", 1))
        with pytest.raises(ValueError, match="frontmatter name must match its directory"):
            distribution[1]["check"](distribution[0])
    finally:
        entry.write_bytes(original)


@pytest.mark.parametrize("field,value", [
    ("name", "wrong-collection-name"),
    ("entrypoints", ["skills/h3-prompt-writing/README.md"]),
])
def test_source_identity_must_match_the_expected_original(distribution, field, value):
    manifest = package_at(distribution, "ai-go-play-h3-official") / "sources/manifest.json"
    original = manifest.read_bytes()
    changed = json.loads(original)
    changed[field] = value
    try:
        manifest.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(ValueError, match="expected original entrypoints|Missing original skill entrypoint"):
            distribution[1]["check"](distribution[0])
    finally:
        manifest.write_bytes(original)


def test_release_tracked_guard_rejects_an_uncommitted_archive(distribution):
    root, checker = distribution
    tracked = {
        path.relative_to(root).as_posix() for path in (root / ".agents/skills").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    omitted = ".agents/skills/ai-go-play-h3-official/sources/upstream.zip"
    assert omitted in tracked
    tracked.remove(omitted)
    with pytest.raises(ValueError, match="Skill files are not committed: .*sources/upstream.zip"):
        checker["check"](root, tracked=tracked)


@pytest.mark.parametrize("name", SOURCE_NAMES)
def test_original_loaders_return_readable_short_paths_and_relative_links(distribution, tmp_path, name):
    package = package_at(distribution, name)
    loader = loader_at(package)
    manifest, files = loader["verified_files"](package)
    result = loader["materialize"](package, tmp_path / "cache")
    root = Path(result["root"])
    assert result["verified"] is True
    for relative, absolute in zip(manifest["entrypoints"], result["entrypoints"], strict=True):
        assert Path(absolute).read_bytes() == files[relative]
    # The short-path branch must not return an extended Windows path: ordinary
    # readers need ../ links to the sibling original skill to work as written.
    if os.name == "nt" and len(str(root).removeprefix("\\\\?\\")) + 1 + max(map(len, files)) < 240:
        assert not str(root).startswith("\\\\?\\")
    if name == "ai-go-play-maimai":
        sibling = Path(result["entrypoints"][0]).parent / ".." / "mmt-cel-first-frame/SKILL.md"
        if not str(root).startswith("\\\\?\\"):
            assert sibling.read_bytes() == files["skills/mmt-cel-first-frame/SKILL.md"]
        assert sibling.resolve().read_bytes() == files["skills/mmt-cel-first-frame/SKILL.md"]
    assert loader["materialize"](package, tmp_path / "cache")["root"] == result["root"]


@pytest.mark.parametrize("name", SOURCE_NAMES)
def test_original_loaders_handle_long_default_temp_roots(distribution, tmp_path, monkeypatch, name):
    package = package_at(distribution, name)
    loader = loader_at(package)
    long_temp = tmp_path / "临时创作 空间"
    while len(str(long_temp)) <= 270:
        long_temp /= "long temporary directory"
    windows_path(long_temp).mkdir(parents=True)
    monkeypatch.setattr(tempfile, "tempdir", str(long_temp))
    # Use the actual default-cache path, rather than a QA-only extraction helper.
    result = loader["materialize"](package)
    assert result["verified"] is True
    assert len(result["root"]) > 260
    manifest, files = loader["verified_files"](package)
    for relative, absolute in zip(manifest["entrypoints"], result["entrypoints"], strict=True):
        assert Path(absolute).read_bytes() == files[relative]
    assert loader["materialize"](package)["root"] == result["root"]


@pytest.mark.parametrize("name", SOURCE_NAMES)
def test_real_cli_handles_parent_cache_and_western_stdout(distribution, tmp_path, name):
    child = tmp_path / "child"
    child.mkdir()
    environment = os.environ.copy()
    # Match a western Windows user whose Agent captures stdout through a pipe.
    # JSON must retain Unicode paths without depending on the active code page.
    environment["PYTHONIOENCODING"] = "cp1252"
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(package_at(distribution, name) / "scripts/source.py"),
         "materialize", "--cache-dir", str(Path("..") / "中文 缓存")],
        cwd=child, env=environment, capture_output=True, text=True, encoding="cp1252", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["verified"] is True
    assert os.path.samefile(Path(parsed["root"]).parent, tmp_path / "中文 缓存")
    assert all(Path(entry).read_text(encoding="utf-8-sig").strip() for entry in parsed["entrypoints"])

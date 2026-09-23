"""Source archive safety and integrity checks using a disposable Git repository."""

import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from scripts.release import ARCHIVE_ROOT, build, verify


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def write(repo: Path, name: str, content: bytes) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def source_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Release Test")
    write(repo, "README.md", b"public readme\n")
    write(repo, "server/app.py", b"print('public')\n")
    write(repo, "web/src/main.tsx", b"export const ready = true;\n")
    write(repo, "docs/说明.md", "可公开\n".encode())
    write(repo, "SDKs/camera.dll", b"private sdk")
    write(repo, "models/yamnet/saved_model.pb", b"private weights")
    write(repo, "recordings/clip.wav", b"private voice")
    write(repo, "runtime/calibration.json", b"private calibration")
    write(repo, "config.local.json", b"private paths")
    write(repo, "reports/local-test-shot.png", b"private screenshot")
    write(repo, "web/tsconfig.tsbuildinfo", b"private build output")
    write(repo, "web/src/api-key.json", b"private key")
    write(repo, "docs/personal-notes.md", b"private notes")
    write(repo, "design/halo360-hud-concept-v6.png", b"design image")
    write(repo, "Team55提案.docx", b"private document")
    git(repo, "add", "-f", ".")
    git(repo, "commit", "-qm", "fixture")
    write(repo, "server/app.py", b"uncommitted private change")
    write(repo, "server/untracked.py", b"untracked secret")
    return repo


def test_archive_uses_only_allowlisted_committed_blobs(tmp_path: Path) -> None:
    repo = source_repo(tmp_path)
    output = tmp_path / "bundle.zip"
    manifest = build(repo, output)
    assert {item["path"] for item in manifest["files"]} == {
        "README.md",
        "server/app.py",
        "web/src/main.tsx",
        "docs/说明.md",
    }
    assert verify(output) == manifest
    with zipfile.ZipFile(output) as archive:
        assert archive.read(f"{ARCHIVE_ROOT}/server/app.py") == b"print('public')\n"
        assert archive.read(f"{ARCHIVE_ROOT}/docs/说明.md") == "可公开\n".encode()
    assert (
        output.with_suffix(".manifest.json").read_bytes()
        == (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    )
    for item in manifest["files"]:
        with zipfile.ZipFile(output) as archive:
            content = archive.read(f"{ARCHIVE_ROOT}/{item['path']}")
        assert hashlib.sha256(content).hexdigest() == item["sha256"]


def test_tampered_archive_fails_integrity_check(tmp_path: Path) -> None:
    repo = source_repo(tmp_path)
    output = tmp_path / "bundle.zip"
    build(repo, output)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(output) as source, zipfile.ZipFile(bad, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name.endswith("server/app.py"):
                content = b"changed\n"
            target.writestr(name, content)
    with pytest.raises(ValueError, match="Hash or size mismatch"):
        verify(bad)


def test_same_commit_produces_identical_archive(tmp_path: Path) -> None:
    repo = source_repo(tmp_path)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    build(repo, first)
    build(repo, second)
    assert first.read_bytes() == second.read_bytes()


def test_sidecar_mismatch_fails_integrity_check(tmp_path: Path) -> None:
    output = tmp_path / "bundle.zip"
    build(source_repo(tmp_path), output)
    output.with_suffix(".manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Sidecar manifest"):
        verify(output)


def test_output_must_be_zip(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must end in .zip"):
        build(source_repo(tmp_path), tmp_path / "README.md")

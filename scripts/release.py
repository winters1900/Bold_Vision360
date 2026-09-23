"""Build and verify a reviewable source-only archive from a Git commit.

Only the explicit source allowlist is packaged. Local files, ignored files,
uncommitted changes, binaries, model weights, SDKs, recordings and reports
cannot enter the archive through the working tree.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = "bold-vision360-source"
MANIFEST_NAME = "SOURCE-MANIFEST.json"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

ROOT_FILES = {
    ".gitignore",
    "README.md",
    "Start Bold Vision 360.cmd",
    "config.example.json",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
}
SOURCE_SUFFIXES = {
    "docs": {".md"},
    "native": {".cpp", ".h", ".hpp", ".cmake", ".txt"},
    "scripts": {".py", ".ps1"},
    "server": {".py"},
    "tests": {".py"},
    "web": {".css", ".html", ".json", ".ts", ".tsx"},
}
BLOCKED_PARTS = {
    ".env",
    ".git",
    ".tools",
    ".venv",
    "__pycache__",
    "build",
    "config.local.json",
    "dist",
    "models",
    "node_modules",
    "recordings",
    "runtime",
    "sdks",
    "secrets",
}
BLOCKED_SUFFIXES = {".local.json", ".png", ".jpg", ".jpeg", ".pdf", ".docx", ".zip"}
SENSITIVE_NAME_WORDS = {
    "credential",
    "credentials",
    "key",
    "keys",
    "password",
    "passwords",
    "personal",
    "private",
    "secret",
    "secrets",
    "token",
    "tokens",
}


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)
    return result.stdout


def allowed_source(path: str) -> bool:
    """Fail closed for unknown directories and artifact-like paths."""
    pure = PurePosixPath(path)
    parts = pure.parts
    if not parts or pure.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        return False
    lower = [part.lower() for part in parts]
    if any(part in BLOCKED_PARTS or part.startswith("local-") for part in lower):
        return False
    if any(SENSITIVE_NAME_WORDS.intersection(re.split(r"[._-]+", part)) for part in lower):
        return False
    if any(lower[-1].endswith(suffix) for suffix in BLOCKED_SUFFIXES):
        return False
    if len(parts) == 1:
        return path in ROOT_FILES
    return pure.suffix.lower() in SOURCE_SUFFIXES.get(parts[0], set())


def tracked_source_blobs(repo: Path, revision: str = "HEAD") -> tuple[str, list[tuple[str, str]]]:
    commit = _git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}").decode().strip()
    entries: list[tuple[str, str]] = []
    for item in _git(repo, "ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if kind == "blob" and mode in {"100644", "100755"} and allowed_source(path):
            entries.append((path, oid))
    return commit, sorted(entries)


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o100644 << 16
    return info


def build(repo: Path, output: Path, revision: str = "HEAD") -> dict:
    repo = repo.resolve()
    output = output.resolve()
    if output.suffix.lower() != ".zip":
        raise ValueError("Source archive output must end in .zip")
    commit, entries = tracked_source_blobs(repo, revision)
    if not entries:
        raise ValueError("No allowlisted source files found in the Git commit")
    files = []
    payloads = []
    for path, oid in entries:
        if (
            output == (repo / path).resolve()
            or output.with_suffix(".manifest.json") == (repo / path).resolve()
        ):
            raise ValueError(f"Output would overwrite tracked source: {path}")
        data = _git(repo, "cat-file", "blob", oid)
        files.append({"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        payloads.append((path, data))
    manifest = {"format_version": 1, "source_commit": commit, "files": files}
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", allowZip64=True) as archive:
        for path, data in payloads:
            archive.writestr(_zip_info(f"{ARCHIVE_ROOT}/{path}"), data)
        archive.writestr(_zip_info(f"{ARCHIVE_ROOT}/{MANIFEST_NAME}"), manifest_bytes)
    output.with_suffix(".manifest.json").write_bytes(manifest_bytes)
    verify(output)
    return manifest


def verify(archive_path: Path) -> dict:
    archive_path = archive_path.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Archive contains duplicate paths")
        manifest_path = f"{ARCHIVE_ROOT}/{MANIFEST_NAME}"
        manifest_bytes = archive.read(manifest_path)
        manifest = json.loads(manifest_bytes)
        if manifest.get("format_version") != 1 or not isinstance(manifest.get("files"), list):
            raise ValueError("Unsupported or invalid source manifest")
        expected = {manifest_path}
        for item in manifest["files"]:
            path = item["path"]
            if not allowed_source(path):
                raise ValueError(f"Manifest contains a disallowed path: {path}")
            name = f"{ARCHIVE_ROOT}/{path}"
            expected.add(name)
            data = archive.read(name)
            if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError(f"Hash or size mismatch: {path}")
        if set(names) != expected:
            raise ValueError("Archive file list does not match the manifest")
    sidecar = archive_path.with_suffix(".manifest.json")
    if sidecar.exists() and sidecar.read_bytes() != manifest_bytes:
        raise ValueError("Sidecar manifest does not match archive manifest")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--revision", default="HEAD", help="Git commit to package (default: HEAD)")
    parser.add_argument("--verify", type=Path, help="Verify an existing archive and its sidecar")
    args = parser.parse_args()
    if args.verify:
        manifest = verify(args.verify)
        print(f"Verified {len(manifest['files'])} files from {manifest['source_commit']}")
        return
    commit = _git(args.repo, "rev-parse", "--short=12", args.revision).decode().strip()
    output = args.output or args.repo / "dist" / f"bold-vision360-source-{commit}.zip"
    manifest = build(args.repo, output, args.revision)
    print(f"Created {output} with {len(manifest['files'])} files from {manifest['source_commit']}")


if __name__ == "__main__":
    main()

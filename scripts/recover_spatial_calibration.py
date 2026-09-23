"""Rebuild a validated spatial calibration from the five labelled recordings.

The default mode is read-only. ``--apply`` writes only while the local service is
stopped, and requires the operator to confirm the expected camera serial.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
from datetime import datetime

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.spatial_calibration_audit import audit, read_capture  # noqa: E402
from server.calibration import calibration_quality, load_samples, save_samples  # noqa: E402


DEFAULT_SESSIONS = (
    "20260923-104556-8702",  # front
    "20260923-114933-8c69",  # louder right retest
    "20260923-115447-afd2",  # rear retest
    "20260923-110400-32e9",  # left
    "20260923-111257-75f5",  # independent clockwise-90-degree rotation
)


def build_recovery(sessions):
    if len(sessions) != 5 or len(set(sessions)) != 5:
        raise ValueError("需要五份不同的前、右、后、左、转动录制")
    result = audit(sessions)
    if not result["passed"] or not calibration_quality(result["calibration"])["passed"]:
        raise ValueError(result.get("error") or result["quality"]["reason"])
    samples = {}
    for angle, session in zip((0, 90, 180, 270), sessions[:4]):
        pcm, binding = read_capture(session)
        if binding != result["binding"]:
            raise ValueError(f"录制 {session} 的相机或收音配置不一致")
        samples[angle] = pcm
    rotation, binding = read_capture(sessions[4])
    if binding != result["binding"]:
        raise ValueError("转动录制的相机或收音配置不一致")
    calibration = {
        **result["calibration"],
        "evidence_sessions": result["sessions"],
        "field_accuracy_measured": False,
    }
    return calibration, samples, rotation, result["binding"]


def service_listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def validate_install(calibration, binding, config_file, expected_serial):
    if not expected_serial or binding["serial"] != expected_serial:
        raise ValueError("--apply 需要 --expected-serial，且必须等于录制中的相机序列号")
    config = json.loads(config_file.read_text(encoding="utf-8"))
    for key in ("audio_profile", "camera_microphone"):
        if config.get(key) != binding[key]:
            raise ValueError(f"当前 {key} 与标定录制不一致；不能应用旧标定")
    if service_listening(int(config.get("port", 8765))):
        raise ValueError("本地服务仍在运行；先正常退出系统，再应用恢复结果并重新启动")
    if not calibration_quality(calibration)["passed"]:
        raise ValueError("方向精度门槛未通过")


def install_recovery(runtime_dir, calibration, samples, rotation, binding):
    """Stage and verify every file, then back up originals before replacement."""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    names = (
        "calibration-samples.npz",
        "calibration-rotation.npz",
        "calibration.json",
    )
    backup = runtime_dir / "calibration-history" / (
        "recovery-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )
    with tempfile.TemporaryDirectory(prefix="calibration-recovery-", dir=runtime_dir) as folder:
        stage = Path(folder)
        save_samples(stage / names[0], samples, binding)
        save_samples(stage / names[1], {"rotation": rotation}, binding)
        (stage / names[2]).write_text(
            json.dumps(calibration, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        loaded = load_samples(stage / names[0], binding)
        if loaded.keys() != samples.keys() or any(
            not np.array_equal(loaded[a], samples[a]) for a in samples
        ):
            raise ValueError("暂存的四向音频与原录制不一致")
        with np.load(stage / names[1], allow_pickle=False) as archive:
            if json.loads(str(archive["metadata"])) != binding or not np.array_equal(
                archive["rotation"], rotation
            ):
                raise ValueError("暂存的转动音频与原录制不一致")
        staged_json = json.loads((stage / names[2]).read_text(encoding="utf-8"))
        if not calibration_quality(staged_json)["passed"]:
            raise ValueError("暂存标定未通过精度门槛")

        backup.mkdir(parents=True)
        for name in names:
            original = runtime_dir / name
            if original.exists():
                shutil.copy2(original, backup / name)
        installed = []
        try:
            for name in names:
                os.replace(stage / name, runtime_dir / name)
                installed.append(name)
        except OSError:
            for name in installed:
                original = runtime_dir / name
                saved = backup / name
                if saved.exists():
                    shutil.copy2(saved, original)
                else:
                    original.unlink(missing_ok=True)
            raise
    return backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sessions", nargs="*", default=DEFAULT_SESSIONS)
    parser.add_argument("--apply", action="store_true", help="write validated files after service stops")
    parser.add_argument("--expected-serial", help="required with --apply")
    parser.add_argument("--runtime-dir", type=Path, default=ROOT / "runtime")
    parser.add_argument("--config-file", type=Path, default=ROOT / "config.local.json")
    args = parser.parse_args(argv)
    try:
        calibration, samples, rotation, binding = build_recovery(args.sessions)
        result = {
            "passed": True,
            "mode": "apply" if args.apply else "read_only",
            "binding": binding,
            "quality": calibration_quality(calibration),
            "sessions": calibration["evidence_sessions"],
            "rotation": calibration["rotation"],
            "field_accuracy_measured": False,
        }
        if args.apply:
            validate_install(calibration, binding, args.config_file, args.expected_serial)
            result["backup"] = str(
                install_recovery(args.runtime_dir, calibration, samples, rotation, binding)
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

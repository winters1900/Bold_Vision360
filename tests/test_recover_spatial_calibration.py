import json

import numpy as np
import pytest

from scripts import recover_spatial_calibration as recovery
from server.calibration import load_samples


def fixture_recovery():
    binding = dict(
        serial="test-camera",
        audio_profile="ambisonic",
        camera_microphone="builtin",
        sample_rate=16000,
        channels=4,
    )
    samples = {angle: np.zeros((16000, 4), dtype=np.float32) for angle in (0, 90, 180, 270)}
    rotation = np.zeros((16000, 4), dtype=np.float32)
    calibration = dict(
        **binding,
        method="shared_band_80_4000_v1",
        mapping=dict(w=0, x=3, y=1, sx=1, sy=-1),
        estimates=[dict(target=a, measured=a, confidence=0.5) for a in samples],
        rotation_verified=True,
        rotation=dict(target=270, measured=270, confidence=0.5, error_deg=0),
        evidence_sessions=dict(zip(("front", "right", "rear", "left", "rotation"), ("a", "b", "c", "d", "e"))),
    )
    return calibration, samples, rotation, binding


def test_recovery_dry_run_never_writes_runtime(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(recovery, "build_recovery", lambda sessions: fixture_recovery())
    runtime_dir = tmp_path / "runtime"
    assert recovery.main(["--runtime-dir", str(runtime_dir)]) == 0
    assert not runtime_dir.exists()
    assert json.loads(capsys.readouterr().out)["mode"] == "read_only"


def test_apply_rejects_wrong_serial_and_running_service(monkeypatch, tmp_path):
    calibration, _, _, binding = fixture_recovery()
    config = tmp_path / "config.json"
    config.write_text(json.dumps(dict(audio_profile="ambisonic", camera_microphone="builtin", port=8765)))
    with pytest.raises(ValueError, match="expected-serial"):
        recovery.validate_install(calibration, binding, config, "other-camera")
    monkeypatch.setattr(recovery, "service_listening", lambda port: True)
    with pytest.raises(ValueError, match="仍在运行"):
        recovery.validate_install(calibration, binding, config, "test-camera")


def test_install_preserves_old_files_and_restores_validated_samples(tmp_path):
    calibration, samples, rotation, binding = fixture_recovery()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "calibration.json").write_text("old calibration")
    backup = recovery.install_recovery(runtime_dir, calibration, samples, rotation, binding)
    assert (backup / "calibration.json").read_text() == "old calibration"
    assert set(load_samples(runtime_dir / "calibration-samples.npz", binding)) == set(samples)
    with np.load(runtime_dir / "calibration-rotation.npz", allow_pickle=False) as archive:
        assert np.array_equal(archive["rotation"], rotation)
    assert json.loads((runtime_dir / "calibration.json").read_text())["rotation_verified"]

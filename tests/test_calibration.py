import asyncio
import json
import time

import numpy as np
import pytest

from server.audio import AudioWindow, SPATIAL_METHOD, fit_axes, intensity
from server.calibration import calibration_quality, load_samples, save_samples
from server.domain import delta
from server.runtime import Runtime


def directional_pcm(angle, rate=48000, seconds=1.2):
    t = np.arange(round(rate * seconds)) / rate
    s = 0.1 * np.sin(2 * np.pi * 1000 * t)
    a = np.radians(angle)
    return np.column_stack([s, -s * np.sin(a), np.sin(2 * np.pi * 719 * t) * 0.001, s * np.cos(a)])


def test_common_band_rejects_rumble_without_changing_pcm_or_circular_bearing():
    mapping = dict(w=0, x=3, y=1, sx=1, sy=-1)
    pcm = directional_pcm(359)
    t = np.arange(len(pcm)) / 48000
    pcm += np.column_stack([0.5 * np.sin(2 * np.pi * f * t) for f in (10, 12, 18, 25)])
    original = pcm.copy()
    angle, confidence = intensity(pcm, mapping, 48000)
    assert abs(delta(angle, 359)) < 2 and confidence >= 0.2
    assert np.array_equal(pcm, original)
    # A new 300 ms live window uses the same estimator as calibration.
    angle, confidence = intensity(pcm[20000:34400], mapping, 48000)
    assert abs(delta(angle, 359)) < 2 and confidence >= 0.2


def test_duplicate_and_quiet_channels_cannot_pass_spatial_calibration():
    duplicate = np.repeat(directional_pcm(0)[:, :1], 4, axis=1)
    for pcm in (duplicate, directional_pcm(0) * 1e-5):
        with pytest.raises(ValueError):
            fit_axes({a: pcm for a in (0, 90, 180, 270)}, 48000)


def test_fit_records_version_and_individual_errors_without_claiming_rotation():
    result = fit_axes({a: directional_pcm(a) for a in (0, 90, 180, 270)}, 48000)
    assert result["mapping"] == dict(w=0, x=3, y=1, sx=1, sy=-1)
    assert result["method"] == SPATIAL_METHOD and result["sample_rate"] == 48000
    assert len(result["estimates"]) == 4 and result["max_error_deg"] < 0.01
    assert not result["rotation_verified"]


def test_saved_raw_captures_survive_restart_but_not_different_hardware_settings(tmp_path):
    path = tmp_path / "samples.npz"
    binding = dict(serial="camera-1", sample_rate=48000, channels=4, audio_profile="ambisonic")
    samples = {0: directional_pcm(0), 90: directional_pcm(90)}
    save_samples(path, samples, binding)
    restored = load_samples(path, binding)
    assert restored.keys() == samples.keys()
    assert all(np.array_equal(restored[a], samples[a]) for a in samples)
    for field, value in (
        ("serial", "camera-2"),
        ("sample_rate", 44100),
        ("audio_profile", "stereo"),
    ):
        assert load_samples(path, {**binding, field: value}) == {}


def calibrated_runtime():
    r = Runtime()
    r.mode = "live"
    r.audio_source = "camera"
    r.native = dict(serial="test-camera")
    r.channels, r.audio_rate = 4, 48000
    r.config.update(audio_profile="ambisonic", camera_microphone="builtin")
    r.calibration = dict(
        **r.spatial_binding,
        method=SPATIAL_METHOD,
        mapping=dict(w=0, x=3, y=1, sx=1, sy=-1),
        rotation_verified=True,
        rotation=dict(measured=270, confidence=0.8),
        estimates=[dict(target=a, measured=a, confidence=0.8) for a in (0, 90, 180, 270)],
    )
    return r


@pytest.mark.parametrize(
    "key,value",
    [
        ("method", "old_full_band"),
        ("sample_rate", 44100),
        ("serial", "other-camera"),
        ("audio_profile", "wind_reduction_strong"),
        ("camera_microphone", "external"),
        ("rotation_verified", False),
    ],
)
def test_direction_is_disabled_when_calibration_no_longer_matches(key, value):
    r = calibrated_runtime()
    assert r.calibrated_audio
    r.calibration[key] = value
    assert not r.calibrated_audio


def test_verified_w_channel_prevents_ambisonic_downmix_cancellation():
    window = AudioWindow()
    pcm = directional_pcm(180, rate=16000)
    window.append(pcm, 16000, "camera", 1)
    assert np.sqrt(np.mean(window.samples**2)) < 0.001
    window.append(pcm[:1600], 16000, "camera", 1.1, mono_channel=0)
    assert len(window.samples) == 1600  # changing the channel clears old downmix
    assert np.sqrt(np.mean(window.samples**2)) > 0.06


def test_failed_rotation_revokes_previous_verification_and_saves_diagnostic(monkeypatch, tmp_path):
    r = calibrated_runtime()
    monkeypatch.setattr("server.runtime.ROOT", tmp_path)

    async def capture(_):
        r.calibration_ring.append((time.perf_counter(), directional_pcm(0)))

    monkeypatch.setattr("server.runtime.asyncio.sleep", capture)
    with pytest.raises(ValueError, match="转动测试未通过"):
        asyncio.run(r.calibrate("rotation"))
    saved = json.loads((tmp_path / "runtime/calibration.json").read_text())
    assert not saved["rotation_verified"] and not r.calibrated_audio
    assert saved["rotation"]["error_deg"] > 80
    assert r.calibration_error and r.calibration_stage is None


def test_audio_discontinuity_cancels_capture_without_saving_partial_samples(monkeypatch, tmp_path):
    r = calibrated_runtime()
    monkeypatch.setattr("server.runtime.ROOT", tmp_path)

    async def capture(_):
        r.reset_audio_analysis()
        r.calibration_ring.append((time.perf_counter(), directional_pcm(0)))

    monkeypatch.setattr("server.runtime.asyncio.sleep", capture)
    with pytest.raises(ValueError, match="采集状态改变"):
        asyncio.run(r.calibrate(0))
    assert r.calibration_samples == {}
    assert not (tmp_path / "runtime/calibration-samples.npz").exists()


def test_runtime_restores_real_binding_and_samples_once_per_format(monkeypatch, tmp_path):
    r = calibrated_runtime()
    monkeypatch.setattr("server.runtime.ROOT", tmp_path)
    samples = {a: directional_pcm(a) for a in (0, 90, 180, 270)}
    save_samples(tmp_path / "runtime/calibration-samples.npz", samples, r.spatial_binding)
    r.save_calibration()
    r.calibration = None
    r.load_calibration()
    assert r.calibrated_audio and r.calibration_samples.keys() == samples.keys()
    # Native status packets are periodic: do not reload PCM and reset state each time.
    before = r.calibration_samples
    r.load_calibration()
    assert r.calibration_samples is before
    r.audio_rate = 44100
    r.load_calibration()
    assert not r.calibrated_audio and not r.calibration_samples


def test_offline_audit_holds_mapping_fixed_and_counts_failed_rotation(monkeypatch):
    from scripts import spatial_calibration_audit as audit

    binding = dict(
        serial="test",
        audio_profile="ambisonic",
        camera_microphone="builtin",
        sample_rate=48000,
        channels=4,
    )
    captures = {str(a): (directional_pcm(a), binding) for a in (0, 90, 180, 270)}
    monkeypatch.setattr(audit, "read_capture", lambda session: captures[session])
    result = audit.audit(["0", "90", "180", "270", "0"])
    assert not result["passed"] and not result["calibration"]["rotation_verified"]
    assert result["calibration"]["rotation"]["error_deg"] > 80
    assert result["calibration"]["mapping"] == dict(w=0, x=3, y=1, sx=1, sy=-1)
    assert not result["field_accuracy_measured"]


def test_mean_and_rotation_cannot_hide_a_bad_cardinal_or_claimed_summary():
    r = calibrated_runtime()
    r.calibration["estimates"][1]["measured"] = 123
    r.calibration.update(mean_error_deg=8.25, max_error_deg=0)
    quality = calibration_quality(r.calibration)
    assert not quality["passed"] and quality["failed_angles"] == [90]
    assert quality["max_error_deg"] == 33
    assert r.mapped_audio and not r.calibrated_audio
    assert r.snapshot()["classification_channel"] == 0


@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf")])
def test_missing_or_nonfinite_estimates_cannot_enable_direction(invalid):
    r = calibrated_runtime()
    r.calibration["estimates"][0]["measured"] = invalid
    assert not calibration_quality(r.calibration)["passed"]


def test_quality_gate_handles_wrap_and_boundary_without_trusting_verified_flag():
    r = calibrated_runtime()
    r.calibration["estimates"][0]["measured"] = 359
    r.calibration["estimates"][1]["measured"] = 112.5
    assert calibration_quality(r.calibration)["passed"]
    r.calibration["rotation"]["measured"] = 0
    assert not calibration_quality(r.calibration)["passed"]

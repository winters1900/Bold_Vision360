import av
import numpy as np
import pytest
from server.audio import AudioSignal, localization_status, pcm_from_frame


def feed(pcm, rate=48000):
    signal = AudioSignal()
    for start in range(0, len(pcm), 1024):
        signal.append(pcm[start : start + 1024], rate, "camera", start / rate)
    return signal, signal.snapshot(len(pcm) / rate)


def test_duplicate_stereo_is_detected_and_never_enables_localization():
    rng = np.random.default_rng(12)
    mono = rng.normal(0, 0.05, 48000)
    _, status = feed(np.column_stack([mono, mono]))
    assert status["structure"] == "dual_mono"
    assert status["correlation"] == pytest.approx(1)
    assert status["difference_ratio"] == pytest.approx(0)
    result = localization_status(status, "camera", 2, calibrated=True)
    assert not result["acoustic_available"] and result["mode"] == "visual_candidate_only"


def test_silence_and_short_audio_do_not_prove_mono_or_spatial_audio():
    _, status = feed(np.zeros((48000, 2)))
    assert status["structure"] == "quiet"
    assert status["correlation"] is None
    _, status = feed(np.full((4096, 2), 0.05))
    assert status["structure"] == "analyzing"


def test_different_channels_are_not_automatically_spatially_calibrated():
    rng = np.random.default_rng(4)
    _, status = feed(rng.normal(0, 0.05, (48000, 2)))
    assert status["structure"] == "stereo_unverified"
    assert abs(status["correlation"]) < 0.05
    assert not localization_status(status, "camera", 2)["acoustic_available"]


def test_envelope_tracks_real_power_without_cancelling_antiphase():
    pcm = np.repeat(np.array([0.01, 0.1, 0], np.float32), 960)
    _, status = feed(np.column_stack([pcm, -pcm]))
    assert status["envelope"] == pytest.approx([0.01, 0.1, 0])


def test_envelope_is_time_based_across_chunk_boundaries_and_bounded():
    signal, status = feed(np.full((96000, 2), 0.05))
    assert len(status["envelope"]) == 64
    assert status["envelope"] == pytest.approx([0.05] * 64)
    assert status["observed_ms"] < 1100
    assert signal.snapshot(4)["envelope"] == []
    signal.append(np.full((320, 1), 0.01), 16000, "microphone", 4)
    assert signal.snapshot(4)["envelope"] == pytest.approx([0.01])
    signal.append(np.full((320, 1), 0.02), 16000, "microphone", 5)
    assert signal.snapshot(5)["envelope"] == pytest.approx([0.02])


def test_four_channels_require_camera_and_calibration():
    _, status = feed(np.random.default_rng(4).normal(0, 0.05, (48000, 4)))
    assert not localization_status(status, "camera", 4)["acoustic_available"]
    assert not localization_status(status, "microphone", 4, True)["acoustic_available"]
    assert localization_status(status, "camera", 4, True)["acoustic_available"]


@pytest.mark.parametrize(
    "format,values",
    [
        ("fltp", np.array([[0.1, 0.2], [0.3, 0.4]], np.float32)),
        ("s16", np.array([[1000, 2000, 3000, 4000]], np.int16)),
        ("u8", np.array([[128, 192, 0, 255]], np.uint8)),
    ],
)
def test_decoder_preserves_planar_and_interleaved_channels(format, values):
    frame = av.AudioFrame.from_ndarray(values, format=format, layout="stereo")
    output = pcm_from_frame(frame)
    expected = values.T if format == "fltp" else values.reshape(-1, 2)
    if format == "s16":
        expected = expected / 32768
    if format == "u8":
        expected = (expected.astype(float) - 128) / 128
    assert np.allclose(output, expected)
    assert output.dtype == np.float32
    assert not np.array_equal(output[:, 0], output[:, 1])


def test_actual_aac_decode_keeps_independent_stereo():
    encoder = av.CodecContext.create("aac", "w")
    encoder.sample_rate = 48000
    encoder.layout = "stereo"
    encoder.format = "fltp"
    encoder.bit_rate = 128000
    encoder.open()
    t = np.arange(48000) / 48000
    pcm = np.vstack([0.1 * np.sin(2 * np.pi * 440 * t), 0.1 * np.sin(2 * np.pi * 880 * t)]).astype(
        np.float32
    )
    frame = av.AudioFrame.from_ndarray(pcm, format="fltp", layout="stereo")
    frame.sample_rate = 48000
    packets = encoder.encode(frame) + encoder.encode(None)
    decoder = av.CodecContext.create("aac", "r")
    decoder.extradata = encoder.extradata
    decoded = [pcm_from_frame(f) for packet in packets for f in decoder.decode(packet)]
    _, status = feed(np.concatenate(decoded))
    assert status["structure"] == "stereo_unverified"
    assert abs(status["correlation"]) < 0.05

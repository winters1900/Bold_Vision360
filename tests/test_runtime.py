import asyncio
import pytest
import time
from server.runtime import Runtime


def test_stopped_or_stale_stream_does_not_report_live_fps():
    r = Runtime()
    now = time.perf_counter()
    r.frame_times.extend([now - 0.1, now])
    r.frame_time = now
    assert r.snapshot()["fps"] == 0
    r.mode = "live"
    assert r.snapshot()["fps"] > 0
    r.frame_time = now - 3
    assert r.snapshot()["fps"] == 0


def test_backpressure_clears_audio_window_and_signals_gap():
    r = Runtime()
    r.raw_queue = asyncio.Queue(maxsize=1)
    r.raw_queue.put_nowait(({}, b"old", 1))
    header = {}
    r.enqueue(r.raw_queue, (header, b"new", 1))
    assert r.drops == 1 and r.raw_queue.qsize() == 1 and header["discontinuity"]


def test_no_simulated_source_fallback():
    r = Runtime()
    assert r.mode == "idle"
    assert "simulation" not in r.config


def test_invalid_source_rejected_without_mutation():
    r = Runtime()
    with pytest.raises(ValueError):
        asyncio.run(r.start("invalid"))
    assert r.mode == "idle"


def test_calibration_rejects_stereo():
    r = Runtime()
    r.mode = "live"
    r.audio_source = "camera"
    r.channels = 2
    with pytest.raises(ValueError):
        asyncio.run(r.calibrate(0))


def test_replay_uses_recorded_forward_calibration():
    r = Runtime()
    r.config["forward_offset_deg"] = 45
    r.replay_forward = 90
    assert r.forward_offset == 45
    r.mode = "replay"
    assert r.forward_offset == 90


def test_missing_models_report_error_without_crashing_service(monkeypatch):
    def unavailable(*args):
        raise FileNotFoundError("test missing model")

    monkeypatch.setattr("server.runtime.Classifier", unavailable)
    monkeypatch.setattr("server.runtime.Detector", unavailable)
    r = Runtime()
    asyncio.run(r.load_models())
    assert r.classifier is None and r.detector is None
    assert all("test missing model" in v for v in r.model_status.values())

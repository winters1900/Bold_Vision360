import asyncio
import numpy as np
import pytest
import time
from server.domain import DEFAULT_THRESHOLDS
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


def test_existing_local_config_receives_new_model_thresholds():
    r = Runtime()
    assert r.config["thresholds"].keys() >= DEFAULT_THRESHOLDS.keys()
    assert all(
        r.config["thresholds"][key] == value
        for key, value in DEFAULT_THRESHOLDS.items()
        if key not in ("horn", "siren", "bell", "shout", "speech")
    )


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


def test_audio_discontinuity_clears_display_and_pending_alert_debounce():
    r = Runtime()
    now = time.perf_counter()
    r.signal.append(np.full((1024, 2), 0.05), 48000, "camera", now)
    r.last_observation["horn"] = now
    assert r.snapshot()["audio_signal"]["present"]
    r.reset_audio_analysis()
    assert not r.last_observation
    assert not r.snapshot()["audio_signal"]["present"]
    assert not r.snapshot()["localization"]["acoustic_available"]


def test_simultaneous_categories_still_alert_without_assigning_shared_bearing(monkeypatch):
    class Model:
        def infer(self, samples):
            return {"horn": 0.9, "speech": 0.8}

    monkeypatch.setattr(Runtime, "calibrated_audio", property(lambda self: True))
    monkeypatch.setattr("server.runtime.intensity", lambda pcm, mapping, rate: (90, 0.6))

    async def run():
        r = Runtime()
        r.mode = "replay"
        r.classifier = Model()
        r.calibration = {"mapping": {"w": 0, "x": 1, "y": 2, "sx": 1, "sy": 1}}
        worker = asyncio.create_task(r.audio_worker())
        try:
            first = time.perf_counter()
            pcm = np.ones((16000, 4), dtype=np.float32) * 0.01
            r.audio_queue.put_nowait((pcm, 16000, "camera", first, r.generation, None))
            await asyncio.sleep(0.12)
            r.audio_queue.put_nowait((pcm, 16000, "camera", first + 0.12, r.generation, None))
            event = None
            for _ in range(100):
                event = r.fusion.events.get("horn")
                if event:
                    break
                await asyncio.sleep(0.01)
            assert event is not None
            assert event.priority == 0 and event.angle is None
            assert event.direction_reason == "ambiguous_audio_categories"
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    asyncio.run(run())

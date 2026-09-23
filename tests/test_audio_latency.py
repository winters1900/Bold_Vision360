import asyncio
import numpy as np

from scripts.audio_latency_check import run_probe, summarize
from server.recording import Recorder


def test_latency_summary_keeps_missing_socket_updates_out_of_socket_percentiles():
    events = [
        dict(id="a", generated_at=10.2, updated_at=10.0, classification_call_ms=8),
        dict(id="a", generated_at=10.4, updated_at=10.3, classification_call_ms=9),
    ]
    result = summarize(
        events,
        {("a", 10.2): 10.25},
        [4, 6],
        [2, 3],
        session="example",
        seconds=1.0,
        audio_blocks=2,
    )
    assert result["event_updates_generated"] == 2
    assert result["event_updates_received_by_websocket"] == 1
    assert result["websocket_update_coverage"] == 0.5
    assert result["model_inference_p95_ms"] == 5.9
    assert result["audio_timestamp_to_websocket_receipt_p95_ms"] == 250
    assert result["acoustic_onset_to_hud_p95_measured"] is False


def test_no_alert_does_not_claim_zero_latency():
    result = summarize([], {}, [5.0], [1.0], session="quiet", seconds=2.0, audio_blocks=20)
    assert result["model_inference_p95_ms"] == 5.0
    assert result["audio_timestamp_to_event_p95_ms"] is None
    assert result["audio_timestamp_to_websocket_receipt_p95_ms"] is None
    assert result["websocket_update_coverage"] is None


def test_offline_replay_measures_real_event_websocket_without_camera(tmp_path):
    recorder = Recorder(tmp_path)
    session = recorder.start({"config": {"audio_preprocessing": "off"}})
    pcm = np.full((16000, 1), 0.02, dtype=np.float32)
    for timestamp in (10.0, 10.12, 10.24):
        recorder.write(
            "audio", pcm, {"timestamp": timestamp, "rate": 16000, "source": "microphone"}
        )
    recorder.stop()

    class Classifier:
        def infer(self, samples):
            return {"horn": 0.9}

    result = asyncio.run(run_probe(tmp_path / session, 2, Classifier()))
    assert result["event_updates_generated"] >= 1
    assert result["event_updates_received_by_websocket"] >= 1
    assert result["model_inference_calls"] >= 2
    assert result["audio_timestamp_to_event_p95_ms"] >= 0
    assert result["event_to_websocket_receipt_p95_ms"] >= 0

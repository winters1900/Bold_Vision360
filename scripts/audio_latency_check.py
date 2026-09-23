"""Measure offline audio replay through fusion and the local event WebSocket.

This does not measure acoustic onset, camera capture, browser paint, or HUD visibility.
No request is sent to an already running service and the camera is never opened.
"""

import argparse
import asyncio
from dataclasses import asdict
import importlib
import json
import os
from pathlib import Path
import sys
import threading
import time

from fastapi.testclient import TestClient
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

from server.audio import Classifier  # noqa: E402
from server.domain import Fusion  # noqa: E402
from server.recording import load_timeline, safe_session  # noqa: E402
from server.runtime import Runtime  # noqa: E402


class TimedClassifier:
    def __init__(self, classifier):
        self.classifier = classifier
        self.inference_ms = []
        self.lock = threading.Lock()

    def infer(self, samples):
        started = time.perf_counter()
        result = self.classifier.infer(samples)
        with self.lock:
            self.inference_ms.append((time.perf_counter() - started) * 1000)
        return result


class ProbeFusion(Fusion):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime
        self.produced = []

    def observe(self, *args, **kwargs):
        event = super().observe(*args, **kwargs)
        self.produced.append({**asdict(event), "classification_call_ms": self.runtime.audio_ms})
        return event


def percentile(values, q):
    return round(float(np.percentile(values, q)), 2) if values else None


def summarize(
    produced, received, model_ms, feed_lag_ms, *, session, seconds, audio_blocks, thresholds=None
):
    generated = [(event["generated_at"] - event["updated_at"]) * 1000 for event in produced]
    to_socket = []
    socket_delivery = []
    for event in produced:
        arrival = received.get((event["id"], event["generated_at"]))
        if arrival is not None:
            to_socket.append((arrival - event["updated_at"]) * 1000)
            socket_delivery.append((arrival - event["generated_at"]) * 1000)
    return {
        "session": session,
        "replayed_audio_seconds": seconds,
        "audio_blocks": audio_blocks,
        "event_updates_generated": len(produced),
        "event_updates_received_by_websocket": len(to_socket),
        "event_categories": sorted({event["category"] for event in produced})
        if produced and "category" in produced[0]
        else [],
        "thresholds": thresholds,
        "model_inference_calls": len(model_ms),
        "model_inference_p50_ms": percentile(model_ms, 50),
        "model_inference_p95_ms": percentile(model_ms, 95),
        "alerting_classification_call_p95_ms": percentile(
            [event["classification_call_ms"] for event in produced], 95
        ),
        "replay_feed_lag_p95_ms": percentile(feed_lag_ms, 95),
        "audio_timestamp_to_event_p95_ms": percentile(generated, 95),
        "audio_timestamp_to_websocket_receipt_p95_ms": percentile(to_socket, 95),
        "event_to_websocket_receipt_p95_ms": percentile(socket_delivery, 95),
        "websocket_update_coverage": round(len(to_socket) / len(produced), 3) if produced else None,
        "clock": "one local host monotonic clock; recorded relative timestamps rebased at replay start",
        "audio_timestamp_meaning": "last contributing decoded PCM block, not sound onset",
        "websocket": "in-process TestClient on the real /ws/events route, not a browser render",
        "metric_scope": "offline replay-chain proxy from last PCM block to server event/local WebSocket receipt; excludes physical acoustic onset, camera capture and browser paint",
        "acoustic_onset_to_hud_p95_measured": False,
    }


async def run_probe(folder, seconds, classifier):
    metadata = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    rows = [row for row in load_timeline(folder) if row["kind"] == "audio"]
    if not rows:
        raise ValueError("录制没有音频块")
    origin = rows[0]["timestamp"]
    # Preload before starting the clock so disk reads do not dominate playback timing.
    blocks = [
        (row, np.load(folder / row["file"], allow_pickle=False))
        for row in rows
        if row["timestamp"] - origin <= seconds
    ]
    runtime = Runtime()
    runtime.mode = "replay"
    runtime.phase = "running"
    runtime.generation = 1
    runtime.native = metadata.get("native", {})
    runtime.calibration = metadata.get("calibration")
    runtime.replay_audio_config = metadata.get("config", {})
    # Historical captures include their thresholds; use them for a reproducible
    # diagnostic even when local configuration has since changed.
    runtime.config["thresholds"].update(metadata.get("config", {}).get("thresholds", {}))
    timed = TimedClassifier(classifier)
    runtime.classifier = timed
    runtime.fusion = ProbeFusion(runtime)

    # Reuse the shipped WebSocket route without starting its lifespan, TCP capture
    # listener, another HTTP server, or the native camera process.
    app_module = importlib.import_module("server.app")
    previous = app_module.runtime
    app_module.runtime = runtime
    received = {}
    errors = []
    duration = blocks[-1][0]["timestamp"] - origin + 0.8

    def receive_events():
        try:
            with TestClient(app_module.app).websocket_connect("/ws/events") as socket:
                deadline = time.perf_counter() + duration
                while time.perf_counter() < deadline:
                    snapshot = socket.receive_json()
                    arrival = time.perf_counter()
                    for event in snapshot["history"]:
                        if "generated_at" in event:
                            received.setdefault((event["id"], event["generated_at"]), arrival)
        except Exception as exc:
            errors.append(exc)

    consumer = threading.Thread(target=receive_events, daemon=True)
    worker = asyncio.create_task(runtime.audio_worker())
    start = time.perf_counter() + 0.15
    feed_lag_ms = []
    try:
        consumer.start()
        for row, pcm in blocks:
            scheduled = start + row["timestamp"] - origin
            await asyncio.sleep(max(0, scheduled - time.perf_counter()))
            feed_lag_ms.append(max(0, time.perf_counter() - scheduled) * 1000)
            await runtime.audio_queue.put(
                (
                    pcm,
                    row["rate"],
                    row["source"],
                    scheduled,
                    runtime.generation,
                    row.get("camera_us"),
                )
            )
        await asyncio.sleep(0.35)
        await asyncio.to_thread(consumer.join, duration + 3)
        if consumer.is_alive():
            raise TimeoutError("事件 WebSocket 诊断未能按时结束")
        if errors:
            raise RuntimeError("事件 WebSocket 诊断失败") from errors[0]
        return summarize(
            runtime.fusion.produced,
            received,
            timed.inference_ms,
            feed_lag_ms,
            session=folder.name,
            seconds=round(blocks[-1][0]["timestamp"] - origin, 3),
            audio_blocks=len(blocks),
            thresholds=runtime.config["thresholds"],
        )
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        app_module.runtime = previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--recordings-root", type=Path, default=ROOT / "recordings")
    parser.add_argument("--model", type=Path, default=ROOT / "models/yamnet")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/local-audio-latency.json")
    args = parser.parse_args()
    if not 1 < args.seconds <= 120:
        parser.error("--seconds must be greater than 1 and at most 120")
    folder = safe_session(args.recordings_root, args.session)
    report = asyncio.run(run_probe(folder, args.seconds, Classifier(args.model)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

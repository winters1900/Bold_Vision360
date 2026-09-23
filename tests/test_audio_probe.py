"""The mode probe must never pass computer-mic fallback off as camera evidence."""

import json
import httpx
import pytest
from scripts import camera_audio_probe as probe


@pytest.mark.parametrize("source", ["camera", "microphone"])
def test_probe_preserves_failed_trials_and_releases_capture(monkeypatch, tmp_path, source):
    clock, active, calls = [0.0], [False], []
    output = tmp_path / "probe.json"

    def advance(seconds):
        clock[0] += seconds

    def respond(request):
        path = request.url.path
        calls.append((request.method, path))
        if path == "/api/start":
            active[0] = True
        if path == "/api/stop":
            active[0] = False
        if path == "/api/status":
            return httpx.Response(
                200,
                json=dict(
                    mode="live" if active[0] else "idle",
                    phase="running",
                    error=None,
                    now=clock[0],
                    fps=30,
                    frame_age_ms=0,
                    audio_source=source,
                    channels=2,
                    audio_rate=48000,
                    audio_layout="stereo",
                    audio_signal=dict(observed_ms=1000, structure="dual_mono"),
                    localization={},
                    audio_processing={},
                    audio_comparison={},
                    audio_drops=0,
                ),
            )
        if path == "/api/record/start":
            return httpx.Response(200, json={"session": "test-session"})
        return httpx.Response(200, json={})

    real_client = httpx.Client
    monkeypatch.setattr(
        probe.httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw),
    )
    monkeypatch.setattr(probe.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(probe.time, "sleep", advance)
    monkeypatch.setattr(
        probe.sys,
        "argv",
        ["probe", "--profile", "ambisonic", "--seconds", "2", "--output", str(output)],
    )
    if source == "microphone":
        with pytest.raises(SystemExit) as exc:
            probe.main()
        assert exc.value.code == 1
    else:
        probe.main()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert not active[0] and calls[-1] == ("POST", "/api/stop")
    assert report["capture_completed"] == (source == "camera")
    assert not report["field_accuracy_measured"]
    if source == "microphone":
        assert report["median_fps"] is None and report["samples"] == []
        assert "microphone fallback" in report["errors"][0]
        assert ("POST", "/api/record/start") not in calls

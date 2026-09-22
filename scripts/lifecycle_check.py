"""Hardware integration checks. Requires the service and the attached X4 Air."""

import json
import time
from pathlib import Path
import requests
import psutil

BASE = "http://127.0.0.1:8765/api/"


def call(path, body=None):
    r = requests.post(BASE + path, json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def status():
    return requests.get(BASE + "status", timeout=5).json()


def wait_for(predicate, seconds=90):
    start = time.monotonic()
    while time.monotonic() - start < seconds:
        s = status()
        if predicate(s):
            return s
        time.sleep(0.5)
    raise AssertionError(f"Timed out: {s}")


def healthy(s):
    return (
        s["phase"] == "running"
        and s["fps"] > 10
        and s["frame_age_ms"] is not None
        and s["frame_age_ms"] < 1000
    )


def main():
    root = Path(__file__).resolve().parents[1]
    checks = []
    for i in range(3):
        call("start", {"mode": "live"})
        s = wait_for(healthy)
        time.sleep(3)
        s = status()
        assert healthy(s)
        call("stop")
        assert status()["phase"] == "stopped"
        children = [
            p
            for p in psutil.process_iter(["name", "exe"])
            if p.info["name"] == "bold_capture.exe"
            and p.info["exe"]
            and str(root).lower() in p.info["exe"].lower()
        ]
        assert not children, "Capture child leaked after stop"
        checks.append(
            {
                "check": f"live_start_stop_{i + 1}",
                "passed": True,
                "fps": s["fps"],
                "audio_source": s["audio_source"],
                "clock": s["clock_diagnostics"],
            }
        )
        print(checks[-1], flush=True)
    call("start", {"mode": "live"})
    wait_for(healthy)
    session = call("record/start")["session"]
    time.sleep(8)
    call("record/stop")
    checks.append({"check": "record", "passed": True, "session": session})
    captured_id = status()["frame_id"]
    for proc in psutil.process_iter(["name", "exe"]):
        if (
            proc.info["name"] == "bold_capture.exe"
            and proc.info["exe"]
            and str(root).lower() in proc.info["exe"].lower()
        ):
            proc.kill()
    s = wait_for(lambda s: healthy(s) and s["frame_id"] > captured_id + 20)
    checks.append({"check": "capture_process_crash_recovery", "passed": True, "fps": s["fps"]})
    print(checks[-1], flush=True)
    call("start", {"mode": "replay", "session": session})
    s = wait_for(lambda s: s["mode"] == "replay" and healthy(s), 20)
    time.sleep(2)
    s = status()
    assert s["audio_source"] == "camera" and s["channels"] == 2
    checks.append(
        {
            "check": "recorded_video_audio_replay",
            "passed": True,
            "fps": s["fps"],
            "audio_source": s["audio_source"],
        }
    )
    wait_for(lambda s: s["phase"] == "ended", 20)
    call("start", {"mode": "live"})
    wait_for(healthy)
    report = {
        "passed": True,
        "checks": checks,
        "not_tested": [
            "physical USB disconnect/reconnect",
            "labelled 240-trial accuracy",
            "quiet negative false-positive rate",
        ],
    }
    (root / "reports/local-lifecycle.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

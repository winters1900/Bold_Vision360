"""Record and measure one operator-confirmed camera audio mode through the local service.

The SDK does not switch the camera's audio mode. Set it on the camera first. This
probe labels the mode, starts live capture, records source PCM and exports measured
channel capability. It stops capture on exit to allow the next physical mode change.
"""

import argparse
import json
from pathlib import Path
import statistics
import sys
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.noise import CAMERA_PROFILES, CAMERA_MICROPHONES  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=CAMERA_PROFILES)
    parser.add_argument("--microphone", default="builtin", choices=CAMERA_MICROPHONES)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 2 <= args.seconds <= 60:
        parser.error("--seconds must be between 2 and 60")
    samples, session, diagnostics, errors = [], None, None, []
    with httpx.Client(base_url=args.url, trust_env=False, timeout=15) as client:

        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def post(path, body=None):
            response = client.post(path, json=body)
            response.raise_for_status()
            return response.json()

        if get("/api/status")["mode"] != "idle":
            parser.error("Stop capture in the webpage first; the probe requires an idle service")
        post(
            "/api/config",
            dict(
                audio_profile=args.profile,
                camera_microphone=args.microphone,
                audio_preprocessing="off",
            ),
        )
        try:
            post("/api/start", {"mode": "live"})
            deadline = time.perf_counter() + 30
            while time.perf_counter() < deadline:
                state = get("/api/status")
                if state["phase"] == "error":
                    raise RuntimeError(state["error"])
                if (
                    state["phase"] == "running"
                    and state["audio_source"] == "camera"
                    and state["audio_signal"]["observed_ms"] >= 500
                ):
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError(
                    "No valid camera audio arrived within 30 s; microphone fallback is not a camera-mode result"
                )
            session = post("/api/record/start")["session"]
            deadline = time.perf_counter() + args.seconds
            while time.perf_counter() < deadline:
                state = get("/api/status")
                samples.append(
                    {
                        k: state[k]
                        for k in (
                            "now",
                            "fps",
                            "frame_age_ms",
                            "audio_source",
                            "channels",
                            "audio_rate",
                            "audio_layout",
                            "audio_signal",
                            "localization",
                            "audio_processing",
                            "audio_comparison",
                            "audio_drops",
                            "error",
                        )
                    }
                )
                if (
                    state["audio_source"] != "camera"
                    or state["frame_age_ms"] is None
                    or state["frame_age_ms"] >= 2000
                ):
                    raise RuntimeError("Camera audio/video disconnected during probe")
                time.sleep(0.2)
            diagnostics = get("/api/audio/diagnostics")
        except Exception as exc:
            errors.append(str(exc))
            try:
                diagnostics = get("/api/audio/diagnostics")
            except Exception as diagnostic_error:
                errors.append("diagnostics: " + str(diagnostic_error))
        finally:
            for path in (["/api/record/stop"] if session else []) + ["/api/stop"]:
                try:
                    post(path)
                except Exception as cleanup_error:
                    errors.append("cleanup: " + str(cleanup_error))
    report = dict(
        capture_completed=not errors,
        errors=errors,
        session=session,
        profile=args.profile,
        profile_source="operator_confirmed",
        microphone=args.microphone,
        requested_seconds=args.seconds,
        observed_span_seconds=samples[-1]["now"] - samples[0]["now"] if len(samples) > 1 else 0,
        channel_counts=sorted({s["channels"] for s in samples}),
        rates=sorted({s["audio_rate"] for s in samples}),
        structures=sorted({s["audio_signal"]["structure"] for s in samples}),
        median_fps=statistics.median(s["fps"] for s in samples) if samples else None,
        field_accuracy_measured=False,
        diagnostics=diagnostics,
        samples=samples,
    )
    capture_id = session or time.strftime("%Y%m%d-%H%M%S-failed")
    output = args.output or ROOT / f"reports/local-audio-probe-{args.profile}-{capture_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("samples", "diagnostics")}))
    print(str(output))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

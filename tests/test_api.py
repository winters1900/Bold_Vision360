from fastapi.testclient import TestClient
from server.app import app, runtime


# No lifespan: these tests exercise guards without acquiring real camera hardware.
def test_simulation_cannot_be_injected_into_live_session():
    runtime.mode = "live"
    try:
        client = TestClient(app)
        assert (
            client.post("/api/simulate", json={"category": "horn", "angle": 225}).status_code == 409
        )
        assert client.post("/api/config", json={}).status_code == 409
    finally:
        runtime.mode = "idle"


def test_simulation_mode_is_explicit_and_angles_validated():
    runtime.mode = "simulation"
    try:
        client = TestClient(app)
        assert (
            client.post("/api/simulate", json={"category": "horn", "angle": 360}).status_code == 422
        )
        assert client.post("/api/simulate", json={"category": "bogus"}).status_code == 400
        data = client.post("/api/simulate", json={"category": "horn", "angle": 225}).json()
        assert data["mode"] == "simulation" and data["events"][0]["simulated"]
        assert data["events"][0]["evidence"] == "simulation"
    finally:
        runtime.mode = "idle"
        runtime.fusion.clear()


def test_remote_web_origin_cannot_control_camera():
    response = TestClient(app).post("/api/stop", headers={"Origin": "https://unrelated.example"})
    assert response.status_code == 403


def test_no_recording_without_live_frames():
    runtime.mode = "idle"
    assert TestClient(app).post("/api/record/start").status_code == 409


def test_audio_diagnostics_separates_declared_profile_from_measured_capability():
    response = TestClient(app).get("/api/audio/diagnostics")
    assert response.status_code == 200
    data = response.json()
    assert "declared_audio_profile" in data and "audio_signal" in data
    assert not data["localization"]["acoustic_available"]
    assert "attachment" in response.headers["content-disposition"]


def test_partial_settings_update_preserves_confirmed_camera_mode(monkeypatch, tmp_path):
    original, calibration = runtime.config.copy(), runtime.calibration
    monkeypatch.setattr("server.app.ROOT", tmp_path)
    runtime.mode = "idle"
    try:
        runtime.config.update(
            audio_profile="wind_reduction_strong",
            camera_microphone="builtin",
            audio_preprocessing="off",
        )
        response = TestClient(app).post("/api/config", json={"forward_offset_deg": 20})
        assert response.status_code == 200
        assert response.json()["audio_profile"] == "wind_reduction_strong"
        assert response.json()["camera_microphone"] == "builtin"
        assert response.json()["audio_preprocessing"] == "off"
    finally:
        runtime.config.clear()
        runtime.config.update(original)
        runtime.calibration = calibration

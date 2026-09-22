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

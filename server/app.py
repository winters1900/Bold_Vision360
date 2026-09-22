import asyncio
from contextlib import asynccontextmanager
import json
import time
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .runtime import Runtime, ROOT
from .domain import LABELS

runtime = Runtime()


@asynccontextmanager
async def lifespan(app):
    await runtime.initialize()
    yield
    await runtime.shutdown()


app = FastAPI(title="Bold Vision 360", lifespan=lifespan)


@app.middleware("http")
async def local_origin(request, call_next):
    origin = request.headers.get("origin")
    if origin and origin not in {
        f"http://127.0.0.1:{runtime.config['port']}",
        f"http://localhost:{runtime.config['port']}",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }:
        return Response("Forbidden origin", status_code=403)
    return await call_next(request)


@app.get("/api/status")
async def status():
    return runtime.snapshot()


class Start(BaseModel):
    mode: str = "live"
    session: str | None = None


@app.post("/api/start")
async def start(body: Start):
    try:
        return await runtime.start(body.mode, body.session)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/stop")
async def stop():
    return await runtime.stop()


@app.get("/api/config")
def config():
    return runtime.config


class Settings(BaseModel):
    forward_offset_deg: float = Field(0, ge=-180, le=180)
    audio_profile: str = Field("unknown", max_length=80)
    microphone_fallback: bool = True
    microphone_device: int | None = None


@app.post("/api/config")
async def configure(body: Settings):
    if runtime.mode != "idle":
        raise HTTPException(409, "请先停止采集再修改设置")
    runtime.config.update(body.model_dump())
    runtime.calibration = None
    (ROOT / "config.local.json").write_text(
        json.dumps(runtime.config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return runtime.config


@app.get("/api/microphones")
def microphones():
    import sounddevice as sd

    return [
        {"id": i, "name": d["name"], "channels": d["max_input_channels"]}
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0
    ]


@app.post("/api/record/start")
async def record():
    if runtime.mode != "live" or runtime.phase != "running":
        raise HTTPException(409, "仅运行中的实时模式可录制")
    if runtime.recorder.file:
        raise HTTPException(409, "录制已开启")
    return {
        "session": runtime.recorder.start(
            {"native": runtime.native, "calibration": runtime.calibration, "config": runtime.config}
        )
    }


@app.post("/api/record/stop")
async def stop_record():
    runtime.recorder.stop()
    return {"ok": True}


@app.get("/api/recordings")
def recordings():
    return [
        {"name": p.name, "bytes": sum(f.stat().st_size for f in p.iterdir() if f.is_file())}
        for p in sorted((ROOT / "recordings").glob("*"), reverse=True)
        if (p / "timeline.jsonl").exists()
    ]


class Calibration(BaseModel):
    angle: int | str


@app.post("/api/calibration/capture")
async def calibration(body: Calibration):
    try:
        return await runtime.calibrate(body.angle)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/calibration/reset")
async def reset_calibration():
    if runtime.calibration_lock.locked():
        raise HTTPException(409, "标定采样中，请等待采样结束")
    runtime.calibration = None
    runtime.calibration_samples.clear()
    (ROOT / "runtime/calibration.json").unlink(missing_ok=True)
    return {"ok": True}


class Simulation(BaseModel):
    category: str = "horn"
    angle: float | None = Field(None, ge=0, lt=360)


@app.post("/api/simulate")
async def simulate(body: Simulation):
    if runtime.mode != "simulation":
        raise HTTPException(409, "仅明确标记的模拟模式可注入事件")
    if body.category not in LABELS:
        raise HTTPException(400, "未知声音类别")
    runtime.fusion.observe(
        body.category, 0.9, time.perf_counter(), [], "simulation", body.angle, 1, True
    )
    return runtime.snapshot()


@app.get("/api/events/export")
async def export():
    _, history = runtime.fusion.snapshot(time.perf_counter())
    return Response(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in history),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="events.jsonl"'},
    )


async def accept_socket(ws):
    origin = ws.headers.get("origin")
    if origin and origin not in {
        f"http://127.0.0.1:{runtime.config['port']}",
        f"http://localhost:{runtime.config['port']}",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }:
        await ws.close(code=1008)
        return False
    await ws.accept()
    return True


@app.websocket("/ws/events")
async def events(ws: WebSocket):
    if not await accept_socket(ws):
        return
    try:
        while True:
            await asyncio.wait_for(ws.send_json(runtime.snapshot()), 2)
            await asyncio.sleep(0.1)
    except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
        pass


@app.websocket("/ws/frames")
async def frames(ws: WebSocket):
    if not await accept_socket(ws):
        return
    last = -1
    try:
        while True:
            if runtime.jpeg and runtime.frame_id != last:
                last = runtime.frame_id
                await asyncio.wait_for(ws.send_bytes(runtime.jpeg), 2)
            await asyncio.sleep(0.03)
    except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
        pass


if (ROOT / "web/dist/assets").exists():
    app.mount("/assets", StaticFiles(directory=ROOT / "web/dist/assets"), name="assets")


@app.get("/")
def index():
    file = ROOT / "web/dist/index.html"
    if not file.exists():
        return Response("Build frontend first: scripts/build.ps1", status_code=503)
    return FileResponse(file)

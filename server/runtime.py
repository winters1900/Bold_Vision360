import asyncio
from collections import deque
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import struct
import time
import numpy as np
from PIL import Image
from .audio import AudioWindow, Classifier, fit_axes, intensity
from .domain import Fusion, delta
from .recording import Recorder, safe_session, load_timeline
from .vision import Detector
from .clock import CameraClock

ROOT=Path(__file__).resolve().parents[1]

class Runtime:
    def __init__(self):
        file=ROOT/"config.local.json"
        self.config=json.loads((file if file.exists() else ROOT/"config.example.json").read_text(encoding="utf-8-sig"))
        self.mode="idle";self.phase="stopped";self.error=None
        self.fusion=Fusion();self.targets=[];self.jpeg=None;self.rgb=None;self.frame_id=0;self.frame_time=0
        self.last_camera_audio=0;self.native={};self.process=None;self.writer=None;self.runner=None
        self.audio_queue=asyncio.Queue(maxsize=128);self.raw_queue=asyncio.Queue(maxsize=128)
        self.window=AudioWindow();self.audio_source="none";self.audio_rate=0;self.channels=0;self.energy=0
        self.scores={};self.mic=None;self.detector=None;self.classifier=None
        self.model_status={"vision":"loading","audio":"loading"};self.detection_ms=0;self.audio_ms=0
        self.classification_time=0;self.frame_times=deque(maxlen=60);self.drops=0;self.frame_signal=asyncio.Event()
        self.recorder=Recorder(ROOT/"recordings");self.tasks=[];self.calibration=None;self.calibration_samples={}
        self.calibration_ring=deque(maxlen=150);self.calibration_lock=asyncio.Lock();self.lifecycle=asyncio.Lock()
        self.last_observation={};self.generation=0;self.capture_started=0;self.latest_raw=None
        self.calibration_stage=None;self.rotation_sample=None;self.seen_audio_time=None
        self.clock_samples={};self.clock_diagnostics={};self.audio_layout="unknown"
        self.clock=CameraClock()

    async def initialize(self):
        (ROOT/"runtime").mkdir(exist_ok=True);(ROOT/"recordings").mkdir(exist_ok=True)
        self.loop=asyncio.get_running_loop()
        self.server=await asyncio.start_server(self.capture_client,"127.0.0.1",self.config["capture_port"])
        self.tasks=[asyncio.create_task(job()) for job in (self.load_models,self.frame_worker,self.audio_worker,self.decode_worker,self.vision_worker,self.watchdog)]

    async def load_models(self):
        async def load(name, factory):
            try:
                result=await asyncio.to_thread(factory)
                if name=="audio":self.classifier=result
                else:self.detector=result
                self.model_status[name]="ready"+(":"+result.provider if name=="vision" else "")
            except Exception as exc:self.model_status[name]="error: "+str(exc)[:240]
        await asyncio.gather(load("vision",lambda:Detector(ROOT/"models/yolov8n.onnx")),
                             load("audio",lambda:Classifier(ROOT/"models/yamnet")))

    def snapshot(self):
        now=time.perf_counter();active,history=self.fusion.snapshot(now)
        if self.mode=="live" and now-self.frame_time>2:active=[]
        fps=(len(self.frame_times)-1)/(self.frame_times[-1]-self.frame_times[0]) if len(self.frame_times)>1 else 0
        return {"mode":self.mode,"phase":self.phase,"error":self.error,"now":now,"frame_id":self.frame_id,
                "frame_age_ms":round((now-self.frame_time)*1000) if self.frame_time else None,
                "fps":round(fps,1),"audio_source":self.audio_source,"channels":self.channels,"audio_rate":self.audio_rate,
                "audio_layout":self.audio_layout,"energy":self.energy,"scores":self.scores,"models":self.model_status,
                "detection_ms":round(self.detection_ms,1),"audio_inference_ms":round(self.audio_ms,1),
                "classification_age_ms":round((now-self.classification_time)*1000) if self.classification_time else None,
                "native":self.native,"targets":self.targets if now-self.frame_time<2 else [],"events":active,"history":history,
                "recording":self.recorder.folder.name if self.recorder.file else None,"audio_drops":self.drops,
                "calibration":self.calibration,"calibration_stage":self.calibration_stage,
                "calibration_captured":sorted(self.calibration_samples),"clock_diagnostics":self.clock_diagnostics,
                "forward_offset_deg":self.config["forward_offset_deg"]}

    async def start(self, mode="live", session=None):
        if mode not in ("live","replay","simulation"):raise ValueError("不支持的数据源")
        if mode=="replay":safe_session(ROOT/"recordings",session or "")
        async with self.lifecycle:
            await self.stop_unlocked()
            self.generation+=1;self.mode=mode;self.phase="starting";self.error=None
            self.fusion=Fusion();self.targets=[];self.jpeg=None;self.rgb=None;self.frame_time=0;self.latest_raw=None
            self.frame_times.clear();self.audio_source="none";self.last_camera_audio=0;self.window.clear();self.last_observation.clear()
            self.native={};self.calibration_ring.clear();self.clock_samples.clear();self.clock_diagnostics.clear()
            self.scores={};self.energy=0;self.classification_time=0;self.calibration=None
            if mode=="live":self.runner=asyncio.create_task(self.capture_supervisor(self.generation))
            elif mode=="replay":self.runner=asyncio.create_task(self.replay(session,self.generation))
            else:self.phase="running"
        return self.snapshot()

    async def stop(self):
        async with self.lifecycle:await self.stop_unlocked()
        return self.snapshot()

    async def stop_unlocked(self):
        self.generation+=1;self.mode="idle";self.phase="stopped"
        if self.runner:self.runner.cancel()
        if self.runner:
            try:await self.runner
            except asyncio.CancelledError:pass
            self.runner=None
        await self.stop_process()
        if self.mic:
            await asyncio.to_thread(self.mic.stop);await asyncio.to_thread(self.mic.close);self.mic=None
        self.recorder.stop();self.fusion.clear();self.targets=[];self.window.clear();self.audio_source="none";self.energy=0
        self.latest_raw=None;self.jpeg=None;self.rgb=None;self.frame_time=0
        for queue in (self.audio_queue,self.raw_queue):
            while not queue.empty():queue.get_nowait()

    async def stop_process(self):
        proc=self.process
        if proc and proc.returncode is None:
            try:
                proc.stdin.write(b"stop\n");await proc.stdin.drain()
                await asyncio.wait_for(proc.wait(),8)
            except (BrokenPipeError,ConnectionResetError,asyncio.TimeoutError):
                if proc.returncode is None:proc.kill();await proc.wait()
            except asyncio.CancelledError:
                if proc.returncode is None:proc.kill();await proc.wait()
                raise
            finally:
                if self.process is proc:self.process=None
        if self.writer:self.writer.close();self.writer=None

    async def capture_supervisor(self, generation):
        exe=ROOT/"build/native/Release/bold_capture.exe"
        if not exe.exists():self.phase="error";self.error="未找到相机采集程序，请先运行 scripts/build.ps1";return
        media=Path(self.config["media_sdk"])
        for attempt in range(3):
            if generation!=self.generation:return
            self.phase="connecting";self.capture_started=time.perf_counter();self.frame_time=0
            self.clock_samples.clear();self.clock_diagnostics.clear();self.fusion.clear();self.window.clear()
            self.clock=CameraClock()
            args=[str(exe),str(self.config["capture_port"]),str(media/"bin/models")+os.sep]
            if self.config.get("software_decode"):args.append("software")
            env=os.environ.copy();env["PATH"]=str(media/"bin")+os.pathsep+env.get("PATH","")
            try:
                with (ROOT/"runtime/capture.log").open("ab") as log:
                    self.process=await asyncio.create_subprocess_exec(*args,cwd=media/"bin",env=env,
                        stdin=asyncio.subprocess.PIPE,stdout=log,stderr=log,creationflags=0x08000000)
                stream_start=None
                while generation==self.generation:
                    await asyncio.sleep(.25)
                    now=time.perf_counter()
                    if self.process.returncode is not None:raise RuntimeError(f"采集进程退出 ({self.process.returncode})，详见 runtime/capture.log")
                    if self.native.get("connected_at",0)>self.capture_started and stream_start is None:
                        stream_start=now
                    if self.frame_time and now-self.frame_time<2:self.phase="running";self.error=None
                    elif (stream_start and now-stream_start>5) or now-self.capture_started>30:
                        raise RuntimeError("相机未持续输出有效拼接帧；检查 USB、模式及 SDK 日志")
            except asyncio.CancelledError:raise
            except Exception as exc:
                self.error=str(exc);self.phase="retrying" if attempt<2 else "error"
                self.fusion.clear();self.targets=[];self.jpeg=None;self.rgb=None;self.frame_time=0
                await self.stop_process()
                if attempt<2:await asyncio.sleep(1)

    async def capture_client(self, reader, writer):
        if self.mode!="live" or self.writer:
            writer.close();return
        self.writer=writer;generation=self.generation
        try:
            while generation==self.generation:
                size=struct.unpack("!I",await reader.readexactly(4))[0]
                if not 0<size<65536:raise ValueError("Invalid capture header length")
                header=json.loads(await reader.readexactly(size));length=header["payload_bytes"]
                if not isinstance(length,int) or not 0<=length<=32*1024*1024:raise ValueError("Invalid capture payload length")
                data=await reader.readexactly(length);kind=header["kind"]
                if kind=="status":
                    header["connected_at"]=time.perf_counter();self.native=header
                    self.load_calibration()
                elif kind in ("rgba","aac"):
                    self.observe_clock(kind,header)
                    if kind=="rgba":self.latest_raw=(header,data,generation);self.frame_signal.set()
                    else:
                        self.last_camera_audio=time.perf_counter()
                        self.enqueue(self.raw_queue,(header,data,generation))
        except (asyncio.IncompleteReadError,ConnectionError):pass
        except Exception as exc:self.error="采集协议错误: "+str(exc)
        finally:
            writer.close()
            if self.writer is writer:self.writer=None

    def observe_clock(self,kind,header):
        header["received_at"]=header["host_time"]
        raw=header["camera_us"] # historical wire key; value is raw ticks, unit measured below
        previous=self.clock.previous.get(kind)
        if previous is not None and raw<previous:self.window.clear();self.fusion.clear()
        header["host_time"]=self.clock.align(kind,raw,header["host_time"])
        self.clock_diagnostics=self.clock.diagnostics.copy()

    def enqueue(self,queue,item):
        if queue.full():
            while not queue.empty():queue.get_nowait()
            self.drops+=1;self.window.clear()
            if queue is self.raw_queue:item[0]["discontinuity"]=True
        queue.put_nowait(item)

    async def frame_worker(self):
        while True:
            await self.frame_signal.wait();self.frame_signal.clear()
            item=self.latest_raw;self.latest_raw=None
            if not item:continue
            header,data,generation=item
            try:
                w,h=header["width"],header["height"]
                if not 0<w<=4096 or not 0<h<=2048 or len(data)!=w*h*4:raise ValueError("Invalid RGBA frame")
                rgb=np.frombuffer(data,dtype=np.uint8).reshape(h,w,4)[:,:,:3].copy()
                jpeg=await asyncio.to_thread(self.encode_jpeg,rgb)
                if generation==self.generation:self.publish_frame(rgb,jpeg,header["host_time"],header.get("camera_us"))
            except Exception as exc:self.error=str(exc)

    @staticmethod
    def encode_jpeg(rgb):
        out=io.BytesIO();Image.fromarray(rgb).save(out,format="JPEG",quality=85);return out.getvalue()

    def publish_frame(self,rgb,jpeg,timestamp,camera_us=None):
        self.rgb=rgb;self.jpeg=jpeg;self.frame_time=timestamp;self.frame_id+=1;self.frame_times.append(time.perf_counter())
        self.recorder.write("frame",jpeg,{"timestamp":timestamp,"camera_us":camera_us})

    async def decode_worker(self):
        import av
        decoder=av.CodecContext.create("aac","r");old_generation=-1
        while True:
            header,data,generation=await self.raw_queue.get()
            if generation!=self.generation:continue
            try:
                if header.get("discontinuity") or old_generation!=generation:
                    decoder=av.CodecContext.create("aac","r");self.window.clear();old_generation=generation
                for packet in decoder.parse(data):
                    for frame in decoder.decode(packet):
                        pcm=frame.to_ndarray()
                        channels=len(frame.layout.channels)
                        if frame.format.is_planar:pcm=pcm.T
                        else:pcm=pcm.reshape(-1,channels)
                        if np.issubdtype(pcm.dtype,np.integer):pcm=pcm.astype(np.float32)/32768
                        pcm=pcm.astype(np.float32)
                        self.audio_layout=frame.layout.name
                        self.enqueue(self.audio_queue,(pcm,frame.sample_rate,"camera",header["host_time"],generation,header.get("camera_us")))
            except Exception as exc:
                self.error="AAC 解码: "+str(exc);decoder=av.CodecContext.create("aac","r");self.window.clear()

    async def start_microphone(self):
        if self.mic:return
        import sounddevice as sd
        generation=self.generation
        def callback(data,frames,timing,status):
            if generation!=self.generation:return
            if status:self.loop.call_soon_threadsafe(self.window.clear)
            item=(data.copy(),16000,"microphone",time.perf_counter(),generation,None)
            self.loop.call_soon_threadsafe(self.enqueue,self.audio_queue,item)
        mic=sd.InputStream(samplerate=16000,channels=1,dtype="float32",blocksize=1600,
                           device=self.config.get("microphone_device"),callback=callback)
        mic.start();self.mic=mic

    async def audio_worker(self):
        while True:
            pcm,rate,source,timestamp,generation,camera_us=await self.audio_queue.get()
            if generation!=self.generation or self.mode not in ("live","replay"):continue
            if source=="microphone" and time.perf_counter()-self.last_camera_audio<2:continue
            if time.perf_counter()-timestamp>1.5:self.window.clear();self.drops+=1;continue
            self.audio_source=source;self.channels=pcm.shape[1];self.audio_rate=rate
            self.energy=self.window.append(pcm,rate,source,timestamp)
            self.recorder.write("audio",pcm,{"timestamp":timestamp,"rate":rate,"source":source,"camera_us":camera_us})
            if source=="camera" and self.channels==4:self.calibration_ring.append((timestamp,pcm.copy()))
            if not self.classifier or not self.window.ready(time.perf_counter()):continue
            started=time.perf_counter();self.window.last_infer=started
            try:scores=await asyncio.to_thread(self.classifier.infer,self.window.samples.copy())
            except Exception as exc:self.model_status["audio"]="error: "+str(exc);continue
            if generation!=self.generation:continue
            self.audio_ms=(time.perf_counter()-started)*1000;self.classification_time=time.perf_counter();self.scores=scores
            angle=None;direction_confidence=0
            if self.calibration and self.calibration.get("rotation_verified") and source=="camera" and self.channels==4:
                recent=[p for t,p in self.calibration_ring if timestamp-t<.3]
                if recent:angle,direction_confidence=intensity(np.concatenate(recent),self.calibration["mapping"])
            for category,score in scores.items():
                if score<self.config["thresholds"][category]:self.last_observation.pop(category,None);continue
                previous=self.last_observation.get(category)
                self.last_observation[category]=timestamp
                if previous is None or timestamp-previous>.4:continue
                event=self.fusion.observe(category,score,timestamp,self.targets,source,angle,direction_confidence)
                self.recorder.write("event",None,{"timestamp":timestamp,"event":asdict(event),"inference_ms":self.audio_ms})

    async def vision_worker(self):
        last=0
        while True:
            await asyncio.sleep(.1)
            if self.detector is None or self.rgb is None or last==self.frame_id:continue
            last=self.frame_id;rgb=self.rgb;timestamp=self.frame_time;generation=self.generation
            try:
                start=time.perf_counter()
                result=await asyncio.to_thread(self.detector.detect,rgb,timestamp,self.config["forward_offset_deg"])
                if generation==self.generation:self.targets=result;self.detection_ms=(time.perf_counter()-start)*1000
            except Exception as exc:self.model_status["vision"]="error: "+str(exc)

    async def watchdog(self):
        mic_retry=0
        while True:
            await asyncio.sleep(.5);now=time.perf_counter()
            if self.mode=="live":
                if now-self.frame_time>2:self.fusion.clear();self.targets=[]
                if self.config["microphone_fallback"] and now-max(self.last_camera_audio,self.capture_started)>5 and not self.mic and now>mic_retry:
                    try:await self.start_microphone()
                    except Exception as exc:self.error="电脑麦克风不可用: "+str(exc);mic_retry=now+15
            if self.window.last_time and now-self.window.last_time>1:
                self.energy=0;self.scores={};self.audio_source="none"

    async def replay(self,session,generation):
        try:
            folder=safe_session(ROOT/"recordings",session);entries=load_timeline(folder)
            metadata=json.loads((folder/"session.json").read_text(encoding="utf-8"))
            self.calibration=metadata.get("calibration");self.native=metadata.get("native",{})
            if not entries:raise ValueError("录制为空")
            start=time.perf_counter();original=entries[0]["timestamp"];self.phase="running"
            for entry in entries:
                if generation!=self.generation:return
                timestamp=start+entry["timestamp"]-original
                await asyncio.sleep(max(0,timestamp-time.perf_counter()))
                if entry["kind"]=="frame":
                    jpeg=(folder/entry["file"]).read_bytes();rgb=np.asarray(Image.open(io.BytesIO(jpeg)).convert("RGB"))
                    self.publish_frame(rgb,jpeg,timestamp,entry.get("camera_us"))
                elif entry["kind"]=="audio":
                    pcm=np.load(folder/entry["file"],allow_pickle=False)
                    self.enqueue(self.audio_queue,(pcm,entry["rate"],entry["source"],timestamp,generation,entry.get("camera_us")))
            await asyncio.sleep(1.5);self.phase="ended";self.fusion.clear()
        except asyncio.CancelledError:raise
        except Exception as exc:self.phase="error";self.error=str(exc)

    def load_calibration(self):
        path=ROOT/"runtime/calibration.json"
        if self.calibration or not path.exists():return
        data=json.loads(path.read_text(encoding="utf-8"))
        if data.get("serial")==self.native.get("serial") and data.get("audio_profile")==self.config["audio_profile"]:
            self.calibration=data

    async def calibrate(self,angle):
        if self.mode!="live" or self.audio_source!="camera" or self.channels!=4:raise ValueError("仅相机四声道实时音频支持此标定")
        if self.config["audio_profile"]=="unknown":raise ValueError("请先在设置中填写机身实际收音模式")
        async with self.calibration_lock:
            self.calibration_stage=angle;start=time.perf_counter()
            try:
                await asyncio.sleep(2)
                data=[pcm for t,pcm in self.calibration_ring if start<=t<=time.perf_counter()]
                if sum(len(p) for p in data)<self.audio_rate:raise ValueError("有效四声道数据不足一秒")
                pcm=np.concatenate(data)
                if angle in (0,90,180,270):
                    self.calibration_samples[angle]=pcm
                    if len(self.calibration_samples)==4:
                        self.calibration={**fit_axes(self.calibration_samples),"serial":self.native.get("serial"),"audio_profile":self.config["audio_profile"]}
                elif angle=="rotation":
                    if not self.calibration:raise ValueError("先完成四方位采样")
                    # Speaker stays in front in world coordinates; camera turns clockwise 90 degrees.
                    measured,confidence=intensity(pcm,self.calibration["mapping"])
                    if confidence<.2 or abs(delta(measured,270))>22.5:raise ValueError("转动测试未通过，尚不能确认头相对方向")
                    self.calibration["rotation_verified"]=True
                    (ROOT/"runtime/calibration.json").write_text(json.dumps(self.calibration,indent=2),encoding="utf-8")
                else:raise ValueError("无效标定步骤")
            finally:self.calibration_stage=None
        return self.snapshot()

    async def shutdown(self):
        await self.stop()
        for task in self.tasks:task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        self.server.close();await self.server.wait_closed()

import json
import time
from pathlib import Path
import numpy as np

class Recorder:
    def __init__(self, root):
        self.root=Path(root);self.folder=None;self.file=None;self.count=0

    def start(self, metadata):
        self.stop();self.folder=self.root/time.strftime("%Y%m%d-%H%M%S")
        self.folder.mkdir(parents=True,exist_ok=False);self.count=0
        (self.folder/"session.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
        self.file=(self.folder/"timeline.jsonl").open("w",encoding="utf-8")
        return self.folder.name

    def write(self, kind, payload, meta):
        if not self.file:return
        self.count+=1;name=f"{self.count:08d}."+("jpg" if kind=="frame" else "npy")
        if kind=="frame":(self.folder/name).write_bytes(payload)
        elif kind=="audio":np.save(self.folder/name,payload,allow_pickle=False)
        else:name=None
        self.file.write(json.dumps({**meta,"kind":kind,"file":name},ensure_ascii=False)+"\n")
        self.file.flush()

    def stop(self):
        if self.file:self.file.close()
        self.file=None

def safe_session(root, name):
    root=Path(root).resolve();path=(root/name).resolve()
    if path.parent!=root or not (path/"timeline.jsonl").is_file():raise ValueError("无效录制会话")
    return path

def load_timeline(folder):
    entries=[json.loads(line) for line in (folder/"timeline.jsonl").read_text(encoding="utf-8").splitlines()]
    entries.sort(key=lambda entry:entry["timestamp"])
    for entry in entries:
        if entry.get("file") and (folder/entry["file"]).resolve().parent!=folder.resolve():raise ValueError("非法素材路径")
    return entries

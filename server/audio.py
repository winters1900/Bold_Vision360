import csv
import itertools
import math
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly
from .domain import delta

GROUPS={"horn":["Vehicle horn, car horn, honking","Air horn, truck horn","Honking"],
        "siren":["Siren","Civil defense siren","Police car (siren)","Ambulance (siren)","Fire engine, fire truck (siren)"],
        "bell":["Bicycle bell"],"shout":["Shout","Yell","Screaming"],"speech":["Speech","Conversation"]}

class Classifier:
    def __init__(self, root:Path):
        import tensorflow as tf
        tf.config.threading.set_intra_op_parallelism_threads(2)
        tf.config.threading.set_inter_op_parallelism_threads(2)
        self.model=tf.saved_model.load(str(root))
        with open(root/"assets"/"yamnet_class_map.csv",encoding="utf-8") as f:
            labels=[row["display_name"] for row in csv.DictReader(f)]
        self.indices={k:[i for i,v in enumerate(labels) if v in names] for k,names in GROUPS.items()}
        self.model(np.zeros(16000,dtype=np.float32))

    def infer(self, mono):
        scores=self.model(mono.astype(np.float32))[0].numpy().mean(axis=0)
        return {k:float(max(scores[idx])) if idx else 0 for k,idx in self.indices.items()}

class AudioWindow:
    def __init__(self):
        self.clear()

    def clear(self):
        self.samples=np.empty(0,dtype=np.float32)
        self.source=None;self.last_time=None;self.last_infer=0

    def append(self, pcm, rate, source, timestamp):
        if source!=self.source or (self.last_time is not None and timestamp-self.last_time>.35):self.clear()
        self.source=source;self.last_time=timestamp
        mono=pcm.mean(axis=1)
        g=math.gcd(rate,16000)
        out=resample_poly(mono,16000//g,rate//g).astype(np.float32)
        self.samples=np.concatenate([self.samples,out])[-16000:]
        return float(np.sqrt(np.mean(mono**2)))

    def ready(self, now):
        return len(self.samples)>=15600 and now-self.last_infer>=.1

def intensity(pcm, mapping):
    # Remove DC; integrate over the window. Only enabled after measured calibration.
    p=pcm.astype(np.float64)-pcm.mean(axis=0)
    w,x,y=(p[:,mapping[k]] for k in ("w","x","y"))
    ix=float(np.mean(w*x))*mapping["sx"];iy=float(np.mean(w*y))*mapping["sy"]
    energy=float(np.mean(w*w+x*x+y*y))
    confidence=min(1.,2*math.hypot(ix,iy)/max(energy,1e-12))
    return math.degrees(math.atan2(iy,ix))%360,confidence

def fit_axes(samples):
    """Four labelled captures; accept only a unique consistent directional mapping."""
    if set(samples)!={0,90,180,270}:raise ValueError("需要前、右、后、左四段采样")
    candidates=[]
    for w,x,y in itertools.permutations(range(4),3):
        for sx,sy in itertools.product((-1,1),repeat=2):
            mapping=dict(w=w,x=x,y=y,sx=sx,sy=sy)
            estimates=[(target,*intensity(pcm,mapping)) for target,pcm in samples.items()]
            error=float(np.mean([abs(delta(a,t)) for t,a,_ in estimates]))
            minimum=min(c for _,_,c in estimates)
            candidates.append((error,minimum,mapping,estimates))
    candidates=[item for item in candidates if item[1]>=.2]
    if not candidates:raise ValueError("声场置信度过低，无法确认方向")
    candidates.sort(key=lambda item:item[0])
    best=candidates[0]
    if best[0]>22.5 or best[1]<.2:raise ValueError("方向误差或声场置信度未达标，请在安静环境重新采样")
    if len(candidates)>1 and candidates[1][0]-best[0]<5:raise ValueError("声道映射不唯一，不能确认 Ambisonic；请重新采样")
    return {"mapping":best[2],"mean_error_deg":best[0],"minimum_confidence":best[1],"rotation_verified":False}

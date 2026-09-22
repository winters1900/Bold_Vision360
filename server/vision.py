import io
import time
from pathlib import Path
import numpy as np
from PIL import Image
from .domain import delta

CLASSES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

def circular_iou(a, b):
    def regular(x, y):
        left, top = max(x[0],y[0]),max(x[1],y[1])
        right,bottom=min(x[0]+x[2],y[0]+y[2]),min(x[1]+x[3],y[1]+y[3])
        area=max(0,right-left)*max(0,bottom-top)
        return area/max(1e-9,x[2]*x[3]+y[2]*y[3]-area)
    return max(regular(a,[b[0]+shift,*b[1:]]) for shift in (-1,0,1))

class Detector:
    def __init__(self, path: Path):
        import onnxruntime as ort
        opts=ort.SessionOptions();opts.enable_mem_pattern=False;opts.intra_op_num_threads=2
        try:
            self.session=ort.InferenceSession(str(path),sess_options=opts,providers=["DmlExecutionProvider","CPUExecutionProvider"])
        except Exception:
            self.session=ort.InferenceSession(str(path),sess_options=opts,providers=["CPUExecutionProvider"])
        self.provider=self.session.get_providers()[0]
        self.previous=[]
        self.track_counter=0

    def detect(self, rgb, timestamp, forward=0):
        # Circular padding presents targets split by the ERP seam as whole objects.
        h,w=rgb.shape[:2];pad=w//4
        padded=np.concatenate([rgb[:,-pad:],rgb,rgb[:,:pad]],axis=1)
        scale=min(640/padded.shape[1],640/h)
        nw,nh=round(padded.shape[1]*scale),round(h*scale)
        canvas=np.full((640,640,3),114,dtype=np.uint8)
        ox,oy=(640-nw)//2,(640-nh)//2
        canvas[oy:oy+nh,ox:ox+nw]=np.asarray(Image.fromarray(padded).resize((nw,nh)))
        inp=np.transpose(canvas.astype(np.float32)/255,(2,0,1))[None]
        output=self.session.run(None,{self.session.get_inputs()[0].name:inp})[0][0]
        if output.shape[0]<output.shape[1]:output=output.T
        detections=[]
        for row in output:
            cls=int(np.argmax(row[4:]));score=float(row[4+cls])
            if cls not in CLASSES or score<.35:continue
            cx,cy,bw,bh=row[:4];cx=(cx-ox)/scale-pad;cy=(cy-oy)/scale;bw/=scale;bh/=scale
            if not (-pad <= cx <= w+pad):continue
            bbox=[float(((cx-bw/2)/w)%1),float(max(0,(cy-bh/2)/h)),float(min(1,bw/w)),float(min(1,bh/h))]
            detections.append({"label":CLASSES[cls],"confidence":score,"bbox":bbox,
                               "angle":float(((cx/w-.5)*360-forward)%360),"timestamp":timestamp})
        kept=[]
        for d in sorted(detections,key=lambda d:-d["confidence"]):
            if not any(d["label"]==k["label"] and circular_iou(d["bbox"],k["bbox"])>.45 for k in kept):kept.append(d)
        used=set()
        for d in kept:
            matches=[p for p in self.previous if p["track_id"] not in used and p["label"]==d["label"]
                     and 0<timestamp-p["timestamp"]<.8 and abs(delta(p["angle"],d["angle"]))<20]
            prev=min(matches,key=lambda p:abs(delta(p["angle"],d["angle"]))) if matches else None
            if prev:
                d["track_id"]=prev["track_id"];used.add(prev["track_id"])
                dt=timestamp-prev["timestamp"]
                growth=(d["bbox"][3]/max(.01,prev["bbox"][3])-1)/max(.01,dt)
                d["growth"]=.7*prev.get("growth",0)+.3*growth
                d["approaching"]=d["growth"]>.25
            else:
                self.track_counter+=1;d.update(track_id=self.track_counter,growth=0,approaching=False)
        self.previous=kept
        return kept

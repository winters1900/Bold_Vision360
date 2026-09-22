import json
import numpy as np
import pytest
from server.audio import AudioWindow,intensity,fit_axes
from server.domain import delta
from server.vision import circular_iou
from server.recording import Recorder,safe_session,load_timeline

def test_seam_boxes_merge():
    assert circular_iou([.98,.2,.1,.2],[-.02,.2,.1,.2])>.99
    assert circular_iou([.98,.2,.1,.2],[.4,.2,.1,.2])==0

def test_resampling_and_discontinuity_reset():
    window=AudioWindow()
    for i in range(11):window.append(np.ones((4800,2),np.float32),48000,'camera',i*.1)
    assert len(window.samples)==16000 and window.ready(2)
    window.append(np.ones((1600,1),np.float32),16000,'microphone',1.1)
    assert len(window.samples)==1600
    window.append(np.ones((1600,1),np.float32),16000,'microphone',3)
    assert len(window.samples)==1600

def test_intensity_cardinals_and_calibration():
    rng=np.random.default_rng(3);signal=rng.normal(size=4800);samples={}
    for angle in (0,90,180,270):
        a=np.radians(angle)
        # Independent low noise makes the unused Z axis distinguishable.
        pcm=np.column_stack([signal,signal*np.cos(a),signal*np.sin(a),rng.normal(size=4800)*.01])
        samples[angle]=pcm
        value,confidence=intensity(pcm,dict(w=0,x=1,y=2,sx=1,sy=1))
        assert abs(delta(value,angle))<.01 and confidence>.9
    result=fit_axes(samples)
    assert result['mean_error_deg']<.01 and not result['rotation_verified']

def test_silent_calibration_rejected():
    with pytest.raises(ValueError):fit_axes({a:np.zeros((4800,4)) for a in (0,90,180,270)})

def test_recording_preserves_source_and_orders_timeline(tmp_path):
    r=Recorder(tmp_path);name=r.start({'camera':'test'})
    pcm=np.ones((100,2),np.float32)
    r.write('audio',pcm,{'timestamp':2,'rate':48000,'source':'camera'})
    r.write('frame',b'jpeg',{'timestamp':1});r.stop()
    folder=safe_session(tmp_path,name);rows=load_timeline(folder)
    assert [x['timestamp'] for x in rows]==[1,2]
    assert np.array_equal(np.load(folder/rows[1]['file']),pcm)
    assert rows[1]['source']=='camera'
    with pytest.raises(ValueError):safe_session(tmp_path,'../escape')

def test_replay_path_traversal_rejected(tmp_path):
    (tmp_path/'timeline.jsonl').write_text(json.dumps({'timestamp':0,'file':'../outside.jpg'}))
    with pytest.raises(ValueError):load_timeline(tmp_path)

import asyncio
import pytest
from server.runtime import Runtime

def test_backpressure_clears_audio_window_and_signals_gap():
    r=Runtime();r.raw_queue=asyncio.Queue(maxsize=1)
    r.raw_queue.put_nowait(({},b'old',1))
    header={};r.enqueue(r.raw_queue,(header,b'new',1))
    assert r.drops==1 and r.raw_queue.qsize()==1 and header['discontinuity']

def test_no_simulated_source_fallback():
    r=Runtime();assert r.mode=='idle'
    assert 'simulation' not in r.config

def test_invalid_source_rejected_without_mutation():
    r=Runtime()
    with pytest.raises(ValueError):asyncio.run(r.start('invalid'))
    assert r.mode=='idle'

def test_calibration_rejects_stereo():
    r=Runtime();r.mode='live';r.audio_source='camera';r.channels=2
    with pytest.raises(ValueError):asyncio.run(r.calibrate(0))

import pytest
from server.domain import Fusion, DirectionFilter, delta, sector

def target(label='car',angle=225,ts=10,id=1):
    return dict(label=label,angle=angle,timestamp=ts,track_id=id,approaching=True)

def test_circular_smoothing_and_hysteresis():
    f=DirectionFilter();f.update(359,0);angle,s=f.update(1,.1)
    assert abs(delta(angle,0))<1 and s==0
    assert f.update(35,1)[1]==0
    assert f.update(40,2)[1]==1
    assert f.update(25,3)[1]==1
    assert f.update(5,4)[1]==0

@pytest.mark.parametrize('angle,expected',[(0,0),(90,2),(180,4),(270,6),(359,0)])
def test_cardinal_sectors(angle,expected):assert sector(angle)==expected

def test_unknown_audio_direction_is_not_invented():
    f=Fusion()
    e=f.observe('horn',.8,10,[],'microphone')
    assert e.angle is None and e.evidence=='audio_only'
    e=f.observe('horn',.8,10,[target(),target(angle=90,id=2)],'microphone')
    assert e.angle is None
    e=f.observe('horn',.8,10,[target(label='person')],'microphone')
    assert e.angle is None

def test_visual_candidate_requires_unique_recent_class_match():
    f=Fusion();e=f.observe('horn',.8,10,[target()],'camera')
    assert e.evidence=='visual_candidate' and e.angle==pytest.approx(225)
    e=f.observe('horn',.8,11,[target()],'camera')
    assert e.angle is None

def test_audio_direction_association_wraps_at_north():
    f=Fusion();e=f.observe('horn',.9,10,[target(angle=2)],'camera',358,.8)
    assert e.evidence=='audio_visual'
    e=f.observe('horn',.9,10,[target(angle=80)],'camera',358,.8)
    assert e.evidence=='audio_direction'

def test_priority_expiry_and_history():
    f=Fusion();f.observe('speech',.8,10,[],'camera')
    f.observe('horn',.8,10.1,[],'camera')
    active,history=f.snapshot(10.2)
    assert len(active)==1 and active[0]['category']=='horn'
    assert len(history)==2
    assert f.snapshot(11.4)[0]==[]
    f.clear();assert f.snapshot(11.4)[0]==[]

def test_expired_events_get_new_ids():
    f=Fusion();a=f.observe('horn',.8,1,[],'camera');b=f.observe('horn',.9,1.2,[],'camera')
    assert a.id==b.id and b.expires_at==2.4
    c=f.observe('horn',.9,3,[],'camera');assert c.id!=a.id

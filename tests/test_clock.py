from server.clock import CameraClock

def test_sdk_millisecond_quirk_is_measured():
    c=CameraClock();c.align('aac',1000,10)
    assert c.align('aac',1600,10.6)==10.6
    assert c.diagnostics['aac']['unit']=='milliseconds'

def test_microseconds_and_shared_offset():
    c=CameraClock();c.align('aac',1000000,10);c.align('aac',1600000,10.6)
    c.align('rgba',1600000,10.7)
    aligned=c.align('rgba',2200000,11.3)
    assert abs(aligned-11.2)<.001
    assert c.diagnostics['rgba']['unit']=='microseconds'

def test_camera_reset_drops_old_mapping():
    c=CameraClock();c.align('aac',1000,10);c.align('aac',1600,10.6)
    assert c.align('aac',10,20)==20
    assert c.units=={}

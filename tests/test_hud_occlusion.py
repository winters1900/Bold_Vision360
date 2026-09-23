from scripts.hud_occlusion_check import clip_box, covered_area


def test_overlap_is_counted_once_in_hud_coverage_measurement():
    assert covered_area([(0, 0, 2, 2), (1, 1, 3, 3)]) == 7
    assert covered_area([]) == 0
    assert clip_box({"x": 0, "y": 0, "width": 2, "height": 2}, (1, 1, 3, 3)) == (
        1,
        1,
        2,
        2,
    )

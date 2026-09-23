import csv
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.evaluate import ANGLES, CATEGORIES, CONDITIONS, FIELDS, REPETITIONS, summarize
from scripts.field_trials import (
    TrialError,
    _exclusive_sheet,
    _read_sheet,
    next_trial,
    record_negative,
    record_trial,
)


def sheet(tmp_path):
    path = tmp_path / "field-trials.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        planned = (
            (condition, category, angle, repetition)
            for condition in CONDITIONS
            for category in CATEGORIES
            for angle in ANGLES
            for repetition in REPETITIONS
        )
        for trial, (condition, category, angle, repetition) in enumerate(planned, 1):
            writer.writerow(
                dict(
                    trial=trial,
                    condition=condition,
                    category=category,
                    angle_deg=angle,
                    repetition=repetition,
                    observed=0,
                )
            )
        writer.writerow(
            dict(trial="negative-10min", condition="quiet", category="negative", observed=0)
        )
    return path


def test_resume_recorded_detection_miss_and_negative_without_invented_results(tmp_path, capsys):
    path = sheet(tmp_path)
    assert next_trial(path)["trial"] == "1"
    record_trial(path, 1, 1, None, 12500, 13250, "external video A", "clear horn")
    record_trial(path, 2, 0, None, 24000, None, None, "no HUD event")
    record_negative(path, "negative-10min", 10, 0, "quiet indoor")
    record_negative(path, "negative-session-2", 2.5, 1, "second period")
    assert next_trial(path)["trial"] == "3"
    rows = _read_sheet(path)
    assert rows[0]["predicted_angle_deg"] == ""
    assert rows[0]["notes"] == "clock_source=external video A; clear horn"
    assert rows[1]["detected"] == "0" and rows[1]["hud_ms"] == ""
    assert rows[2]["observed"] == "0"
    summary = summarize(rows)
    assert summary["measured_positive_trials"] == 2
    assert summary["recall"] == 0.5
    assert summary["direction_unknown_trials"] == 2
    assert summary["alert_latency_p95_ms"] == 750
    assert summary["negative_minutes"] == 12.5
    assert summary["false_positives_per_5_minutes"] == 0.4
    assert summary["status"] == "not_fully_measured"
    assert "2/240 recorded" in capsys.readouterr().out


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(trial=0, detected=1, predicted_angle=0, onset=0, hud=1, clock_source="video"),
        dict(trial=1, detected=2, predicted_angle=0, onset=0, hud=1, clock_source="video"),
        dict(trial=1, detected=1, predicted_angle=361, onset=0, hud=1, clock_source="video"),
        dict(
            trial=1, detected=1, predicted_angle=float("nan"), onset=0, hud=1, clock_source="video"
        ),
        dict(trial=1, detected=1, predicted_angle=None, onset=10, hud=9, clock_source="video"),
        dict(trial=1, detected=1, predicted_angle=None, onset=0, hud=None, clock_source="video"),
        dict(trial=1, detected=1, predicted_angle=None, onset=0, hud=1, clock_source=None),
        dict(trial=1, detected=0, predicted_angle=20, onset=0, hud=None, clock_source=None),
        dict(trial=1, detected=0, predicted_angle=None, onset=0, hud=1, clock_source=None),
    ],
)
def test_invalid_positive_result_never_changes_sheet(tmp_path, kwargs):
    path = sheet(tmp_path)
    before = path.read_bytes()
    with pytest.raises(TrialError):
        record_trial(path, **kwargs, notes="")
    assert path.read_bytes() == before


def test_duplicate_positive_and_negative_results_are_rejected(tmp_path):
    path = sheet(tmp_path)
    record_trial(path, 1, 1, 360, 100, 200, "video", "")
    before = path.read_bytes()
    with pytest.raises(TrialError, match="already recorded"):
        record_trial(path, 1, 0, None, None, None, None, "")
    assert path.read_bytes() == before
    record_negative(path, "negative-10min", 10, 0, "")
    before = path.read_bytes()
    with pytest.raises(TrialError, match="already recorded"):
        record_negative(path, "negative-10min", 10, 0, "")
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "session_id,minutes,count",
    [
        ("bad-id", 10, 0),
        ("negative-二", 10, 0),
        ("negative-x", 0, 0),
        ("negative-x", float("inf"), 0),
        ("negative-x", 10, -1),
    ],
)
def test_invalid_negative_result_never_changes_sheet(tmp_path, session_id, minutes, count):
    path = sheet(tmp_path)
    before = path.read_bytes()
    with pytest.raises(TrialError):
        record_negative(path, session_id, minutes, count, "")
    assert path.read_bytes() == before


def test_duplicate_planned_key_is_rejected_before_any_write(tmp_path):
    path = sheet(tmp_path)
    rows = _read_sheet(path)
    rows[1]["angle_deg"] = rows[0]["angle_deg"]
    rows[1]["repetition"] = rows[0]["repetition"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    before = path.read_bytes()
    with pytest.raises(TrialError, match="missing, duplicate, or unexpected"):
        record_trial(path, 1, 0, None, None, None, None, "")
    assert path.read_bytes() == before


def test_swapped_planned_ids_are_rejected_before_any_write(tmp_path):
    path = sheet(tmp_path)
    rows = _read_sheet(path)
    rows[0]["trial"], rows[1]["trial"] = rows[1]["trial"], rows[0]["trial"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    before = path.read_bytes()
    with pytest.raises(TrialError, match="no longer matches"):
        record_trial(path, 1, 0, None, None, None, None, "")
    assert path.read_bytes() == before


def test_interrupted_replace_keeps_original_and_releases_lock(tmp_path, monkeypatch):
    path = sheet(tmp_path)
    before = path.read_bytes()

    def interrupted(*_args):
        raise OSError("simulated interruption")

    monkeypatch.setattr("scripts.field_trials.os.replace", interrupted)
    with pytest.raises(OSError, match="simulated interruption"):
        record_trial(path, 1, 0, None, None, None, None, "")
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".field-trials-*.csv"))
    with _exclusive_sheet(path):
        pass


def test_second_writer_is_rejected(tmp_path):
    path = sheet(tmp_path)
    with _exclusive_sheet(path):
        with pytest.raises(TrialError, match="Another writer"):
            with _exclusive_sheet(path):
                pass


def test_cli_runs_as_a_script_without_mutating_template(tmp_path):
    path = sheet(tmp_path)
    program = Path(__file__).resolve().parents[1] / "scripts" / "field_trials.py"
    before = path.read_bytes()
    result = subprocess.run(
        [sys.executable, str(program), "--input", str(path), "next"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Next: trial 1" in result.stdout
    assert path.read_bytes() == before

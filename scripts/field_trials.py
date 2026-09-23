"""Record real field trials in the existing 240-trial worksheet."""

import argparse
import csv
import math
import msvcrt
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

if __package__:
    from .evaluate import (
        ANGLES,
        CATEGORIES,
        CONDITIONS,
        EXPECTED,
        FIELDS,
        REPETITIONS,
        nonnegative_integer,
        planned_key,
        summarize,
    )
else:
    from evaluate import (
        ANGLES,
        CATEGORIES,
        CONDITIONS,
        EXPECTED,
        FIELDS,
        REPETITIONS,
        nonnegative_integer,
        planned_key,
        summarize,
    )

DEFAULT_SHEET = Path("reports/field-trials.csv")
PLANNED_BY_ID = {
    index: (condition, category, angle, repetition)
    for index, (condition, category, angle, repetition) in enumerate(
        (
            (condition, category, angle, repetition)
            for condition in CONDITIONS
            for category in CATEGORIES
            for angle in ANGLES
            for repetition in REPETITIONS
        ),
        1,
    )
}


class TrialError(ValueError):
    pass


def _finite_nonnegative(value, name, *, positive=False):
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise TrialError(f"{name} must be a finite nonnegative number") from exc
    if not math.isfinite(parsed) or parsed < 0 or (positive and parsed == 0):
        raise TrialError(
            f"{name} must be a finite {'positive' if positive else 'nonnegative'} number"
        )
    return parsed


def _read_sheet(path):
    if not path.is_file():
        raise TrialError(
            f"Worksheet not found: {path}. Generate it with scripts/evaluate.py --template"
        )
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise TrialError("Worksheet columns do not match reports/field-trials.csv template")
        rows = list(reader)
    positive = [row for row in rows if row["category"] != "negative"]
    if len(positive) != len(EXPECTED):
        raise TrialError("Worksheet must contain exactly the 240 planned positive trials")
    keys = [planned_key(row) for row in positive]
    if set(keys) != EXPECTED or len(set(keys)) != len(keys):
        raise TrialError("Worksheet has a missing, duplicate, or unexpected planned trial")
    ids = [row["trial"] for row in rows]
    if len(ids) != len(set(ids)) or not all(ids):
        raise TrialError("Worksheet has duplicate or blank trial IDs")
    if any(
        planned_key(row) != PLANNED_BY_ID.get(nonnegative_integer(row["trial"])) for row in positive
    ):
        raise TrialError("A planned trial ID no longer matches its original condition and angle")
    for row in rows:
        if row["observed"] not in ("0", "1"):
            raise TrialError(f"Trial {row['trial']} has an invalid observed value")
        if row["category"] == "negative" and row["condition"] != "quiet":
            raise TrialError("Negative rows must use the quiet condition for this worksheet")
    return rows


@contextmanager
def _exclusive_sheet(path):
    # OS locks release automatically after a crash, so a stale lock file does not block recovery.
    lock = path.with_name(path.name + ".lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            locked = True
        except OSError as exc:
            raise TrialError(f"Another writer holds {lock}; retry after it finishes") from exc
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, str(os.getpid()).encode("ascii"))
        yield
    finally:
        if locked:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        os.close(fd)


def _save_sheet(path, rows):
    # Same-directory replace keeps the old worksheet intact if writing is interrupted.
    fd, temporary = tempfile.mkstemp(prefix=".field-trials-", suffix=".csv", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def next_trial(path):
    rows = _read_sheet(path)
    remaining = sorted(
        (r for r in rows if r["category"] != "negative" and r["observed"] == "0"),
        key=lambda row: int(row["trial"]),
    )
    progress = 240 - len(remaining)
    if remaining:
        row = remaining[0]
        print(
            f"Next: trial {row['trial']} | {row['condition']} | {row['category']} | "
            f"{row['angle_deg']}° | repetition {row['repetition']} ({progress}/240 recorded)"
        )
    else:
        print("All 240 positive trials have been recorded")
    result = summarize(rows)
    print(
        f"Quiet negative: {result['negative_minutes']:g}/10 minutes recorded; "
        f"status={result['status']}"
    )
    return remaining[0] if remaining else None


def record_trial(path, trial, detected, predicted_angle, onset, hud, clock_source, notes):
    if trial not in range(1, 241):
        raise TrialError("--trial must be an integer from 1 to 240")
    if detected not in (0, 1):
        raise TrialError("--detected must be 0 or 1")
    if detected:
        if onset is None or hud is None:
            raise TrialError("Detected trials require both --onset-ms and --hud-ms")
        onset_value = _finite_nonnegative(onset, "--onset-ms")
        hud_value = _finite_nonnegative(hud, "--hud-ms")
        if hud_value < onset_value:
            raise TrialError("--hud-ms must be at or after --onset-ms on the same clock")
        if not clock_source or not clock_source.strip():
            raise TrialError("Detected trials require --clock-source for the shared external clock")
        angle = None
        if predicted_angle is not None:
            angle = _finite_nonnegative(predicted_angle, "--predicted-angle")
            if angle > 360:
                raise TrialError("--predicted-angle must be between 0 and 360 degrees")
    else:
        if predicted_angle is not None or hud is not None or clock_source is not None:
            raise TrialError(
                "Missed trials cannot have a predicted angle, HUD time, or clock source"
            )
        onset_value = _finite_nonnegative(onset, "--onset-ms") if onset is not None else None
        hud_value = None
        angle = None
    with _exclusive_sheet(path):
        rows = _read_sheet(path)
        row = next(r for r in rows if r["trial"] == str(trial))
        if row["observed"] == "1":
            raise TrialError(f"Trial {trial} is already recorded; refusing to overwrite it")
        row.update(
            observed="1",
            detected=str(detected),
            predicted_angle_deg="" if angle is None else str(angle),
            onset_ms="" if onset_value is None else str(onset_value),
            hud_ms="" if hud_value is None else str(hud_value),
            notes=(f"clock_source={clock_source.strip()}; " if detected else "") + (notes or ""),
        )
        _save_sheet(path, rows)
    print(f"Recorded trial {trial}: {'detected' if detected else 'missed'}")


def record_negative(path, session_id, minutes, false_positives, notes):
    if not session_id or not session_id.startswith("negative-") or session_id == "negative-":
        raise TrialError("--session-id must start with 'negative-' and include a unique suffix")
    if not session_id.isascii() or any(c.isspace() or c in ",\r\n" for c in session_id):
        raise TrialError("--session-id must be ASCII without spaces or commas")
    duration = _finite_nonnegative(minutes, "--minutes", positive=True)
    count = nonnegative_integer(false_positives)
    if count is None:
        raise TrialError("--false-positives must be a nonnegative integer")
    with _exclusive_sheet(path):
        rows = _read_sheet(path)
        existing = next((r for r in rows if r["trial"] == session_id), None)
        if existing is not None and existing["observed"] == "1":
            raise TrialError(f"Negative session {session_id} is already recorded")
        if existing is None:
            existing = dict.fromkeys(FIELDS, "")
            existing.update(trial=session_id, condition="quiet", category="negative", observed="0")
            rows.append(existing)
        elif existing["category"] != "negative":
            raise TrialError(f"Trial ID {session_id} is not a negative session")
        existing.update(
            observed="1",
            negative_minutes=str(duration),
            false_positive_count=str(count),
            notes=notes or "",
        )
        _save_sheet(path, rows)
    print(
        f"Recorded quiet negative session {session_id}: {duration:g} min, {count} false positives"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_SHEET)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "next", help="Show the next unrecorded positive trial and quiet-negative progress"
    )
    record = sub.add_parser("record", help="Record one measured positive trial")
    record.add_argument("--trial", type=int, required=True)
    record.add_argument("--detected", type=int, choices=(0, 1), required=True)
    record.add_argument("--predicted-angle", type=float)
    record.add_argument("--onset-ms", type=float)
    record.add_argument("--hud-ms", type=float)
    record.add_argument("--clock-source", help="One external clock used for both timestamps")
    record.add_argument("--notes", default="")
    negative = sub.add_parser("negative", help="Record one quiet negative sample period")
    negative.add_argument("--session-id", required=True)
    negative.add_argument("--minutes", type=float, required=True)
    negative.add_argument("--false-positives", type=int, required=True)
    negative.add_argument("--notes", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "next":
            next_trial(args.input)
        elif args.command == "record":
            record_trial(
                args.input,
                args.trial,
                args.detected,
                args.predicted_angle,
                args.onset_ms,
                args.hud_ms,
                args.clock_source,
                args.notes,
            )
        else:
            record_negative(
                args.input,
                args.session_id,
                args.minutes,
                args.false_positives,
                args.notes,
            )
    except TrialError as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()

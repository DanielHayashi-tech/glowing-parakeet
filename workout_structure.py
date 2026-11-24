"""What the athlete actually did inside a run: laps, repetitions, recoveries, and progressions.

Two kinds of structure, never mixed up:

  garmin   Garmin defined it. The run came from a structured workout (it has a workout name or
           plan, or its laps carry warm-up / cool-down / recovery / rest labels). Reps and
           recoveries are read straight from Garmin's lap intensity labels.
  inferred Corre Cortes worked it out from the numbers because the athlete pressed the lap button
           or the splits show a pattern. Every inferred result says so, lists its evidence, and is
           only produced when the evidence is clear. If it is not, the answer is "unclear", not a guess.

Ordinary runs are 1-mile auto laps that Garmin labels "interval" with trigger "distance"; that label
is a default, not evidence of a workout, so it is ignored unless a Garmin workout is present.

Lap distances and paces come from the device's raw measurements. Where those do not add up to
Garmin's session distance (treadmill calibration) the result is flagged, never silently corrected.
"""

import math
from statistics import median

METERS_PER_MILE = 1609.344
FEET_PER_METER = 3.28084

# Garmin-defined: lap labels that only exist because a workout defined the structure.
STRUCTURE_LABELS = {"warmup", "cooldown", "recovery", "rest"}
GARMIN_ROLES = {"interval": "rep", "rest": "recovery", "recovery": "recovery", "warmup": "warmup",
                "cooldown": "cooldown", "active": "rep", "other": "other"}
# Garmin's own split summary (from its activity data) counts segments by these types.
GARMIN_SPLIT_TYPES = {"INTERVAL_ACTIVE": "rep", "INTERVAL_RECOVERY": "recovery", "INTERVAL_REST": "recovery",
                      "INTERVAL_WARMUP": "warmup", "INTERVAL_COOLDOWN": "cooldown"}

# Inference thresholds (explicit so the result can be explained and tested).
MIN_PACE_LAP_METERS = 40            # shorter laps have no meaningful pace
MIN_MANUAL_LAPS = 6                 # a block of consecutive manual laps this long, to consider intervals
MIN_REPS = 3
MIN_FAST_SLOW_GAP = 60              # seconds per mile between the rep pace and the recovery pace
REP_PACE_TOLERANCE = 25             # reps must be within this many s/mi of the typical rep pace
RECOVERY_SLOWER_THAN_REPS = 45      # a recovery lap is at least this much slower than the reps
RECOVERY_BETWEEN_REPS_SHARE = 0.7   # share of rep-to-rep gaps that must contain a recovery lap
SHORT_REP_SECONDS = 30              # heart rate lags this long after a rep starts, so it is not meaningful
PROGRESSION_SECONDS = 20            # last third faster (progression) or slower (fade) than first third
MIN_MILE_SPLITS = 5
MILE_LAP_RANGE = (0.95, 1.05)       # a distance-triggered lap this long counts as a mile split
LONG_RUN_FOR_SUMMARY_MILES = 6
PAUSE_GAP_SECONDS = 10              # a gap this long between records means the timer was paused


# ---------- formatting ----------

def mmss(seconds):
    if seconds is None:
        return None
    seconds = round(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def pace_seconds(distance_m, duration_s):
    """Seconds per mile, or None when the lap is too short to give an honest pace."""
    if not distance_m or not duration_s or distance_m < MIN_PACE_LAP_METERS:
        return None
    return duration_s / (distance_m / METERS_PER_MILE)


def miles(distance_m):
    return None if distance_m is None else round(distance_m / METERS_PER_MILE, 2)


def round_or_none(value, digits=0):
    return None if value is None else round(value, digits)


# ---------- laps ----------

def prepare_laps(rows):
    """Lap dicts from database rows, sorted, with pace computed. Original Garmin values are kept."""
    laps = []
    for row in sorted(rows, key=lambda r: r["lap_index"]):
        spm = pace_seconds(row["distance_m"], row["duration_seconds"])
        laps.append({
            "n": row["lap_index"],
            "intensity": row.get("intensity"),
            "trigger": row.get("lap_trigger"),
            "distance_m": row["distance_m"],
            "duration_s": row["duration_seconds"],
            "pace_s": spm,
            "avg_hr": row.get("avg_heart_rate_bpm"),
            "max_hr": row.get("max_heart_rate_bpm"),
            "role": None,
            "role_source": None,
        })
    return laps


def is_garmin_defined(activity, laps):
    if activity.get("workout_name") or activity.get("workout_description"):
        return True
    return any(lap["intensity"] in STRUCTURE_LABELS for lap in laps)


def weighted_pace(laps):
    distance = sum(l["distance_m"] or 0 for l in laps)
    duration = sum(l["duration_s"] or 0 for l in laps)
    return pace_seconds(distance, duration)


def weighted_hr(laps):
    pairs = [(l["avg_hr"], l["duration_s"]) for l in laps if l["avg_hr"] and l["duration_s"]]
    return round(sum(h * s for h, s in pairs) / sum(s for _, s in pairs)) if pairs else None


def segment_view(segment):
    return {
        "segment": segment["segment"],
        "garmin_intensity": segment["intensity"],
        "role": segment["role"],
        "laps": segment["lap_numbers"],
        "miles": miles(segment["distance_m"]),
        "time": mmss(segment["duration_s"]),
        "pace": mmss(segment["pace_s"]),
        "avg_hr": round_or_none(segment["avg_hr"]),
        "max_hr": round_or_none(segment["max_hr"]),
    }


def lap_view(lap):
    """One lap as returned to the client."""
    view = {
        "n": lap["n"],
        "garmin_intensity": lap["intensity"],
        "trigger": lap["trigger"],
        "role": lap["role"],
        "role_source": lap["role_source"],
        "miles": miles(lap["distance_m"]),
        "time": mmss(lap["duration_s"]),
        "pace": mmss(lap["pace_s"]),
        "avg_hr": round_or_none(lap["avg_hr"]),
        "max_hr": round_or_none(lap["max_hr"]),
    }
    if "segment" in lap:
        view["segment"] = lap["segment"]
    return view


# ---------- Garmin's own split summary: an independent count to compare with ----------

def garmin_split_counts(payload):
    """{'rep': n, 'recovery': n, 'warmup': n, 'cooldown': n} from Garmin's splitSummaries, or None."""
    summaries = (payload or {}).get("splitSummaries") or []
    counts = {}
    for entry in summaries:
        role = GARMIN_SPLIT_TYPES.get(entry.get("splitType"))
        if role:
            counts[role] = counts.get(role, 0) + (entry.get("noOfSplits") or 0)
    return counts or None


def split_summary_note(counts, reps, recoveries):
    """Evidence line comparing our segment counts with Garmin's, only when it says something."""
    if not counts or not (counts.get("recovery") or counts.get("warmup") or counts.get("cooldown")):
        return None            # plain runs report every mile as an "active" split; that says nothing about structure
    garmin_reps, garmin_recoveries = counts.get("rep", 0), counts.get("recovery", 0)
    if garmin_reps == reps and garmin_recoveries == recoveries:
        return f"Garmin's own split summary agrees: {garmin_reps} interval and {garmin_recoveries} recovery splits"
    return f"Garmin's own split summary reports {garmin_reps} interval and {garmin_recoveries} recovery splits (we found {reps} and {recoveries})"


# ---------- Garmin-defined workouts ----------

def describe_reps(reps):
    if not reps:
        return None
    paces = [r["pace_s"] for r in reps if r["pace_s"]]
    durations = [r["duration_s"] for r in reps if r["duration_s"]]
    distances = [r["distance_m"] for r in reps if r["distance_m"]]
    return {
        "count": len(reps),
        "avg_time": mmss(sum(durations) / len(durations)) if durations else None,
        "avg_miles": round(sum(distances) / len(distances) / METERS_PER_MILE, 2) if distances else None,
        "pace_range": None if not paces else [mmss(min(paces)), mmss(max(paces))],
        "avg_pace": mmss(weighted_pace(reps)),
        "avg_hr": weighted_hr(reps),
        "hr_range": _range([r["avg_hr"] for r in reps if r["avg_hr"]]),
    }


def _range(values):
    return None if not values else [round(min(values)), round(max(values))]


def merge_segments(laps):
    """Consecutive laps with the same Garmin label are one segment, as Garmin counts them.

    A single interval can cross an auto-lap boundary and show up as several laps; counting laps
    would turn one long rep into several. Garmin's own split summaries count segments.
    """
    segments = []
    for lap in laps:
        if segments and segments[-1]["intensity"] == lap["intensity"]:
            segments[-1]["laps"].append(lap)
        else:
            segments.append({"intensity": lap["intensity"], "laps": [lap]})
    result = []
    for number, segment in enumerate(segments, start=1):
        members = segment["laps"]
        hr_values = [l["max_hr"] for l in members if l["max_hr"]]
        distance = sum(l["distance_m"] or 0 for l in members)
        duration = sum(l["duration_s"] or 0 for l in members)
        merged = {
            "segment": number,
            "intensity": segment["intensity"],
            "role": members[0]["role"] if members[0]["role"] else GARMIN_ROLES.get(segment["intensity"], "unlabeled"),
            "lap_numbers": [l["n"] for l in members],
            "distance_m": distance or None,
            "duration_s": duration or None,
            "pace_s": pace_seconds(distance, duration),
            "avg_hr": weighted_hr(members),
            "max_hr": max(hr_values) if hr_values else None,
        }
        for lap in members:
            lap["segment"] = number
        result.append(merged)
    return result


def garmin_structure(activity, laps, garmin_splits=None):
    for lap in laps:
        lap["role"] = GARMIN_ROLES.get(lap["intensity"], "unlabeled")
        # the leftover bit of lap the watch closes at the end of the activity is not a repetition
        if lap["role"] == "rep" and lap["trigger"] == "session_end" and (lap["distance_m"] or 0) < 0.1 * METERS_PER_MILE:
            lap["role"] = "other"
        lap["role_source"] = "garmin"
    segments = merge_segments(laps)
    reps = [s for s in segments if s["role"] == "rep"]
    recoveries = [s for s in segments if s["role"] == "recovery"]
    warmup = sum(s["duration_s"] or 0 for s in segments if s["role"] == "warmup")
    cooldown = sum(s["duration_s"] or 0 for s in segments if s["role"] == "cooldown")
    name = activity.get("workout_name")
    plan = activity.get("workout_description")
    stats = describe_reps(reps)

    head = f"Garmin workout '{name}'" if name else "Garmin-labeled workout"
    if plan:
        head += f" ({plan})"
    parts = [head]
    if stats:
        rep_text = f"{stats['count']} reps"
        if stats["avg_time"]:
            rep_text += f" of ~{stats['avg_time']}"
        if stats["avg_miles"]:
            rep_text += f" ({stats['avg_miles']} mi)"
        if stats["pace_range"]:
            low, high = stats["pace_range"]
            rep_text += f" at {low}/mi" if low == high else f" at {low}-{high}/mi"
        parts.append(rep_text)
    else:
        parts.append("no repetition laps labeled")
    if recoveries:
        times = [r["duration_s"] for r in recoveries if r["duration_s"]]
        parts.append(f"{len(recoveries)} recoveries/rests ({mmss(min(times))}-{mmss(max(times))} each)" if times else f"{len(recoveries)} recoveries/rests")
    if warmup:
        parts.append(f"warm-up {mmss(warmup)}")
    if cooldown:
        parts.append(f"cool-down {mmss(cooldown)}")

    flags = []
    if stats and reps and all((r["duration_s"] or 0) < SHORT_REP_SECONDS for r in reps):
        flags.append("short_reps_heart_rate_not_meaningful")
    evidence = ["Garmin workout name or plan is in the file" if (name or plan) else "laps carry Garmin warm-up/cool-down/recovery/rest labels"]
    note = split_summary_note(garmin_splits, len(reps), len(recoveries))
    if note:
        evidence.append(note)
    return {
        "kind": "garmin_structured_workout",
        "source": "garmin",
        "summary": ", ".join(parts),
        "evidence": evidence,
        "reps": stats,
        "flags": flags,
        "segments": segments,
    }


# ---------- inferred: manual-lap intervals ----------

def consecutive_blocks(laps, trigger):
    blocks, current = [], []
    for lap in laps:
        if lap["trigger"] == trigger:
            current.append(lap)
        else:
            if current:
                blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def two_means(values):
    """1-D two-cluster centers (fast, slow). Plain k-means with the extremes as starting points."""
    low, high = min(values), max(values)
    for _ in range(25):
        near_low = [v for v in values if abs(v - low) <= abs(v - high)]
        near_high = [v for v in values if abs(v - low) > abs(v - high)]
        if not near_low or not near_high:
            break
        new_low, new_high = sum(near_low) / len(near_low), sum(near_high) / len(near_high)
        if (new_low, new_high) == (low, high):
            break
        low, high = new_low, new_high
    return low, high


def infer_manual_intervals(laps):
    """Reps and recoveries from manually pressed laps, or (None, reason) if the evidence is not clear."""
    manual = [b for b in consecutive_blocks(laps, "manual") if len(b) >= MIN_MANUAL_LAPS]
    if not manual:
        return None, None
    block = max(manual, key=len)
    paced = [l for l in block if l["pace_s"] and (l["distance_m"] or 0) >= MIN_PACE_LAP_METERS * 2]
    if len(paced) < MIN_MANUAL_LAPS:
        return None, f"{len(block)} manual laps but too few have a usable pace"
    fast_center, slow_center = two_means([l["pace_s"] for l in paced])
    if slow_center - fast_center < MIN_FAST_SLOW_GAP:
        return None, f"{len(block)} manual laps but fast and slow laps differ by only {round(slow_center - fast_center)} s/mi (needs {MIN_FAST_SLOW_GAP})"
    fast_laps = [l for l in paced if abs(l["pace_s"] - fast_center) < abs(l["pace_s"] - slow_center)]
    typical = median(l["pace_s"] for l in fast_laps)
    reps = [l for l in fast_laps if abs(l["pace_s"] - typical) <= REP_PACE_TOLERANCE]
    if len(reps) < MIN_REPS:
        return None, f"only {len(reps)} laps near the fast pace (needs {MIN_REPS})"
    rep_numbers = {l["n"] for l in reps}
    first, last = min(rep_numbers), max(rep_numbers)
    between = [l for l in block if first < l["n"] < last and l["n"] not in rep_numbers]
    recoveries = [l for l in between if l["pace_s"] and l["pace_s"] >= typical + RECOVERY_SLOWER_THAN_REPS]
    ordered = sorted(reps, key=lambda l: l["n"])
    gaps_with_recovery = sum(
        1 for a, b in zip(ordered, ordered[1:]) if any(a["n"] < r["n"] < b["n"] for r in recoveries)
    )
    needed = math.ceil(RECOVERY_BETWEEN_REPS_SHARE * (len(reps) - 1))
    if gaps_with_recovery < needed:
        return None, f"{len(reps)} fast laps but only {gaps_with_recovery} of {len(reps) - 1} gaps have a slower recovery lap"
    evidence = [
        f"{len(block)} consecutive manually pressed laps",
        f"{len(reps)} laps within {REP_PACE_TOLERANCE} s/mi of {mmss(typical)}/mi",
        f"{len(recoveries)} slower recovery laps ({gaps_with_recovery} of {len(reps) - 1} gaps between reps)",
        f"fast and slow lap paces differ by {round(slow_center - fast_center)} s/mi",
    ]
    return {"reps": reps, "recoveries": recoveries, "block": block, "evidence": evidence, "typical": typical}, None


def repetition_list(laps, rep_numbers, recovery_numbers):
    """Each repetition with the recovery lap that follows it, as Garmin recorded the laps (inferred roles)."""
    by_number = {l["n"]: l for l in laps}
    result = []
    for number in sorted(rep_numbers):
        lap = lap_view(by_number[number])
        after = by_number.get(number + 1)
        recovery = lap_view(after) if after and after["n"] in recovery_numbers else None
        def brief(view):
            return {key: view[key] for key in ("n", "time", "miles", "pace", "avg_hr", "max_hr")}
        result.append({"rep": len(result) + 1, **brief(lap), "recovery_after": brief(recovery) if recovery else None})
    return result


def inferred_interval_structure(laps, found, garmin_splits=None):
    rep_numbers = {l["n"] for l in found["reps"]}
    recovery_numbers = {l["n"] for l in found["recoveries"]}
    first, last = min(rep_numbers), max(rep_numbers)
    for lap in laps:
        if lap["n"] in rep_numbers:
            lap["role"] = "rep"
        elif lap["n"] in recovery_numbers:
            lap["role"] = "recovery"
        elif lap["n"] < first:
            lap["role"] = "before_first_rep"
        elif lap["n"] > last:
            lap["role"] = "after_last_rep"
        else:
            lap["role"] = "other"
        lap["role_source"] = "inferred"
    reps = sorted(found["reps"], key=lambda l: l["n"])
    recoveries = sorted(found["recoveries"], key=lambda l: l["n"])
    stats = describe_reps(reps)
    rec_times = [r["duration_s"] for r in recoveries if r["duration_s"]]
    rec_paces = [r["pace_s"] for r in recoveries if r["pace_s"]]
    text = f"{stats['count']} x ~{stats['avg_time']} ({stats['avg_miles']} mi) at ~{stats['avg_pace']}/mi"
    if rec_times:
        text += f" with jogging recoveries (~{mmss(min(rec_times))}-{mmss(max(rec_times))}"
        text += f", {mmss(min(rec_paces))}-{mmss(max(rec_paces))}/mi)" if rec_paces else ")"
    text += " - inferred from manual laps, not a Garmin workout"
    flags = []
    if all((r["duration_s"] or 0) < SHORT_REP_SECONDS for r in reps):
        flags.append("short_reps_heart_rate_not_meaningful")
    evidence = list(found["evidence"])
    note = split_summary_note(garmin_splits, len(reps), len(recoveries))
    if note:
        evidence.append(note)
    return {
        "kind": "inferred_intervals",
        "source": "inferred",
        "summary": text,
        "evidence": evidence,
        "reps": stats,
        "repetitions": repetition_list(laps, rep_numbers, recovery_numbers),
        "flags": flags,
    }


# ---------- inferred: progression / fade / steady from mile splits ----------

def mile_laps(laps):
    low, high = MILE_LAP_RANGE
    return [l for l in laps if l["trigger"] == "distance" and l["distance_m"] and low <= l["distance_m"] / METERS_PER_MILE <= high and l["pace_s"]]


def split_pattern(laps, total_miles):
    splits = mile_laps(laps)
    if len(splits) < MIN_MILE_SPLITS:
        return None
    third = max(1, len(splits) // 3)
    first, final = splits[:third], splits[-third:]
    first_pace, last_pace = weighted_pace(first), weighted_pace(final)
    change = first_pace - last_pace            # positive = faster at the end
    first_hr, last_hr = weighted_hr(splits[:1]), weighted_hr(splits[-1:])   # same first and last mile as the pace text
    hr_text = f", HR {first_hr} -> {last_hr}" if first_hr and last_hr else ""
    for lap in laps:
        lap["role"] = "steady"
        lap["role_source"] = "inferred"
    paces = [s["pace_s"] for s in splits]
    if change >= PROGRESSION_SECONDS:
        kind, label = "progression_run", f"Progression run: miles {mmss(splits[0]["pace_s"])} -> {mmss(splits[-1]["pace_s"])}/mi over {len(splits)} mile splits{hr_text}"
    elif change <= -PROGRESSION_SECONDS:
        kind, label = "fade_run", f"Slowed late: miles {mmss(splits[0]["pace_s"])} -> {mmss(splits[-1]["pace_s"])}/mi over {len(splits)} mile splits{hr_text}"
    else:
        kind, label = "steady_run", f"Even pace: mile splits {mmss(min(paces))}-{mmss(max(paces))}/mi{hr_text}"
    return {
        "kind": kind,
        "source": "inferred",
        "summary": label + " - inferred from mile splits",
        "evidence": [f"{len(splits)} distance-triggered mile laps", f"first third {mmss(first_pace)}/mi vs last third {mmss(last_pace)}/mi"],
        "reps": None,
        "flags": [],
    }


# ---------- entry points ----------

def analyze(activity, lap_rows, garmin_splits=None):
    """Structure of one run. Returns {structure, laps}; roles are filled in on the laps.

    garmin_splits (optional) is Garmin's own split-summary counts, used only as a cross-check."""
    laps = prepare_laps(lap_rows)
    flags_common = []
    if activity.get("lap_distance_adjusted") == 1:
        flags_common.append("lap_distances_unreliable")
    if activity.get("sub_sport") == "treadmill":
        flags_common.append("treadmill")
    if not laps:
        return {"structure": {"kind": "no_lap_data", "source": None, "summary": None,
                              "evidence": ["no laps are stored for this activity"], "reps": None, "flags": flags_common}, "laps": laps}

    structure = None
    if is_garmin_defined(activity, laps):
        structure = garmin_structure(activity, laps, garmin_splits)
    else:
        found, reason = infer_manual_intervals(laps)
        if found:
            structure = inferred_interval_structure(laps, found, garmin_splits)
        else:
            structure = split_pattern(laps, (activity.get("distance_m") or 0) / METERS_PER_MILE)
            if structure is None:
                kind = "manual_laps_unclear" if reason else "plain_run"
                evidence = [reason] if reason else ["no workout labels, manual-lap pattern, or enough mile splits"]
                structure = {"kind": kind, "source": None, "summary": None, "evidence": evidence, "reps": None, "flags": []}
                note = split_summary_note(garmin_splits, 0, 0) if garmin_splits and (garmin_splits.get("recovery") or garmin_splits.get("warmup")) else None
                if note:
                    structure["evidence"].append(note.replace("(we found 0 and 0)", "(the laps do not show a clear pattern)"))
                for lap in laps:
                    lap["role"], lap["role_source"] = "unlabeled", None
    structure["flags"] = sorted(set(structure["flags"]) | set(flags_common))
    if "lap_distances_unreliable" in structure["flags"] and structure["summary"]:
        structure["summary"] += " (raw lap distances do not add up to the session distance: paces approximate)"
    return {"structure": structure, "laps": laps}


def compact_structure(structure, distance_m):
    """The short version for get_training_context: a summary only when there is something to say."""
    if structure["kind"] in ("garmin_structured_workout", "inferred_intervals", "progression_run", "fade_run"):
        return {"kind": structure["kind"], "source": structure["source"], "summary": structure["summary"]}
    if structure["kind"] == "steady_run" and (distance_m or 0) / METERS_PER_MILE >= LONG_RUN_FOR_SUMMARY_MILES:
        return {"kind": structure["kind"], "source": structure["source"], "summary": structure["summary"]}
    return {"kind": structure["kind"], "source": structure["source"], "summary": None}


# ---------- database access and the details tool ----------

LAP_QUERY = """
    SELECT lap_index, duration_seconds, distance_m, avg_heart_rate_bpm, max_heart_rate_bpm,
           intensity, lap_trigger
    FROM laps WHERE activity_id = ? ORDER BY lap_index
"""


def load_laps(connection, activity_id):
    return [dict(r) for r in connection.execute(LAP_QUERY, (activity_id,))]


def load_steps(connection, activity_id):
    return [dict(r) for r in connection.execute(
        "SELECT * FROM workout_steps WHERE activity_id = ? ORDER BY step_index", (activity_id,))]


def readable_plan(steps):
    """Garmin's planned steps as short lines (the plan, not what was executed)."""
    lines = []
    for step in steps:
        kind, value = step["duration_type"], step["duration_value"]
        if kind == "repeat_until_steps_complete":
            lines.append(f"repeat steps {int(step['repeat_from_step'])}-{step['step_index'] - 1} x{int(step['repeat_count'])}")
            continue
        if kind == "time" and value is not None:
            length = mmss(value / 1000)
        elif kind == "distance" and value is not None:
            length = f"{round(value / 100)} m"
        else:
            length = "open"
        text = f"{step['step_index']}: {step['intensity'] or 'step'} {length}"
        if step["target_type"] == "speed" and step["target_low"] and step["target_high"]:
            text += f" at {mmss(METERS_PER_MILE * 1000 / step['target_low'])}-{mmss(METERS_PER_MILE * 1000 / step['target_high'])}/mi"
        lines.append(text)
    return lines


def mile_splits_from_records(samples):
    """Mile splits computed from the per-second records, for runs whose laps are not mile laps.

    Time is timer time, like Garmin's laps: a gap of PAUSE_GAP_SECONDS or more between records is a
    paused timer and is not counted. Distance is the device's raw cumulative distance. Returns
    ([], 0) when there are too few records.
    """
    points = [s for s in samples if s["distance_m"] is not None and s["elapsed_seconds"] is not None]
    if len(points) < 10:
        return [], 0
    splits, mile, timer, paused, start_index = [], 1, 0.0, 0.0, 0
    for index in range(1, len(points)):
        gap = points[index]["elapsed_seconds"] - points[index - 1]["elapsed_seconds"]
        if gap >= PAUSE_GAP_SECONDS:
            paused += gap
        else:
            timer += gap
        if points[index]["distance_m"] >= mile * METERS_PER_MILE:
            hrs = [p["heart_rate_bpm"] for p in points[start_index:index + 1] if p["heart_rate_bpm"]]
            splits.append({"mile": mile, "pace": mmss(timer), "avg_hr": round(sum(hrs) / len(hrs)) if hrs else None})
            timer, start_index, mile = 0.0, index, mile + 1
    return splits, round(paused)


def load_garmin_splits(connection, garmin_activity_id):
    import json
    row = connection.execute("SELECT payload FROM garmin_activity_raw WHERE garmin_activity_id = ?", (garmin_activity_id,)).fetchone()
    if not row:
        return None
    try:
        return garmin_split_counts(json.loads(row[0]))
    except (TypeError, ValueError):
        return None


def build_details(connection, garmin_activity_id, summarize_activity):
    """The `get_workout_details` result for one Garmin activity ID, or None if we do not have it."""
    row = connection.execute("SELECT * FROM activities WHERE garmin_activity_id = ?", (garmin_activity_id,)).fetchone()
    if row is None:
        return None
    activity = dict(row)
    lap_rows = load_laps(connection, activity["id"])
    steps = load_steps(connection, activity["id"])
    is_run = activity["activity_type"] == "running"
    result = analyze(activity, lap_rows, load_garmin_splits(connection, garmin_activity_id)) if is_run else {"structure": None, "laps": prepare_laps(lap_rows)}
    laps = result["laps"]

    lap_sum_m = sum(l["distance_m"] or 0 for l in laps)
    session_m = activity["distance_m"]
    mile_like = laps and len(mile_laps(laps)) >= max(3, len(laps) - 3)
    details = {
        "activity": summarize_activity(activity),
        "structure": result["structure"],
        "garmin_workout": None if not (activity.get("workout_name") or activity.get("workout_description") or steps) else {
            "name": activity.get("workout_name"),
            "description": activity.get("workout_description"),
            "planned_steps": readable_plan(steps),
            "note": "The plan as Garmin recorded it; the laps below are what was actually run.",
        },
        "laps": [lap_view(l) for l in laps],
        "laps_are_mile_splits": bool(mile_like),
        "distance_check": {
            "session_distance_miles": miles(session_m),
            "fit_session_distance_miles": miles(activity.get("fit_distance_m")),
            "sum_of_lap_distances_miles": miles(lap_sum_m) if laps else None,
            "laps_match_session": None if not laps or not session_m else abs(lap_sum_m - (activity.get("fit_distance_m") or session_m)) <= max(25, 0.01 * session_m),
            "session_to_lap_distance_ratio": round(session_m / lap_sum_m, 3) if laps and session_m and lap_sum_m else None,
            "note": "Lap and split distances are the device's raw measurements. Garmin's session distance can differ (treadmill calibration or edits); both are kept.",
        },
        "heart_rate_zone_minutes": None if any(activity[f"hr_zone{z}_seconds"] is None for z in range(1, 6)) else
            {f"zone{z}": round(activity[f"hr_zone{z}_seconds"] / 60) for z in range(1, 6)},
        "missing": [],
    }
    segments = (result["structure"] or {}).get("segments")
    if segments:
        details["segments"] = {
            "source": "garmin",
            "note": "Consecutive laps with the same Garmin label grouped as one segment, the way Garmin counts them.",
            "list": [segment_view(s) for s in segments],
        }
    if not laps:
        details["missing"].append("No laps are stored for this activity.")
    if laps and not mile_like and is_run:
        samples = [dict(r) for r in connection.execute(
            "SELECT elapsed_seconds, distance_m, heart_rate_bpm FROM activity_samples WHERE activity_id = ? ORDER BY elapsed_seconds",
            (activity["id"],))]
        splits, paused = mile_splits_from_records(samples)
        details["mile_splits_from_records"] = {
            "source": "computed from the per-second records: timer time (paused time excluded) over the device's raw distance",
            "splits": splits,
            "paused_seconds_excluded": paused,
        }
    if is_run and laps and sum(1 for l in laps if l["avg_hr"] is None):
        details["missing"].append(f"{sum(1 for l in laps if l['avg_hr'] is None)} laps have no heart rate.")
    if not is_run:
        details["missing"].append("Repetition and progression analysis is only done for runs; the laps are Garmin's, as recorded.")
    return details

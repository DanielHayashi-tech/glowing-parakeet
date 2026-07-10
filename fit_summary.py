#!/usr/bin/env python3
"""
Garmin FIT parsing helpers and CLI summary output.

Usage:
    python fit_summary.py <activity.fit>

The parsing layer is intentionally reusable so other scripts can import the
canonical activity, lap, and sample objects for database ingestion.
"""

import argparse
import json
import struct
import sys
from math import isnan
from datetime import datetime, timedelta, timezone
from pathlib import Path

LACTATE_THRESHOLD_HR = 166
UTC_OFFSET_HOURS = -6

HR_ZONES = [
    (0, 130, "Z1 Easy      (<130 bpm)"),
    (130, 148, "Z2 Aerobic   (130-148 bpm)"),
    (148, 162, "Z3 Tempo     (148-162 bpm)"),
    (162, 172, "Z4 Threshold (162-172 bpm)"),
    (172, 999, "Z5 VO2max    (172+ bpm)"),
]

FIT_EPOCH = datetime(1989, 12, 31, 0, 0, 0, tzinfo=timezone.utc)

SESSION_MSG_NUM = 18
LAP_MSG_NUM = 19
RECORD_MSG_NUM = 20

FIELD_TIMESTAMP = 253
FIELD_POSITION_LAT = 0
FIELD_POSITION_LONG = 1
FIELD_ALTITUDE = 2
FIELD_HEART_RATE = 3
FIELD_CADENCE = 4
FIELD_DISTANCE = 5
FIELD_SPEED = 6
FIELD_ENHANCED_SPEED = 73
FIELD_POWER = 7
FIELD_TEMPERATURE = 13

FIELD_SESSION_SPORT = 5
FIELD_SESSION_SUB_SPORT = 6
FIELD_SESSION_TOTAL_TIMER_TIME = 8
FIELD_SESSION_TOTAL_DISTANCE = 9
FIELD_SESSION_TOTAL_CALORIES = 11
FIELD_SESSION_AVG_SPEED = 14
FIELD_SESSION_MAX_SPEED = 15
FIELD_SESSION_AVG_HEART_RATE = 16
FIELD_SESSION_MAX_HEART_RATE = 17
FIELD_SESSION_AVG_CADENCE = 18
FIELD_SESSION_MAX_CADENCE = 19
FIELD_SESSION_TOTAL_ASCENT = 22
FIELD_SESSION_TOTAL_DESCENT = 23
FIELD_SESSION_ENHANCED_AVG_SPEED = 124
FIELD_SESSION_ENHANCED_MAX_SPEED = 125

FIELD_LAP_TOTAL_TIMER_TIME = 8
FIELD_LAP_TOTAL_DISTANCE = 9
FIELD_LAP_AVG_HEART_RATE = 15
FIELD_LAP_MAX_HEART_RATE = 16
FIELD_LAP_AVG_CADENCE = 17
FIELD_LAP_START_TIME = 2
FIELD_LAP_ENHANCED_AVG_SPEED = 110
FIELD_LAP_ENHANCED_MAX_SPEED = 111

BASE_TYPES = {
    0x00: (1, "B"),
    0x01: (1, "b"),
    0x02: (1, "B"),
    0x07: (1, "s"),
    0x0A: (1, "B"),
    0x0D: (1, "B"),
    0x83: (2, "h"),
    0x84: (2, "H"),
    0x85: (4, "i"),
    0x86: (4, "I"),
    0x88: (4, "f"),
    0x89: (8, "d"),
    0x8B: (2, "H"),
    0x8C: (4, "I"),
    0x8E: (8, "q"),
    0x8F: (8, "Q"),
    0x90: (8, "Q"),
}

SPORT_MAP = {
    0: "generic",
    1: "running",
    2: "cycling",
    3: "transition",
    4: "fitness_equipment",
    5: "swimming",
    6: "basketball",
    7: "soccer",
    8: "tennis",
    9: "american_football",
    10: "training",
    11: "walking",
    12: "cross_country_skiing",
    13: "alpine_skiing",
    14: "snowboarding",
    15: "rowing",
    16: "mountaineering",
    17: "hiking",
    18: "multisport",
    19: "paddling",
}

SUB_SPORT_MAP = {
    0: "generic",
    1: "treadmill",
    2: "street",
    3: "trail",
    4: "track",
    5: "spin",
    6: "indoor_cycling",
    7: "road",
    8: "mountain",
    9: "downhill",
    10: "recumbent",
    11: "cyclocross",
    12: "hand_cycling",
    13: "track_cycling",
    14: "indoor_rowing",
    15: "elliptical",
    16: "stair_climbing",
    17: "lap_swimming",
    18: "open_water",
    19: "flexibility_training",
    20: "strength_training",
    21: "warm_up",
    22: "match",
    23: "exercise",
    24: "challenge",
    25: "indoor_skiing",
    26: "cardio_training",
    27: "indoor_walking",
    28: "e_bike_fitness",
    29: "bmx",
    30: "casual_walking",
    31: "speed_walking",
    32: "bike_to_run_transition",
    33: "run_to_bike_transition",
    34: "swim_to_bike_transition",
    35: "atv",
    36: "motocross",
    37: "backcountry",
    38: "resort",
    39: "rc_drone",
    40: "wingsuit",
    41: "whitewater",
    42: "skate_skiing",
    43: "yoga",
    44: "pilates",
    45: "indoor_running",
}


def parse_fit(filepath):
    with open(filepath, "rb") as file_handle:
        raw = file_handle.read()

    header_size = raw[0]
    data_end = header_size + struct.unpack("<I", raw[4:8])[0]
    pos = header_size

    local_defs = {}
    records, laps, sessions = [], [], []

    def decode_msg(definition, offset):
        message = {}
        for field in definition["fields"]:
            field_id = field["field_num"]
            field_size = field["size"]
            base_type = field["base_type"]
            value_bytes = raw[offset : offset + field_size]
            offset += field_size
            if base_type in BASE_TYPES:
                unit_size, fmt = BASE_TYPES[base_type]
                endian = "<" if definition["arch"] == 0 else ">"
                if fmt == "s":
                    message[field_id] = value_bytes.decode(
                        "utf-8", errors="ignore"
                    ).rstrip("\x00")
                elif field_size == unit_size:
                    message[field_id] = struct.unpack(endian + fmt, value_bytes)[0]
                elif field_size > unit_size:
                    count = field_size // unit_size
                    message[field_id] = list(
                        struct.unpack(endian + (fmt * count), value_bytes)
                    )
        for dev_field in definition["dev_fields"]:
            offset += dev_field["size"]
        return message, offset

    while pos < data_end - 1:
        record_header = raw[pos]
        pos += 1

        if record_header & 0x80:
            local_num = (record_header >> 5) & 0x03
            if local_num in local_defs:
                definition = local_defs[local_num]
                message, pos = decode_msg(definition, pos)
                global_num = definition["global_num"]
                if global_num == RECORD_MSG_NUM:
                    records.append(message)
                elif global_num == LAP_MSG_NUM:
                    laps.append(message)
            continue

        is_definition = bool(record_header & 0x40)
        has_dev_fields = bool(record_header & 0x20)
        local_num = record_header & 0x0F

        if is_definition:
            pos += 1
            architecture = raw[pos]
            pos += 1
            global_num = struct.unpack(
                "<H" if architecture == 0 else ">H", raw[pos : pos + 2]
            )[0]
            pos += 2
            field_count = raw[pos]
            pos += 1
            fields = []
            for _ in range(field_count):
                fields.append(
                    {
                        "field_num": raw[pos],
                        "size": raw[pos + 1],
                        "base_type": raw[pos + 2],
                    }
                )
                pos += 3
            dev_fields = []
            if has_dev_fields:
                dev_count = raw[pos]
                pos += 1
                for _ in range(dev_count):
                    dev_fields.append(
                        {
                            "field_num": raw[pos],
                            "size": raw[pos + 1],
                            "dev_idx": raw[pos + 2],
                        }
                    )
                    pos += 3
            local_defs[local_num] = {
                "global_num": global_num,
                "arch": architecture,
                "fields": fields,
                "dev_fields": dev_fields,
            }
        else:
            if local_num not in local_defs:
                break
            definition = local_defs[local_num]
            message, pos = decode_msg(definition, pos)
            global_num = definition["global_num"]
            if global_num == RECORD_MSG_NUM:
                records.append(message)
            elif global_num == LAP_MSG_NUM:
                laps.append(message)
            elif global_num == SESSION_MSG_NUM:
                sessions.append(message)

    return records, laps, sessions


def fit_seconds_to_datetime(value):
    if value is None:
        return None
    return FIT_EPOCH + timedelta(seconds=value)


def to_iso8601(value):
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def scale(value, divisor):
    if value is None:
        return None
    return value / divisor


def clean_number(value, invalid_values=None):
    if value is None:
        return None
    if isinstance(value, float) and isnan(value):
        return None
    if invalid_values and value in invalid_values:
        return None
    return value


def altitude_from_fit(value):
    value = clean_number(value)
    if value is None:
        return None
    return (value / 5) - 500


def cadence_to_spm(value):
    if value is None:
        return None
    return value * 2


def map_sport(value):
    if value is None:
        return None
    return SPORT_MAP.get(value, f"sport_{value}")


def map_sub_sport(value):
    if value is None:
        return None
    return SUB_SPORT_MAP.get(value, f"sub_sport_{value}")


def first_non_none(*values):
    for value in values:
        if value is not None:
            return value
    return None


def average(values):
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def max_value(values):
    present = [value for value in values if value is not None]
    if not present:
        return None
    return max(present)


def canonicalize_fit(filepath, athlete_timezone="America/Chicago"):
    records, laps, sessions = parse_fit(filepath)
    if not sessions:
        raise ValueError(f"No session data found in FIT file: {filepath}")

    session = sessions[0]
    start_dt = fit_seconds_to_datetime(session.get(FIELD_TIMESTAMP))
    duration_seconds = scale(session.get(FIELD_SESSION_TOTAL_TIMER_TIME), 1000)
    end_dt = (
        start_dt + timedelta(seconds=duration_seconds)
        if start_dt is not None and duration_seconds is not None
        else None
    )

    sample_rows = []
    heart_rates = []
    cadences = []
    speeds = []

    for record in records:
        sample_dt = fit_seconds_to_datetime(record.get(FIELD_TIMESTAMP))
        elapsed_seconds = None
        if sample_dt is not None and start_dt is not None:
            elapsed_seconds = (sample_dt - start_dt).total_seconds()

        heart_rate = clean_number(record.get(FIELD_HEART_RATE), {255})
        cadence_spm = cadence_to_spm(clean_number(record.get(FIELD_CADENCE), {255}))
        speed_raw = first_non_none(
            clean_number(record.get(FIELD_ENHANCED_SPEED), {65535, 4294967295}),
            clean_number(record.get(FIELD_SPEED), {65535, 4294967295}),
        )
        speed_mps = scale(speed_raw, 1000)

        if heart_rate is not None and 40 < heart_rate < 240:
            heart_rates.append(heart_rate)
        if cadence_spm is not None and 0 < cadence_spm < 300:
            cadences.append(cadence_spm)
        if speed_mps is not None and speed_mps >= 0:
            speeds.append(speed_mps)

        sample_rows.append(
            {
                "sample_timestamp_utc": to_iso8601(sample_dt),
                "elapsed_seconds": elapsed_seconds,
                "distance_m": scale(
                    clean_number(record.get(FIELD_DISTANCE), {65535, 4294967295}),
                    100,
                ),
                "speed_mps": speed_mps,
                "heart_rate_bpm": heart_rate,
                "cadence_spm": cadence_spm,
                "power_watts": clean_number(record.get(FIELD_POWER), {65535, 4294967295}),
                "altitude_m": altitude_from_fit(record.get(FIELD_ALTITUDE)),
                "temperature_c": clean_number(record.get(FIELD_TEMPERATURE), {255}),
                "latitude_semicircles": record.get(FIELD_POSITION_LAT),
                "longitude_semicircles": record.get(FIELD_POSITION_LONG),
            }
        )

    lap_rows = []
    for index, lap in enumerate(laps, start=1):
        lap_start_dt = fit_seconds_to_datetime(
            first_non_none(lap.get(FIELD_LAP_START_TIME), lap.get(FIELD_TIMESTAMP))
        )
        lap_duration = scale(lap.get(FIELD_LAP_TOTAL_TIMER_TIME), 1000)
        lap_end_dt = (
            lap_start_dt + timedelta(seconds=lap_duration)
            if lap_start_dt is not None and lap_duration is not None
            else None
        )
        lap_rows.append(
            {
                "lap_index": index,
                "started_at_utc": to_iso8601(lap_start_dt),
                "ended_at_utc": to_iso8601(lap_end_dt),
                "duration_seconds": lap_duration,
                "distance_m": scale(
                    clean_number(lap.get(FIELD_LAP_TOTAL_DISTANCE), {65535, 4294967295}),
                    100,
                ),
                "avg_speed_mps": scale(
                    clean_number(lap.get(FIELD_LAP_ENHANCED_AVG_SPEED), {65535, 4294967295}),
                    1000,
                ),
                "max_speed_mps": scale(
                    clean_number(lap.get(FIELD_LAP_ENHANCED_MAX_SPEED), {65535, 4294967295}),
                    1000,
                ),
                "avg_heart_rate_bpm": clean_number(lap.get(FIELD_LAP_AVG_HEART_RATE), {255}),
                "max_heart_rate_bpm": clean_number(lap.get(FIELD_LAP_MAX_HEART_RATE), {255}),
                "avg_cadence_spm": cadence_to_spm(
                    clean_number(lap.get(FIELD_LAP_AVG_CADENCE), {255})
                ),
                "lap_type": None,
            }
        )

    avg_heart_rate = first_non_none(
        average(heart_rates), session.get(FIELD_SESSION_AVG_HEART_RATE)
    )
    max_heart_rate = first_non_none(
        max_value(heart_rates), session.get(FIELD_SESSION_MAX_HEART_RATE)
    )
    avg_cadence = first_non_none(
        average(cadences), cadence_to_spm(session.get(FIELD_SESSION_AVG_CADENCE))
    )
    max_cadence = first_non_none(
        max_value(cadences), cadence_to_spm(session.get(FIELD_SESSION_MAX_CADENCE))
    )
    avg_speed = first_non_none(
        average(speeds),
        scale(
            clean_number(
                session.get(FIELD_SESSION_ENHANCED_AVG_SPEED), {65535, 4294967295}
            ),
            1000,
        ),
        scale(
            clean_number(session.get(FIELD_SESSION_AVG_SPEED), {65535, 4294967295}),
            1000,
        ),
    )
    max_speed = first_non_none(
        max_value(speeds),
        scale(
            clean_number(
                session.get(FIELD_SESSION_ENHANCED_MAX_SPEED), {65535, 4294967295}
            ),
            1000,
        ),
        scale(
            clean_number(session.get(FIELD_SESSION_MAX_SPEED), {65535, 4294967295}),
            1000,
        ),
    )

    sport = map_sport(session.get(FIELD_SESSION_SPORT))
    sub_sport = map_sub_sport(session.get(FIELD_SESSION_SUB_SPORT))

    return {
        "source_path": str(Path(filepath)),
        "activity": {
            "activity_type": sport or "unknown",
            "sport": sport,
            "sub_sport": sub_sport,
            "started_at_utc": to_iso8601(start_dt),
            "ended_at_utc": to_iso8601(end_dt),
            "timezone": athlete_timezone,
            "duration_seconds": duration_seconds,
            "moving_time_seconds": duration_seconds,
            "distance_m": scale(
                clean_number(session.get(FIELD_SESSION_TOTAL_DISTANCE), {65535, 4294967295}),
                100,
            ),
            "calories_kcal": clean_number(session.get(FIELD_SESSION_TOTAL_CALORIES), {65535}),
            "total_ascent_m": clean_number(session.get(FIELD_SESSION_TOTAL_ASCENT), {65535}),
            "total_descent_m": clean_number(session.get(FIELD_SESSION_TOTAL_DESCENT), {65535}),
            "avg_speed_mps": avg_speed,
            "max_speed_mps": max_speed,
            "avg_heart_rate_bpm": avg_heart_rate,
            "max_heart_rate_bpm": max_heart_rate,
            "avg_cadence_spm": avg_cadence,
            "max_cadence_spm": max_cadence,
            "training_load": None,
            "device_name": None,
        },
        "laps": lap_rows,
        "samples": sample_rows,
    }


def pace(mps):
    if not mps or mps <= 0.5:
        return "--:--"
    seconds = 1609.344 / mps
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def ftime(seconds):
    if seconds is None:
        return "--:--"
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def miles(meters):
    if meters is None:
        return 0
    return meters / 1609.344


def summarize(filepath):
    canonical = canonicalize_fit(filepath)
    activity = canonical["activity"]
    laps = canonical["laps"]
    samples = canonical["samples"]

    start_utc = (
        datetime.fromisoformat(activity["started_at_utc"])
        if activity["started_at_utc"]
        else None
    )
    start_local = (
        start_utc + timedelta(hours=UTC_OFFSET_HOURS) if start_utc is not None else None
    )

    zone_counts = {zone[2]: 0 for zone in HR_ZONES}
    hr_values = []
    for sample in samples:
        heart_rate = sample["heart_rate_bpm"]
        if heart_rate is None or not (40 < heart_rate < 220):
            continue
        hr_values.append(heart_rate)
        for lower, upper, zone_name in HR_ZONES:
            if lower <= heart_rate < upper:
                zone_counts[zone_name] += 1
                break

    total_points = len(hr_values) or 1
    avg_heart_rate = activity["avg_heart_rate_bpm"] or 0
    high_zone_pct = (
        sum(zone_counts[zone[2]] for zone in HR_ZONES if zone[0] >= 148) / total_points
    ) * 100

    if avg_heart_rate < 140 and high_zone_pct < 5:
        classification = "Easy / Recovery Run"
    elif avg_heart_rate < 150 and high_zone_pct < 20:
        classification = "Moderate Aerobic"
    elif avg_heart_rate < 162:
        classification = "Tempo / Threshold"
    else:
        classification = "High Intensity / Intervals"

    width = 57
    summary_date = (
        start_local.strftime("%A, %B %d, %Y") if start_local is not None else "Unknown"
    )
    print("=" * width)
    print(f"  ACTIVITY SUMMARY - {summary_date}")
    print("=" * width)
    if start_local is not None:
        print(f"  Start:      {start_local.strftime('%I:%M %p')} (local)")
    else:
        print("  Start:      Unknown")
    print(f"  Distance:   {miles(activity['distance_m']):.2f} miles")
    print(f"  Duration:   {ftime(activity['duration_seconds'])}")
    print(f"  Avg Pace:   {pace(activity['avg_speed_mps'])}/mi")
    print(
        f"  Avg HR:     {avg_heart_rate:.0f} bpm  "
        f"({avg_heart_rate / LACTATE_THRESHOLD_HR * 100:.0f}% of LT)"
    )
    print(f"  Max HR:     {activity['max_heart_rate_bpm'] or 0:.0f} bpm")
    print(f"  Cadence:    {activity['avg_cadence_spm'] or 0:.0f} spm (avg)")
    print(f"  Elev Gain:  {((activity['total_ascent_m'] or 0) * 3.28084):.0f} ft")
    print(f"  Type:       {classification}")

    print()
    print("  MILE SPLITS")
    print("  " + "-" * (width - 4))
    print(f"  {'Lap':<10} {'Dist':>6}  {'Time':>6}  {'Pace':>7}  {'Avg HR':>7}  {'Cad':>5}")
    print("  " + "-" * (width - 4))
    for lap in laps:
        distance_miles = miles(lap["distance_m"])
        label = (
            f"Mile {lap['lap_index']}"
            if distance_miles > 0.5
            else f"  +{distance_miles:.2f}mi"
        )
        print(
            f"  {label:<10} {distance_miles:>5.2f}mi  "
            f"{ftime(lap['duration_seconds']):>6}  "
            f"{pace(lap['avg_speed_mps']):>7}/mi  "
            f"{(lap['avg_heart_rate_bpm'] or 0):>6.0f} bpm  "
            f"{(lap['avg_cadence_spm'] or 0):>4.0f}"
        )

    print()
    print(f"  HR ZONE DISTRIBUTION  (LT = {LACTATE_THRESHOLD_HR} bpm)")
    print("  " + "-" * (width - 4))
    for zone_name, count in zone_counts.items():
        percent = count / total_points * 100
        bar = "#" * int(percent / 2.5)
        print(f"  {zone_name}: {percent:5.1f}%  {bar}")

    print()
    print("  Copy everything above this line into your coaching chat.")
    print("=" * width)


def parse_args():
    parser = argparse.ArgumentParser(description="Summarize or export Garmin FIT files.")
    parser.add_argument("filepath", help="Path to the .fit file.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit canonicalized FIT data as JSON instead of a terminal summary.",
    )
    parser.add_argument(
        "--timezone",
        default="America/Chicago",
        help="Timezone used for canonical activity metadata.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.json:
        print(
            json.dumps(
                canonicalize_fit(args.filepath, athlete_timezone=args.timezone),
                indent=2,
            )
        )
        sys.exit(0)
    summarize(args.filepath)

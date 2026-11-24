import sqlite3
import unittest

from tests import _path  # noqa: F401
import db_upgrade
import fit_summary as fs
import workout_structure as ws

MI = ws.METERS_PER_MILE


def lap(n, miles, pace="8:30", hr=150, intensity="interval", trigger="distance", seconds=None, max_hr=None):
    """A lap row as stored. pace 'm:ss' per mile, or pass seconds directly."""
    if seconds is None:
        minutes, secs = pace.split(":")
        seconds = (int(minutes) * 60 + int(secs)) * miles
    return {"lap_index": n, "duration_seconds": seconds, "distance_m": miles * MI, "avg_heart_rate_bpm": hr,
            "max_heart_rate_bpm": max_hr if max_hr is not None else (hr + 5 if hr else None), "intensity": intensity, "lap_trigger": trigger}


def mile_run(paces, hrs=None):
    return [lap(i + 1, 1.0, pace, (hrs or [140] * len(paces))[i]) for i, pace in enumerate(paces)]


RUN = {"sub_sport": "generic", "distance_m": 10 * MI, "workout_name": None, "workout_description": None, "lap_distance_adjusted": 0}


class CodeParsingTests(unittest.TestCase):
    def test_garmin_enum_codes_become_names_and_unknown_codes_are_kept(self):
        self.assertEqual(fs.code_name(fs.INTENSITY_NAMES, 5), "interval")
        self.assertEqual(fs.code_name(fs.LAP_TRIGGER_NAMES, 0), "manual")
        self.assertEqual(fs.code_name(fs.INTENSITY_NAMES, 42), "code_42")      # kept, never dropped
        self.assertIsNone(fs.code_name(fs.INTENSITY_NAMES, 255, {255}))         # Garmin's "invalid"
        self.assertIsNone(fs.code_name(fs.INTENSITY_NAMES, None))

    def test_workout_step_values_stay_as_garmin_wrote_them(self):
        time_step = fs.clean_workout_step({254: 1, 1: 0, 2: 15000, 3: 0, 5: 5555, 6: 6416, 7: 5, 0: ""})
        self.assertEqual((time_step["intensity"], time_step["duration_type"], time_step["duration_value"]), ("interval", "time", 15000))
        self.assertEqual((time_step["target_type"], time_step["target_low"], time_step["target_high"]), ("speed", 5555, 6416))
        self.assertIsNone(time_step["name"])
        self.assertIsNone(time_step["repeat_count"])

    def test_repeat_steps_expose_what_they_repeat(self):
        step = fs.clean_workout_step({254: 3, 1: 6, 2: 1, 4: 3, 7: 0})
        self.assertEqual((step["duration_type"], step["repeat_from_step"], step["repeat_count"]), ("repeat_until_steps_complete", 1, 3))

    def test_invalid_markers_become_none(self):
        step = fs.clean_workout_step({254: 0, 1: 255, 2: 4294967295, 3: 255, 5: 4294967295, 7: 255})
        for key in ("duration_type", "duration_value", "target_type", "target_low", "intensity"):
            self.assertIsNone(step[key], key)

    def test_workout_text_is_trimmed_and_blank_is_none(self):
        self.assertEqual(fs.clean_text("  Sprint "), "Sprint")
        self.assertIsNone(fs.clean_text("   "))
        self.assertIsNone(fs.clean_text(None))


class OrdinaryRunTests(unittest.TestCase):
    def test_auto_laps_labelled_interval_are_not_a_workout(self):
        out = ws.analyze(RUN, mile_run(["8:30"] * 8))
        self.assertNotEqual(out["structure"]["source"], "garmin")
        self.assertEqual(out["structure"]["kind"], "steady_run")
        self.assertTrue(all(l["role_source"] == "inferred" for l in out["laps"]))

    def test_progression_is_found_and_labelled_inferred(self):
        paces = ["9:10", "9:01", "8:48", "8:43", "8:15", "8:11", "8:06", "7:51", "7:50", "7:33", "7:27"]
        hrs = [127, 132, 136, 141, 144, 147, 150, 152, 157, 168, 163]
        s = ws.analyze(RUN, mile_run(paces, hrs))["structure"]
        self.assertEqual((s["kind"], s["source"]), ("progression_run", "inferred"))
        self.assertIn("inferred from mile splits", s["summary"])
        self.assertIn("HR", s["summary"])
        self.assertTrue(s["evidence"])

    def test_fade_and_steady_are_told_apart_by_the_threshold(self):
        self.assertEqual(ws.analyze(RUN, mile_run(["8:00"] * 3 + ["8:30"] * 3 + ["9:10"] * 3))["structure"]["kind"], "fade_run")
        self.assertEqual(ws.analyze(RUN, mile_run(["8:30", "8:35", "8:28", "8:33", "8:31", "8:36"]))["structure"]["kind"], "steady_run")

    def test_a_short_run_gets_no_invented_structure(self):
        s = ws.analyze(RUN, mile_run(["8:30", "8:31", "8:29"]))["structure"]
        self.assertEqual(s["kind"], "plain_run")
        self.assertIsNone(s["summary"])

    def test_no_laps_is_stated_not_guessed(self):
        s = ws.analyze(RUN, [])["structure"]
        self.assertEqual(s["kind"], "no_lap_data")
        self.assertIsNone(s["source"])

    def test_missing_values_do_not_crash_and_stay_missing(self):
        laps = [dict(lap(1, 1.0), distance_m=None), dict(lap(2, 1.0), duration_seconds=None), dict(lap(3, 1.0), avg_heart_rate_bpm=None, max_heart_rate_bpm=None)] + mile_run(["8:30"] * 4)[:0]
        out = ws.analyze(RUN, laps)
        self.assertIsNone(out["laps"][0]["pace_s"])
        self.assertIsNone(out["laps"][1]["pace_s"])
        view = ws.lap_view(out["laps"][2])
        self.assertIsNone(view["avg_hr"])


class GarminStructuredTests(unittest.TestCase):
    def workout(self):
        laps = [lap(1, 1.5, "9:00", 130, "warmup", "distance")]
        for i in range(4):
            laps.append(lap(2 + i * 2, 1.0, "6:30", 165, "interval", "time", seconds=390))
            laps.append(lap(3 + i * 2, 0.25, "10:00", 140, "recovery", "time", seconds=150))
        laps.append(lap(10, 1.0, "9:00", 135, "cooldown", "distance"))
        return laps

    def test_labels_and_name_make_it_garmin_defined(self):
        activity = dict(RUN, workout_name="Threshold", workout_description="4x6:30@6:30/mi")
        out = ws.analyze(activity, self.workout())
        s = out["structure"]
        self.assertEqual((s["kind"], s["source"]), ("garmin_structured_workout", "garmin"))
        self.assertEqual(s["reps"]["count"], 4)
        self.assertIn("Threshold", s["summary"])
        self.assertIn("4x6:30@6:30/mi", s["summary"])
        self.assertEqual({l["role"] for l in out["laps"]}, {"warmup", "rep", "recovery", "cooldown"})
        self.assertTrue(all(l["role_source"] == "garmin" for l in out["laps"]))

    def test_labels_alone_are_enough_when_no_name_is_stored(self):
        s = ws.analyze(RUN, self.workout())["structure"]
        self.assertEqual(s["source"], "garmin")
        self.assertIn("Garmin-labeled workout", s["summary"])

    def test_rest_and_recovery_both_count_as_recoveries(self):
        laps = self.workout()
        laps[2]["intensity"] = "rest"
        out = ws.analyze(RUN, laps)
        self.assertEqual(sum(1 for l in out["laps"] if l["role"] == "recovery"), 4)

    def test_very_short_reps_are_flagged_because_heart_rate_lags(self):
        laps = [lap(1, 1.0, "9:00", 120, "warmup")]
        for i in range(4):
            laps.append(lap(2 + i * 2, 0.05, "4:30", 150, "interval", "time", seconds=14))
            laps.append(lap(3 + i * 2, 0.1, "10:00", 130, "rest", "manual", seconds=60))
        laps.append(lap(10, 1.0, "9:00", 130, "cooldown"))
        out = ws.analyze(RUN, laps)["structure"]
        self.assertEqual(out["reps"]["count"], 4)
        self.assertIn("short_reps_heart_rate_not_meaningful", out["flags"])

    def test_one_long_rep_split_by_auto_laps_is_one_rep_not_several(self):
        # a 3-mile tempo that crossed three 1-mile auto laps, framed by a warm-up and cool-down
        laps = [lap(1, 1.0, "9:00", 130, "warmup"), lap(2, 1.0, "7:00", 160, "interval"), lap(3, 1.0, "6:58", 164, "interval"),
                lap(4, 1.0, "6:55", 167, "interval"), lap(5, 1.0, "9:00", 140, "cooldown")]
        s = ws.analyze(RUN, laps)["structure"]
        self.assertEqual(s["reps"]["count"], 1)
        self.assertEqual(s["reps"]["avg_miles"], 3.0)
        self.assertEqual(len(s["segments"]), 3)                          # warm-up, the tempo, cool-down
        self.assertEqual(s["segments"][1]["lap_numbers"], [2, 3, 4])
        out = ws.analyze(RUN, laps)["laps"]
        self.assertEqual([l["segment"] for l in out], [1, 2, 2, 2, 3])   # each lap says which segment it belongs to

    def test_a_warmup_split_by_an_auto_lap_is_one_warmup(self):
        laps = [lap(1, 1.0, "8:30", 125, "warmup"), lap(2, 0.9, "8:20", 140, "warmup"), lap(3, 1.0, "6:30", 165, "interval"), lap(4, 0.5, "10:00", 140, "rest"),
                lap(5, 1.0, "6:30", 166, "interval"), lap(6, 1.0, "9:00", 140, "cooldown")]
        segments = ws.analyze(RUN, laps)["structure"]["segments"]
        self.assertEqual([s["role"] for s in segments], ["warmup", "rep", "recovery", "rep", "cooldown"])

    def test_a_workout_with_no_rep_laps_says_so(self):
        laps = [lap(1, 1.0, "9:00", 120, "warmup"), lap(2, 1.0, "9:00", 120, "cooldown")]
        s = ws.analyze(RUN, laps)["structure"]
        self.assertIn("no repetition laps labeled", s["summary"])

    def test_plan_lines_are_readable(self):
        steps = [
            {"step_index": 0, "intensity": "warmup", "duration_type": "time", "duration_value": 900000, "target_type": "speed", "target_low": 2944, "target_high": 3333, "repeat_from_step": None, "repeat_count": None},
            {"step_index": 1, "intensity": "interval", "duration_type": "time", "duration_value": 15000, "target_type": "open", "target_low": None, "target_high": None, "repeat_from_step": None, "repeat_count": None},
            {"step_index": 2, "intensity": "rest", "duration_type": "distance", "duration_value": 40000, "target_type": "open", "target_low": None, "target_high": None, "repeat_from_step": None, "repeat_count": None},
            {"step_index": 3, "intensity": "active", "duration_type": "repeat_until_steps_complete", "duration_value": 1, "target_type": None, "target_low": None, "target_high": None, "repeat_from_step": 1, "repeat_count": 3},
        ]
        lines = ws.readable_plan(steps)
        self.assertEqual(lines[0], "0: warmup 15:00 at 9:07-8:03/mi")
        self.assertEqual(lines[1], "1: interval 0:15")
        self.assertEqual(lines[2], "2: rest 400 m")
        self.assertEqual(lines[3], "repeat steps 1-2 x3")


def manual_workout():
    """Like a real manual-lap session: two auto miles, a build lap, 7 hard reps with jog recoveries, two auto miles."""
    laps = [lap(1, 1.0, "8:45", 138), lap(2, 1.0, "8:49", 161), lap(3, 0.70, "7:45", 169, trigger="manual")]
    rep_paces = ["6:39", "6:51", "6:52", "6:54", "6:55", "6:47", "6:55"]
    recoveries = [(0.15, "9:39"), (0.21, "9:48"), (0.25, "9:16"), (0.32, "9:18"), (0.49, "9:00"), (0.90, "8:37")]
    n = 4
    for i, pace in enumerate(rep_paces):
        laps.append(lap(n, 0.45, pace, 164, trigger="manual")); n += 1
        if i < len(recoveries):
            laps.append(lap(n, recoveries[i][0], recoveries[i][1], 156, trigger="manual")); n += 1
    laps.append(lap(n, 1.0, "8:48", 156)); laps.append(lap(n + 1, 1.0, "8:19", 147))
    return laps


class InferredIntervalTests(unittest.TestCase):
    def test_manual_lap_reps_and_recoveries_are_found_and_labelled_inferred(self):
        out = ws.analyze(RUN, manual_workout())
        s = out["structure"]
        self.assertEqual((s["kind"], s["source"]), ("inferred_intervals", "inferred"))
        self.assertEqual(s["reps"]["count"], 7)
        self.assertIn("inferred from manual laps, not a Garmin workout", s["summary"])
        self.assertGreaterEqual(len(s["evidence"]), 3)
        roles = [l["role"] for l in out["laps"]]
        self.assertEqual(roles.count("rep"), 7)
        self.assertEqual(roles.count("recovery"), 6)
        self.assertEqual(roles[0], "before_first_rep")
        self.assertEqual(roles[-1], "after_last_rep")
        self.assertTrue(all(l["role_source"] == "inferred" for l in out["laps"]))

    def test_the_build_lap_before_the_first_rep_is_not_counted_as_a_rep(self):
        out = ws.analyze(RUN, manual_workout())
        self.assertNotEqual(out["laps"][2]["role"], "rep")

    def test_similar_paces_are_not_called_intervals(self):
        laps = [lap(i + 1, 0.5, "8:30" if i % 2 else "8:45", 150, trigger="manual") for i in range(10)]
        s = ws.analyze(RUN, laps)["structure"]
        self.assertEqual(s["kind"], "manual_laps_unclear")
        self.assertIsNone(s["summary"])
        self.assertIn("differ by only", s["evidence"][0])

    def test_too_few_fast_laps_is_not_enough_evidence(self):
        laps = [lap(1, 0.5, "6:40", 160, trigger="manual"), lap(2, 0.3, "9:30", 150, trigger="manual"), lap(3, 0.5, "6:42", 161, trigger="manual")] + [lap(4 + i, 0.3, "9:30", 150, trigger="manual") for i in range(5)]
        s = ws.analyze(RUN, laps)["structure"]
        self.assertEqual(s["kind"], "manual_laps_unclear")
        self.assertIn("only 2 laps near the fast pace", s["evidence"][0])

    def test_fast_laps_with_no_recoveries_between_them_are_not_intervals(self):
        laps = [lap(i + 1, 0.5, "6:40", 160, trigger="manual") for i in range(4)] + [lap(5 + i, 0.4, "9:30", 150, trigger="manual") for i in range(4)]
        s = ws.analyze(RUN, laps)["structure"]
        self.assertEqual(s["kind"], "manual_laps_unclear")
        self.assertIn("gaps have a slower recovery lap", s["evidence"][0])

    def test_a_few_manual_laps_are_not_considered_at_all(self):
        laps = [lap(1, 3.0, "8:30", 140), lap(2, 0.5, "6:40", 165, trigger="manual"), lap(3, 0.3, "9:30", 150, trigger="manual"), lap(4, 0.5, "6:40", 165, trigger="manual")]
        s = ws.analyze(RUN, laps)["structure"]
        self.assertNotIn(s["kind"], ("inferred_intervals", "garmin_structured_workout"))


class TreadmillAndCompactTests(unittest.TestCase):
    def test_a_calibration_mismatch_is_flagged_and_the_summary_carries_the_caveat(self):
        activity = dict(RUN, sub_sport="treadmill", lap_distance_adjusted=1)
        s = ws.analyze(activity, mile_run(["9:15", "9:20", "9:18", "9:22", "9:25", "9:19"]))["structure"]
        self.assertIn("lap_distances_unreliable", s["flags"])
        self.assertIn("treadmill", s["flags"])
        self.assertIn("paces approximate", s["summary"])

    def test_compact_structure_keeps_a_summary_only_when_there_is_something_to_say(self):
        notable = ws.analyze(RUN, manual_workout())["structure"]
        self.assertIsNotNone(ws.compact_structure(notable, 10 * MI)["summary"])
        plain = ws.analyze(RUN, mile_run(["8:30"] * 3))["structure"]
        self.assertIsNone(ws.compact_structure(plain, 3 * MI)["summary"])
        steady_short = ws.analyze(RUN, mile_run(["8:30"] * 5))["structure"]
        self.assertIsNone(ws.compact_structure(steady_short, 5 * MI)["summary"])           # short and even: nothing to add
        steady_long = ws.analyze(RUN, mile_run(["8:30"] * 8))["structure"]
        self.assertIsNotNone(ws.compact_structure(steady_long, 8 * MI)["summary"])


class RecordSplitTests(unittest.TestCase):
    def records(self, pause_at=None, pause=0, speed=3.0, seconds=700):
        out, distance, elapsed = [], 0.0, 0
        for t in range(seconds):
            if pause_at is not None and t == pause_at:
                elapsed += pause
            out.append({"elapsed_seconds": elapsed, "distance_m": distance, "heart_rate_bpm": 140 + t // 100})
            elapsed += 1
            distance += speed
        return out

    def test_splits_use_timer_time_and_exclude_a_pause(self):
        splits, paused = ws.mile_splits_from_records(self.records(pause_at=200, pause=120))
        self.assertEqual(paused, 121)                                   # the whole gap: 120 s of pause plus the 1 s step
        self.assertEqual(splits[0]["pace"], "8:56")                    # 1609.344 m at 3 m/s, pause not counted
        self.assertEqual(len(splits), 1)

    def test_heart_rate_is_averaged_per_split(self):
        splits, _ = ws.mile_splits_from_records(self.records())
        self.assertIsNotNone(splits[0]["avg_hr"])

    def test_too_few_records_gives_nothing(self):
        self.assertEqual(ws.mile_splits_from_records([{"elapsed_seconds": 0, "distance_m": 0, "heart_rate_bpm": 1}] * 3), ([], 0))


def database():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    db_upgrade.apply_schema(connection, str(_path.ROOT / "schema.sql"))
    connection.execute("INSERT INTO athletes(id, display_name) VALUES (1, 'a')")
    return connection


def add_activity(connection, garmin_id, kind="running", sub="generic", laps=(), steps=(), **extra):
    row = {"athlete_id": 1, "garmin_activity_id": garmin_id, "activity_type": kind, "sport": kind, "sub_sport": sub,
           "garmin_type_key": kind, "local_date": "2026-11-20", "start_time_local": "2026-11-20T07:00:00",
           "started_at_utc": "2026-11-20T13:00:00+00:00", "distance_m": 10 * MI, "duration_seconds": 5000.0}
    row.update(extra)
    cursor = connection.execute(f"INSERT INTO activities({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
    activity_id = cursor.lastrowid
    for l in laps:
        connection.execute(
            "INSERT INTO laps(activity_id, lap_index, duration_seconds, distance_m, avg_heart_rate_bpm, max_heart_rate_bpm, intensity, lap_trigger) VALUES (?,?,?,?,?,?,?,?)",
            (activity_id, l["lap_index"], l["duration_seconds"], l["distance_m"], l["avg_heart_rate_bpm"], l["max_heart_rate_bpm"], l["intensity"], l["lap_trigger"]))
    for step in steps:
        connection.execute("INSERT INTO workout_steps(activity_id, step_index, intensity, duration_type, duration_value) VALUES (?,?,?,?,?)",
                           (activity_id, step[0], step[1], step[2], step[3]))
    return activity_id


class DetailsTests(unittest.TestCase):
    def summarize(self, row):
        return {"garmin_activity_id": row["garmin_activity_id"], "local_date": row["local_date"]}

    def test_details_for_a_manual_lap_run(self):
        db = database()
        add_activity(db, 111, laps=manual_workout(), distance_m=sum(l["distance_m"] for l in manual_workout()))
        d = ws.build_details(db, 111, self.summarize)
        self.assertEqual(d["structure"]["kind"], "inferred_intervals")
        self.assertEqual(len(d["laps"]), len(manual_workout()))
        self.assertTrue(d["distance_check"]["laps_match_session"])
        self.assertIsNone(d["garmin_workout"])
        self.assertEqual(d["laps"][3]["role"], "rep")
        self.assertEqual(d["laps"][3]["role_source"], "inferred")

    def test_garmin_plan_is_returned_separately_from_the_executed_laps(self):
        db = database()
        add_activity(db, 222, laps=GarminStructuredTests().workout(), workout_name="Threshold", workout_description="4x6:30",
                     steps=[(0, "warmup", "time", 900000), (1, "interval", "time", 390000)])
        d = ws.build_details(db, 222, self.summarize)
        self.assertEqual(d["garmin_workout"]["name"], "Threshold")
        self.assertEqual(d["garmin_workout"]["planned_steps"][0], "0: warmup 15:00")
        self.assertEqual(d["structure"]["source"], "garmin")

    def test_distance_mismatch_is_reported_with_a_ratio_not_corrected(self):
        db = database()
        laps = mile_run(["9:20"] * 6)                                          # 6.0 mi of lap distance
        add_activity(db, 333, sub="treadmill", laps=laps, distance_m=6.7 * MI, fit_distance_m=6.7 * MI, lap_distance_adjusted=1)
        d = ws.build_details(db, 333, self.summarize)
        check = d["distance_check"]
        self.assertFalse(check["laps_match_session"])
        self.assertAlmostEqual(check["session_to_lap_distance_ratio"], 1.117, places=2)
        self.assertEqual(check["sum_of_lap_distances_miles"], 6.0)             # raw value preserved
        self.assertIn("lap_distances_unreliable", d["structure"]["flags"])

    def test_non_runs_return_laps_but_no_invented_structure(self):
        db = database()
        add_activity(db, 444, kind="cycling", sub="indoor_cycling", laps=mile_run(["3:00"] * 3))
        d = ws.build_details(db, 444, self.summarize)
        self.assertIsNone(d["structure"])
        self.assertTrue(any("only done for runs" in m for m in d["missing"]))

    def test_unknown_activity_is_none(self):
        self.assertIsNone(ws.build_details(database(), 999, self.summarize))

    def test_missing_laps_are_called_out(self):
        db = database()
        add_activity(db, 555, laps=[])
        d = ws.build_details(db, 555, self.summarize)
        self.assertTrue(any("No laps" in m for m in d["missing"]))
        self.assertEqual(d["structure"]["kind"], "no_lap_data")

    def test_laps_without_heart_rate_are_counted_as_missing(self):
        db = database()
        laps = [dict(l, avg_heart_rate_bpm=None, max_heart_rate_bpm=None) for l in mile_run(["8:30"] * 5)]
        add_activity(db, 666, laps=laps)
        self.assertTrue(any("5 laps have no heart rate" in m for m in ws.build_details(db, 666, self.summarize)["missing"]))

    def test_manual_lap_runs_also_get_mile_splits_from_the_records(self):
        db = database()
        activity_id = add_activity(db, 777, laps=manual_workout(), distance_m=10 * MI)
        for t in range(0, 2400):
            db.execute("INSERT INTO activity_samples(activity_id, elapsed_seconds, distance_m, heart_rate_bpm) VALUES (?,?,?,?)", (activity_id, t, t * 4.0, 150))
        d = ws.build_details(db, 777, self.summarize)
        self.assertFalse(d["laps_are_mile_splits"])
        self.assertGreaterEqual(len(d["mile_splits_from_records"]["splits"]), 5)


class ContextIntegrationTests(unittest.TestCase):
    def build(self, db):
        import training_context as tc
        from datetime import date, datetime, timezone
        return tc.build_context(db, datetime(2026, 11, 21, 18, 0, tzinfo=timezone.utc), date(2026, 11, 21), None)

    def test_recent_runs_carry_a_short_structure_and_other_activities_do_not(self):
        db = database()
        add_activity(db, 1, laps=manual_workout(), distance_m=10.2 * MI, local_date="2026-11-20", started_at_utc="2026-11-20T13:00:00+00:00")
        add_activity(db, 2, kind="training", sub="strength_training", laps=[], local_date="2026-11-19", started_at_utc="2026-11-19T13:00:00+00:00", distance_m=0)
        recent = {a["garmin_activity_id"]: a for a in self.build(db)["recent_activities"]}
        self.assertEqual(recent[1]["structure"]["kind"], "inferred_intervals")
        self.assertEqual(recent[1]["structure"]["source"], "inferred")
        self.assertIn("inferred from manual laps", recent[1]["structure"]["summary"])
        self.assertNotIn("structure", recent[2])
        self.assertNotIn("reps", recent[1]["structure"])                 # the compact form stays compact
        self.assertNotIn("evidence", recent[1]["structure"])

    def test_a_garmin_workout_is_labelled_garmin_in_the_context(self):
        db = database()
        add_activity(db, 3, laps=GarminStructuredTests().workout(), workout_name="Threshold", local_date="2026-11-20", started_at_utc="2026-11-20T13:00:00+00:00")
        structure = self.build(db)["recent_activities"][0]["structure"]
        self.assertEqual((structure["kind"], structure["source"]), ("garmin_structured_workout", "garmin"))

    def test_long_runs_and_strength_sessions_are_compact_with_an_id_for_details(self):
        db = database()
        add_activity(db, 4, laps=mile_run(["8:30"] * 10), local_date="2026-11-20", started_at_utc="2026-11-20T13:00:00+00:00")
        add_activity(db, 5, kind="training", sub="strength_training", local_date="2026-11-19", started_at_utc="2026-11-19T13:00:00+00:00", distance_m=0)
        out = self.build(db)
        self.assertEqual(out["recent_long_runs"][0]["garmin_activity_id"], 4)
        self.assertNotIn("garmin_training_load", out["recent_long_runs"][0])
        self.assertEqual(set(out["recent_strength_sessions"][0]), {"garmin_activity_id", "local_date", "type", "duration_minutes"})

    def test_no_laps_means_no_structure_claim_for_a_run(self):
        db = database()
        add_activity(db, 6, laps=[], local_date="2026-11-20", started_at_utc="2026-11-20T13:00:00+00:00")
        self.assertEqual(self.build(db)["recent_activities"][0]["structure"]["kind"], "no_lap_data")


if __name__ == "__main__":
    unittest.main()

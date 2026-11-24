# Garmin validation 2026-11-23

Result: **PASS**

Activities in database: 634, in Garmin: 634.

Compared live against Garmin's activity list and per-activity detail (Garmin Connect itself is not scraped).
Per-activity detail for any failures is in `temp/validation/` (not committed).

- **pass** Completeness: 634 of 634 Garmin activities imported; 0 documented as unavailable; 0 unexplained missing
- **pass** No activities Garmin does not have: 0 in database but not in Garmin's list
- **pass** Garmin activity IDs unique: 634 IDs, 634 distinct, 0 rows without an ID
- **pass** Start instant: 634 of 634 match Garmin; 0 differ
- **pass** Local calendar date: 634 of 634 match Garmin; 0 differ
- **pass** Local start time: 634 of 634 match Garmin; 0 differ
- **pass** UTC offset: 634 of 634 match Garmin; 0 differ
- **pass** Distance within 0.5%: 634 of 634 match Garmin; 0 differ
- **pass** Duration within 1 s: 634 of 634 match Garmin; 0 differ
- **pass** Average heart rate within 1 bpm: 634 of 634 match Garmin; 0 differ
- **pass** Max heart rate within 1 bpm: 634 of 634 match Garmin; 0 differ
- **pass** Garmin-adjusted values keep the FIT's original: 15 activities where Garmin's distance or duration differs from the FIT (calibration, edits, indoor rides without FIT distance); original FIT values preserved on all but 0
- **pass** Garmin metrics stored: 634 of 634 activities have Garmin's training metrics
- **pass** Training effect matches Garmin: 0 differ
- **pass** No invalid cadence values (the 510 sentinel): 0 activities with cadence above 300
- **pass** Lap-distance discrepancies explained: 21 activities have laps differing from the session distance by more than 1%; 21 are treadmill runs (distance calibration), 0 unexplained
- **pass** Lap counts match Garmin: 360 of 360 runs have the same number of laps as Garmin's lapCount
- **pass** Garmin-defined workout structure matches Garmin's split summary: 33 of 33 Garmin-defined workouts have the same number of intervals and recoveries as Garmin's own summary
- **pass** Weekly running mileage (last 8 Monday-Sunday weeks): 8 of 8 weeks agree within 0.05 mi
- **pass** Wellness coverage: 2025-04-05 to 2026-11-23: 598 days stored, 35 recorded as no data, 0 unaccounted for, 0 errored
- **pass** Spot check: long run: activity 21515165264 (running) compared with Garmin's activity detail, laps Garmin 27
- **pass** Spot check: interval-like run (derived from lap pace variation): activity 22132297404 (running) compared with Garmin's activity detail, laps Garmin 34
- **pass** Spot check: treadmill run: activity 25164377515 (treadmill_running) compared with Garmin's activity detail, laps Garmin 16
- **pass** Spot check: strength session: activity 22934665474 (strength_training) compared with Garmin's activity detail, laps Garmin 1
- **pass** Spot check: recorded while traveling: activity 24156044040 (running) compared with Garmin's activity detail, laps Garmin 14
- **pass** Sync is current: last successful sync 0.9 hours ago

## Weekly running mileage

- week of 2026-11-16: database 42.84 mi, Garmin 42.84 mi
- week of 2026-11-09: database 46.85 mi, Garmin 46.85 mi
- week of 2026-11-02: database 39.42 mi, Garmin 39.42 mi
- week of 2026-10-26: database 36.87 mi, Garmin 36.87 mi
- week of 2026-10-19: database 35.66 mi, Garmin 35.66 mi
- week of 2026-10-12: database 34.07 mi, Garmin 34.07 mi
- week of 2026-10-05: database 25.47 mi, Garmin 25.47 mi
- week of 2026-09-28: database 22.66 mi, Garmin 22.66 mi

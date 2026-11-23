# Milestone 1: Garmin data pipeline

Goal: make the data we collect from Garmin accurate, complete, and current, locally.

## Result (2026-11-23)

- **634 of 634** Garmin activities imported (Apr 2025 to today), none missing, none unavailable.
- **Wellness** every day since the first data (2025-04-05): 598 days stored, 35 earlier days recorded as "no data", 0 gaps, 0 errors.
- **Validation: 25 of 25 checks pass.** Report: `docs/reports/garmin-validation-2026-11-23.md`.
- 53 unit tests pass (`python -m unittest discover -s tests -t .`).

## What was wrong, and what changed

- **Dates and time zones.** Everything was stamped as Chicago. Each activity now keeps its own UTC offset (from the FIT file, confirmed against Garmin), so local dates, weekly mileage, travel, and daylight saving are right. 8 of the first 86 activities were on the wrong calendar date before.
- **Duplicates.** The Garmin activity ID is stored and the database enforces it unique. The importer also skips an activity it already holds.
- **Garmin's own values.** Heart rate and cadence come from Garmin's session values, not sample averages. Training effect, training load, heart-rate-zone time, and the activity name are now stored, and Garmin's original list JSON is kept (`garmin_activity_raw`) so anything can be re-extracted without asking Garmin again.
- **Cadence.** The strength cadence of 510 (an unchecked 255 sentinel doubled) is gone, and cadence is only doubled for foot sports (cycling is rpm).
- **A real parser bug.** On files without per-second records, the session `timestamp` is the end of the activity. The importer used it as the start, which put one run 47 minutes off. It now uses `start_time`.
- **Garmin vs the FIT file.** For 15 activities Garmin's servers hold a different distance or duration than the uploaded FIT: indoor rides whose FIT has no distance, treadmill runs calibrated afterward, and edited activities. `distance_m` and `duration_seconds` follow Garmin (what Connect shows). The FIT's own values are kept in `fit_distance_m` and `fit_duration_seconds`, and `garmin_adjusted = 1` marks the activity.
- **Lap distances.** 21 treadmill runs have laps that disagree with the session distance by more than 1%. Laps keep the device's raw distance. We did not rescale anything. `lap_distance_sum_m` and `lap_distance_adjusted` flag them, so lap-based analysis can skip or treat them knowingly.
- **Unavailable data is explicit.** An activity Garmin has no file for gets `fit_status = no_original`. A wellness day with no measurements is recorded `empty`, and a failed day is recorded `error` and retried on every run, however old.
- **Sync.** Hourly, at login, and on wake (a calendar schedule, because launchd skips `StartInterval` while asleep). `last_success_at` is tracked separately from the last attempt, the dashboard shows a banner when the last success is over 3 hours old, and notifications are quiet unless something needs attention.

## How to validate

```bash
python validate_garmin.py          # live comparison with Garmin, writes docs/reports/
python -m unittest discover -s tests -t .
```

It checks completeness, unique IDs, start/local time/date/offset, distance (0.5%), duration (1 s), heart rate (1 bpm), 8 weeks of Monday-Sunday running mileage, lap discrepancies, Garmin metrics, wellness coverage and values, and five spot checks (long run, interval-like run, treadmill run, strength session, an activity recorded while traveling). Exit code 1 if anything fails. Details for failures are written to `temp/validation/` (not committed).

## Backfill commands

```bash
python run_sync.py --skip-wellness --full --limit 0 --since 2025-01-01   # all activities
python run_sync.py --wellness-from 2025-03-01                             # all wellness
```

Both are resumable and safe to repeat. Pace a wellness backfill: going much faster than about 20 days a minute made Garmin return one HTTP 429. That day was recorded as an error and retried.

## Limitations

- **Garmin Connect's website is not scraped.** Validation compares with what Garmin's servers return (the activity list and per-activity detail), which is what Connect displays. Weekly mileage is compared by Garmin's own local dates. An occasional manual glance at one week in Connect is still worthwhile.
- For the 15 Garmin-adjusted activities, laps and per-second samples still carry the FIT's original distance.
- On the 21 flagged treadmill runs, lap pace and lap distance are not reliable.
- Not yet parsed (next milestone): lap intensity and interval structure, and strength-set detail. The "interval-like" spot check is derived from lap pace variation, not a Garmin label.
- Not available through the Personal API paths we tried: training readiness, training status, recovery time. Body Battery is the daily summary only (high, low, at wake), not the intraday series.
- Cadence is `NULL` where the FIT file has no valid value (for example cycling and strength).
- The hourly job needs the Mac awake or waking. Wake behavior follows launchd's documented behavior and has not been tested through a real sleep cycle here.
- The Garmin Personal API key still expires (reported 30 days to a year). Set `GARMIN_KEY_EXPIRES` in `.env` for a warning.

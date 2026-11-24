# Corre Cortes MCP server (local, read-only)

A small MCP server with one tool, `get_training_context`. It reads the validated Corre Cortes
database and nothing else. It is **local only**: nothing is exposed to the internet and no tunnel
is configured.

## Run it

```bash
python mcp_server.py               # stdio (what MCP Inspector and local clients launch)
python mcp_server.py --http 8765   # Streamable HTTP at http://127.0.0.1:8765/mcp
```

The HTTP mode always binds to `127.0.0.1` (there is no option to change that) and refuses
requests whose `Host` or `Origin` is not this machine. There is no authentication, because it is
only reachable from this Mac. Authentication is required before it is ever exposed.

Standard library only, no new dependencies. The database is opened read-only (enforced by SQLite),
so the server cannot change your data.

## Test it with MCP Inspector

```bash
# command line (what was tested, Inspector 2.16.0)
npx @modelcontextprotocol/inspector@latest --cli python3 mcp_server.py --method tools/list
npx @modelcontextprotocol/inspector@latest --cli python3 mcp_server.py --method tools/call --tool-name get_training_context --tool-arg recent_activities=3

# over HTTP, with `python mcp_server.py --http 8765` running
npx @modelcontextprotocol/inspector@latest --cli http://127.0.0.1:8765/mcp --transport http --method tools/call --tool-name get_training_context

# the browser UI (not exercised here)
npx @modelcontextprotocol/inspector@latest python3 mcp_server.py
```

Unit tests: `python -m unittest discover -s tests -t .` (113 tests; `tests/test_training_context.py` and
`tests/test_mcp_server.py` cover this tool).

## What `get_training_context` returns

One optional input, `recent_activities` (1 to 25, default 10). The result:

- `as_of`: the Mac's current local date and time zone.
- `freshness`: last successful Garmin sync, hours since, `stale` (true after 3 hours), whether the last attempt failed, the latest activity, and plain-language notes.
- `training_load.windows`: the last 7, 14, and 28 days. For running: runs, miles, minutes, longest run, average pace, duration-weighted heart rate, elevation, treadmill runs, and minutes in each heart-rate zone. Also strength sessions, other activities, active and rest days, and the total of Garmin's own training load. `last_7_days_miles_vs_28_day_weekly_average` compares the last week with the 28-day weekly average.
- `weekly_mileage`: the last 8 Monday-to-Sunday weeks. The current week is marked partial.
- `recent_long_runs`: the longest run of each of the last 6 weeks (a rule, not a judgment).
- `recovery`: Garmin's sleep (hours and score), HRV with Garmin's own balanced range and status, resting heart rate, wake-up body battery, and daily stress. Each shows the latest value plus 7-day and 28-day averages, and how many days had data. Stress counts finished days only. About 300 tokens.
- `recovery.flags`: plain rules on Garmin's numbers, never a score or medical advice: HRV below Garmin's range; 7-day HRV average 20% or more under the 28-day average; resting HR 3+ bpm over its 28-day average; last night under 6 h; 3+ nights under 6.5 h in 7; wake-up body battery 25+ under its 28-day average. An empty list does not mean recovery is good.
- `recent_strength_sessions`, `recent_activities`: newest first, with Garmin's activity ID, local date, distance, pace, heart rate, training effect, training load, and `flags` where a number needs care (treadmill, Garmin-adjusted distance, unreliable lap distances).
- `quality_sessions`: reported as not available.
- `missing`: everything that is not here and why.

Rules: dates are each activity's own local date, distances follow Garmin, `null` means unknown and never zero, and nothing is estimated.

## Checked against real data

On 2026-11-23, the 7/14/28-day windows, all 8 weekly totals, and the 6 longest runs matched an
independent calculation from Garmin's live activity list, with 0 mismatches. The recovery numbers (latest values and 7/28-day averages, HRV range and status) matched fresh Garmin records over 28 days, 10 of 10 groups. The tool returns about 14.5 KB (roughly 3,600 tokens), of which recovery is about 300.

## `get_workout_details(activity_id)`

Second read-only tool. Takes a `garmin_activity_id` (shown on every run in `get_training_context`) and returns how one run was executed: every lap exactly as Garmin recorded it (distance, time, pace, average and max heart rate, Garmin's intensity label, trigger), a structure summary, the Garmin workout plan if there was one, a distance check, heart-rate zone minutes, and what is missing.

`get_training_context` stays compact: recent runs only get a one-line `structure.summary` when something notable was found (for example "7 x ~3:05 (0.45 mi) at ~6:50/mi with jogging recoveries ... - inferred from manual laps, not a Garmin workout").

**Where structure comes from, and how it is labeled** (`structure.source`):

- `garmin`: the file carries a Garmin workout name or plan, or laps labeled warm-up, cool-down, recovery or rest. Consecutive laps with the same label count as one segment, the way Garmin counts them. Planned steps are returned separately and untouched.
- `inferred`: no Garmin structure, so the shape was guessed. Manual-lap intervals need 6 or more manual laps, 3 or more fast laps within 25 s/mi of each other, and fast and slow laps at least 60 s/mi apart. Progression, fade and steady runs come from 5 or more mile splits (20 s/mi first-third vs last-third difference). Summaries end with "inferred from ...". If the evidence is not enough, the kind is `manual_laps_unclear` or `plain_run` and no structure is invented.
- Ordinary runs are 1-mile auto laps that Garmin labels "interval". That label alone is not treated as a workout.

**Treadmill and calibration.** Lap and split distances are the device's raw numbers. Garmin's session distance can be calibrated and differ. Both are returned in `distance_check` (with the ratio), the run is flagged `lap_distances_unreliable`, and the summary says paces are approximate. Nothing is corrected silently.

**Timer pauses.** Mile splits rebuilt from the per-second records use timer time and leave out gaps of 10 s or more.

## Checked against real data (workout details)

- Lap count equals Garmin's `lapCount` for 360 of 360 runs.
- Garmin-defined workouts: interval and recovery counts equal Garmin's own split summary for 33 of 33 (the validator check). Nov 17 (manual laps) and the older Feb/Mar manual-lap workouts are inferred, and 3 of them differ from Garmin's summary by 0-1 reps or have no clear pattern; those say so in `evidence`.
- Nov 17: 7 reps at 6:39-6:55/mi (3:01-3:14 each, HR 161-168), 6 recoveries of 1:27-7:47, total 10.21 mi, matching the FIT laps.
- Nov 14: progression, miles 9:10 to 7:27/mi, HR 127 to 163.
- 'Sprint' (3x3x0:15@4:25/mi): 9 reps of about 15 s, 8 recoveries, 7 planned steps.
- Treadmill 2026-11-12: session 7.02 mi vs lap sum 6.25 mi, flagged.

## Quality sessions, effort and heart-rate settings

- `quality_sessions` lists, for the last 28 days, Garmin-defined workouts (`garmin_workout`, source garmin), interval patterns guessed from manual laps (`inferred_intervals`), and runs that were physiologically hard (`hard_effort_run`), plus `uncertain` ones where the signals disagree. `athlete_confirmed` is always null: nothing records what a run was meant to be, and intent is never derived from heart rate.
- Pace pattern and effort are separate. A pace pattern is `faster_finish_run`, `slower_finish_run` or `steady_run` (from mile splits). Effort is `easy`, `moderate`, `hard` or `unclear`, from Garmin's own zone minutes and training effect: hard needs 20+ minutes in zones 4-5 and aerobic training effect 3.5+ (or anaerobic 2.0+ with 10+ minutes in zones 4-5). If those disagree it says unclear. Runs under 20 minutes or without zone data get no effort.
- Mile laps that look like GPS errors (a fast mile next to a slow one that average out normally, or one mile at under 60% or over 160% of the typical pace) are marked `suspect` and left out of the pattern. Garmin's values for them are unchanged.
- `heart_rate_settings` gives zone boundaries, max, resting and threshold HR from the time-in-zone message of the latest run's FIT file, with that run's date, and earlier values from about 1, 3, 6 and 12 months back. Max and threshold HR have changed over the year, resting HR has not, so treat all of them as settings on a date, not current measurements.

## Limits (workout details)

- Garmin's per-lap workout-step index in the FIT file is always 0, so laps cannot be tied to individual planned steps; it is stored but not trusted.
- Three older manual-lap workouts (Feb 11, Feb 26, Mar 12) have all laps labeled "interval"; Garmin's own summary shows more structure than the laps do. Their structure is unclear or approximate.
- Heart rate on very short reps (15 s) is flagged as not meaningful.
- Existing activities were filled with `python reprocess_workout_details.py` from archived FIT files (no downloads; safe to repeat; `--dry-run` available). New syncs fill the fields on import.

## Limits

- Interval and threshold sessions are not classified yet (lap intensity is not parsed), so `quality_sessions` says so.
- Garmin's training readiness and recovery time are not available from the Personal API.
- The server runs only while started by hand. It reads whatever the hourly sync has stored, so it is as fresh as the last sync (see `freshness`).
- Protocol: it speaks the tools-only part of MCP (initialize, ping, tools/list, tools/call). Inspector accepted it over both transports. Whether ChatGPT's own client has any extra requirements is not yet tested.

## What the ChatGPT step needs (not done)

1. A way for ChatGPT to reach the server. ChatGPT only connects to remote servers: either a public HTTPS URL (a tunnel or hosting) or OpenAI's Secure MCP Tunnel, which is set up in an OpenAI Platform account.
2. Authentication. ChatGPT cannot send an API key or fixed token, so the choices are OAuth or none. This server returns private data, and OpenAI's guidance leans toward authenticating.
3. The server running whenever ChatGPT calls it (a launchd service), on a Mac that is awake.
4. A test in ChatGPT: add the server under Plugins, start a new conversation, mention the plugin, and ask "What should I run tomorrow?"

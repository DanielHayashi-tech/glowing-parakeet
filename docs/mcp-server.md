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

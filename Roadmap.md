# Roadmap

## Where Things Stand

- Garmin Personal API sync works: activities arrive as FIT files, wellness as JSON.
- A nightly launchd job keeps the database current, with a notification after every run.
- The dashboard covers training (distance, pace, route) and recovery (sleep, resting HR, HRV).
- The old manual staging workflow, the Python dashboard, and the date-hint code are gone.

## Ideas, Roughly In Order

1. **Training load and recovery together.** Plot weekly mileage against average HRV or sleep
   so a hard block and a dip in recovery show up on the same page.
2. **Elevation.** Outdoor runs imported so far have no altitude. Find out whether the API's FIT
   files omit it or the importer drops it, then add an elevation profile to the route panel.
3. **More wellness.** Stress, body battery through the day, and respiration are already stored
   in `wellness_raw`. Pull them out into `wellness_daily` when a chart needs them.
4. **A real map behind the route.** The route is currently just the line. Map tiles would need
   an external service, so this is a privacy trade-off to decide on.
5. **Per-activity pages.** Splits, pace and heart-rate profiles for any run, not only the latest.
6. **Weekly and monthly summaries.** Totals and comparisons beyond the 7-day and 30-day windows.
7. **Notes.** Free-text comments on an activity, using the existing `annotations` table.

## Known Limits

- The Garmin Personal API key expires (reported as 30 days to a year). `GARMIN_KEY_EXPIRES`
  in `.env` drives the warning, because Garmin does not report it.
- Garmin can change the Personal API terms. The manual path (drop a `.fit` file in the inbox)
  keeps working without it.
- API FIT files have not been compared field by field against manual exports. Third parties
  report that some proprietary fields are stripped.
- The dashboard is light-theme only.
- `DailyDistanceChart` and `PaceTrendChart` duplicate some drawing code with `RecoveryCharts`.
  Worth merging if another chart is added.

## Notes For The Next Session

- Read `docs/garmin-personal-api-notes.md` first. It has the endpoints, gotchas, and findings.
- Keep Garmin-specific logic in the sync and import layer, not in the schema.
- Keep `README.md` and this file current when the flow changes.

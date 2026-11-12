import Link from "next/link";

import DailyDistanceChart from "@/app/DailyDistanceChart";
import LatestRunPanel from "@/app/LatestRunPanel";
import PaceTrendChart from "@/app/PaceTrendChart";
import RunningTrendPanel from "@/app/RunningTrendPanel";
import {
  getCurrentWeekCalendar,
  getDashboardSummary,
  getLatestRunRoute,
  getRunningMileageLastTwelveWeeks,
  getTrainingDashboard
} from "@/lib/data";
import { formatPace, titleizeActivityType } from "@/lib/format";

export const dynamic = "force-dynamic";

function summarizeRunningWeek(days) {
  const runningItems = days.flatMap((day) =>
    day.items.filter((activity) => activity.activity_type === "running")
  );

  const totalMiles = runningItems.reduce(
    (sum, item) => sum + Number(item.distance_miles || 0),
    0
  );
  const totalMinutes = runningItems.reduce(
    (sum, item) => sum + Number(item.duration_minutes || 0),
    0
  );
  const totalAscentFt = runningItems.reduce(
    (sum, item) => sum + Number(item.total_ascent_ft || 0),
    0
  );

  const hours = Math.floor(totalMinutes / 60);
  const minutes = Math.round(totalMinutes % 60);

  return {
    totalMiles: totalMiles.toFixed(2),
    totalAscentFt: Math.round(totalAscentFt),
    totalTimeDisplay: `${hours}h ${minutes}m`,
    runCount: runningItems.length
  };
}

function formatDuration(minutes) {
  const hours = Math.floor(minutes / 60);
  const remainder = Math.round(minutes % 60);
  return hours > 0 ? `${hours}h ${remainder}m` : `${remainder}m`;
}

function signedDelta(current, previous, digits, unit) {
  const diff = Number((current - previous).toFixed(digits));
  if (diff === 0) {
    return `No change${unit ? ` ${unit}` : ""}`;
  }
  const sign = diff > 0 ? "+" : "\u2212";
  return `${sign}${Math.abs(diff).toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

function KpiTile({ label, value, unit, delta, detail, hero = false }) {
  return (
    <article className={hero ? "kpi-tile kpi-hero" : "kpi-tile"}>
      <div className="metric-label">{label}</div>
      <div className="kpi-value">
        {value}
        {unit ? <span className="kpi-unit">{unit}</span> : null}
      </div>
      {delta ? <div className="kpi-delta">{delta}</div> : null}
      {detail ? <div className="muted kpi-detail">{detail}</div> : null}
    </article>
  );
}

export default function HomePage() {
  const summary = getDashboardSummary();
  const currentWeek = getCurrentWeekCalendar();
  const runningTrend = getRunningMileageLastTwelveWeeks();
  const training = getTrainingDashboard();
  const route = getLatestRunRoute();
  const runningWeekSummary = summarizeRunningWeek(currentWeek);
  const last7 = training?.last7;
  const prev7 = training?.prev7;
  const hasPrev = Boolean(prev7 && prev7.runCount > 0);

  return (
    <main className="page-shell">
      <section className="hero">
        <h1>Corre Cortes Hub</h1>
        <p>
          A local Next.js view into the SQLite training hub. This version leans
          into a week-by-week rhythm so the dashboard reads more like a training
          board than a raw report dump.
        </p>
      </section>

      <div className="toolbar">
        <Link className="button-link primary" href="/activities">
          Open Activities
        </Link>
        <Link className="button-link" href="/ingestion">
          Ingestion
        </Link>
        <Link className="button-link" href="/api/activities">
          Activities API
        </Link>
        <Link className="button-link" href="/api/summary">
          Summary API
        </Link>
      </div>

      {training ? (
        <>
          <section className="kpi-row">
            <KpiTile
              delta={
                hasPrev
                  ? `${signedDelta(last7.miles, prev7.miles, 1, "mi")} vs prior 7 days`
                  : "No runs in the prior 7 days"
              }
              detail={`${last7.runCount} run${last7.runCount === 1 ? "" : "s"} \u00b7 ${formatDuration(last7.minutes)}`}
              hero
              label="Last 7 days"
              unit="mi"
              value={last7.miles.toFixed(1)}
            />
            <KpiTile
              delta={
                hasPrev && last7.paceMinPerMile && prev7.paceMinPerMile
                  ? `${formatPace(Math.abs(last7.paceMinPerMile - prev7.paceMinPerMile))} ${
                      last7.paceMinPerMile <= prev7.paceMinPerMile ? "faster" : "slower"
                    } vs prior 7 days`
                  : null
              }
              label="Average pace"
              unit="/mi"
              value={last7.paceMinPerMile ? formatPace(last7.paceMinPerMile) : "--"}
            />
            <KpiTile
              delta={
                hasPrev && last7.avgHeartRate && prev7.avgHeartRate
                  ? `${signedDelta(last7.avgHeartRate, prev7.avgHeartRate, 0, "bpm")} vs prior 7 days`
                  : null
              }
              label="Average heart rate"
              unit="bpm"
              value={last7.avgHeartRate ? Math.round(last7.avgHeartRate) : "--"}
            />
            <KpiTile
              detail={`${training.last30.runCount} runs \u00b7 ${formatDuration(training.last30.minutes)}`}
              label="Last 30 days"
              unit="mi"
              value={training.last30.miles.toFixed(0)}
            />
          </section>
          <p className="muted kpi-footnote">
            All time: {summary?.activity_count ?? 0} activities &middot; {summary?.total_miles ?? 0} mi &middot;{" "}
            {summary?.total_hours ?? 0} h. Windows end on your latest activity, {training.anchorIso}.
          </p>

          <section className="section">
            <div className="section-header">
              <div>
                <h2>Daily distance</h2>
                <p>Miles run each day over the last 30 days.</p>
              </div>
            </div>
            <div className="card viz-card">
              <DailyDistanceChart days={training.days} />
            </div>
          </section>

          <section className="section">
            <div className="section-header">
              <div>
                <h2>Pace per run</h2>
                <p>Each dot is one run. Higher is faster. Hollow dots are treadmill runs.</p>
              </div>
            </div>
            <div className="card viz-card">
              {training.paceRuns.length > 0 ? (
                <PaceTrendChart
                  dayCount={training.days.length}
                  days={training.days}
                  runs={training.paceRuns}
                />
              ) : (
                <div className="empty-state">No runs in the last 30 days.</div>
              )}
            </div>
          </section>

          <section className="section">
            <div className="section-header">
              <div>
                <h2>Latest outdoor run</h2>
                <p>
                  {route
                    ? `${route.dateLabel} \u00b7 ${route.miles.toFixed(2)} mi \u00b7 ${Math.round(route.minutes)} min. Hover a profile to find that spot on the route.`
                    : "Route, pace, and heart rate for your most recent run with GPS."}
                </p>
              </div>
            </div>
            <div className="card viz-card">
              <LatestRunPanel route={route} />
            </div>
          </section>
        </>
      ) : (
        <div className="empty-state">
          No activities yet. Sync from Garmin on the Ingestion page, then process the staging area.
        </div>
      )}

      <section className="section">
        <div className="section-header">
          <div>
            <h2>This Week</h2>
            <p>
              Monday through Sunday, left to right, so the week reads like a training calendar.
            </p>
          </div>
          <Link className="button-link" href="/activities">
            View All
          </Link>
        </div>
        {currentWeek.length === 0 ? (
          <div className="empty-state">No recent activities found.</div>
        ) : (
          <div className="week-strip">
            {currentWeek.map((day) => (
              <article className="week-day-card" key={day.isoDate}>
                <div className="week-day-top">
                  <div className="week-day-label">{day.dayLabel}</div>
                  <div className="week-day-date">{day.displayDate}</div>
                </div>
                <div className="week-day-metrics">
                  <div className="week-day-count">
                    {day.activityCount} activit{day.activityCount === 1 ? "y" : "ies"}
                  </div>
                  <div className="week-day-total">
                    {day.totalMiles.toFixed(2)} mi | {day.totalMinutes.toFixed(0)} min
                  </div>
                </div>
                {day.items.length === 0 ? (
                  <div className="week-day-empty">No training logged.</div>
                ) : (
                  <div className="week-day-list">
                    {day.items.map((activity) => (
                      <Link
                        className="week-activity-chip"
                        href={`/activities/${activity.activity_id}`}
                        key={activity.activity_id}
                      >
                        <span className="week-activity-type">
                          {titleizeActivityType(activity.activity_type)}
                        </span>
                        <span className="week-activity-meta">
                          {activity.distance_miles} mi | {activity.duration_minutes} min
                        </span>
                      </Link>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="section">
        <RunningTrendPanel
          summary={runningWeekSummary}
          maxMiles={runningTrend.maxMiles}
          weeks={runningTrend.weeks}
        />
      </section>
    </main>
  );
}

import Link from "next/link";

import RunningTrendPanel from "@/app/RunningTrendPanel";
import {
  getCurrentWeekCalendar,
  getDashboardSummary,
  getLatestActivity,
  getRunningMileageLastTwelveWeeks
} from "@/lib/data";
import { titleizeActivityType } from "@/lib/format";

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

export default function HomePage() {
  const summary = getDashboardSummary();
  const currentWeek = getCurrentWeekCalendar();
  const runningTrend = getRunningMileageLastTwelveWeeks();
  const latest = getLatestActivity();
  const runningWeekSummary = summarizeRunningWeek(currentWeek);

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

      <section className="stats-grid">
        <article className="card">
          <div className="metric-label">Imported Activity Ledger</div>
          <div className="metric-value">{summary?.activity_count ?? 0}</div>
          <p className="muted">Total workouts currently stored in the hub.</p>
        </article>
        <article className="card">
          <div className="metric-label">Distance Logged</div>
          <div className="metric-value">{summary?.total_miles ?? 0}</div>
          <p className="muted">Miles from activities that report distance.</p>
        </article>
        <article className="card">
          <div className="metric-label">Training Time</div>
          <div className="metric-value">{summary?.total_hours ?? 0}</div>
          <p className="muted">Total hours across all imported activity types.</p>
        </article>
        <article className="card">
          <div className="metric-label">Average Session Heart Rate</div>
          <div className="metric-value">{summary?.avg_heart_rate_bpm ?? 0}</div>
          <p className="muted">Average of activity-level average heart rates.</p>
        </article>
        <article className="card">
          <div className="metric-label">Most Recent Activity</div>
          <div className="metric-value">
            {latest?.activity_date_display ?? "No data"}
          </div>
          <p className="muted">
            {latest
              ? `${titleizeActivityType(latest.activity_type)} | ${latest.distance_miles} mi | ${latest.pace_min_per_mile} min/mi`
              : "Import a FIT file to populate this view."}
          </p>
        </article>
      </section>

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

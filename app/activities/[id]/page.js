import Link from "next/link";
import { notFound } from "next/navigation";

import ActivityLapsTable from "@/app/activities/[id]/ActivityLapsTable";
import { getActivityById, getLapsForActivity } from "@/lib/data";
import { titleizeActivityType } from "@/lib/format";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }) {
  const resolvedParams = await params;
  return {
    title: `Activity ${resolvedParams.id} | move2Zero`
  };
}

export default async function ActivityDetailPage({ params }) {
  const resolvedParams = await params;
  const activityId = Number(resolvedParams.id);
  const activity = Number.isFinite(activityId)
    ? getActivityById(activityId)
    : null;

  if (!activity) {
    notFound();
  }

  const laps = getLapsForActivity(activityId);

  return (
    <main className="page-shell">
      <section className="hero">
        <h1>{activity.activity_date_display}</h1>
        <p>
          {titleizeActivityType(activity.activity_type)} | {activity.distance_miles} miles in{" "}
          {activity.duration_minutes} minutes at {activity.pace_min_per_mile} min/mi
          with an average heart rate of {activity.avg_heart_rate_bpm} bpm.
        </p>
      </section>

      <div className="toolbar">
        <Link className="button-link" href="/">
          Dashboard
        </Link>
        <Link className="button-link" href="/activities">
          All Activities
        </Link>
      </div>

      <section className="detail-grid">
        <article className="card">
          <div className="metric-label">Distance</div>
          <div className="metric-value">{activity.distance_miles} mi</div>
        </article>
        <article className="card">
          <div className="metric-label">Duration Minutes</div>
          <div className="metric-value">{activity.duration_minutes} min</div>
        </article>
        <article className="card">
          <div className="metric-label">Average Pace</div>
          <div className="metric-value">{activity.pace_min_per_mile} /mi</div>
        </article>
        <article className="card">
          <div className="metric-label">Average HR</div>
          <div className="metric-value">{activity.avg_heart_rate_bpm} bpm</div>
        </article>
        <article className="card">
          <div className="metric-label">Max HR</div>
          <div className="metric-value">{activity.max_heart_rate_bpm} bpm</div>
        </article>
        <article className="card">
          <div className="metric-label">Average Cadence</div>
          <div className="metric-value">{activity.avg_cadence_spm} spm</div>
        </article>
        <article className="card">
          <div className="metric-label">Climb</div>
          <div className="metric-value">{activity.total_ascent_ft} ft</div>
        </article>
      </section>

      <section className="section">
        <div className="section-header">
          <div>
            <h2>Workout Breakdown</h2>
            <p>
              Select a row to highlight that segment. This view is powered by the
              canonical `laps` table and adds cumulative distance/time on top.
            </p>
          </div>
        </div>
        <ActivityLapsTable laps={laps} />
      </section>
    </main>
  );
}

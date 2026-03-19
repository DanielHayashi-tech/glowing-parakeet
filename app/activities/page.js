import Link from "next/link";

import { titleizeActivityType } from "@/lib/format";
import { getActivities } from "@/lib/data";

export const metadata = {
  title: "Activities | move2Zero"
};

export const dynamic = "force-dynamic";

export default function ActivitiesPage() {
  const activities = getActivities();

  return (
    <main className="page-shell">
      <section className="hero">
        <h1>Activities</h1>
        <p>
          A browsable activity table backed directly by the canonical activity
          view in SQLite.
        </p>
      </section>

      <div className="toolbar">
        <Link className="button-link" href="/">
          Back Home
        </Link>
        <Link className="button-link" href="/api/activities">
          JSON API
        </Link>
      </div>

      <section className="section">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Type</th>
                <th>Distance</th>
                <th>Duration</th>
                <th>Pace</th>
                <th>Avg HR</th>
                <th>Max HR</th>
                <th>Cadence</th>
                <th>Climb</th>
              </tr>
            </thead>
            <tbody>
              {activities.map((activity) => (
                <tr key={activity.activity_id}>
                  <td>
                    <Link href={`/activities/${activity.activity_id}`}>
                      {activity.activity_date_display}
                    </Link>
                  </td>
                  <td>
                    <span className="pill">
                      {titleizeActivityType(activity.activity_type)}
                    </span>
                  </td>
                  <td>{activity.distance_miles} mi</td>
                  <td>{activity.duration_minutes} min</td>
                  <td>{activity.pace_min_per_mile} min/mi</td>
                  <td>{activity.avg_heart_rate_bpm} bpm</td>
                  <td>{activity.max_heart_rate_bpm} bpm</td>
                  <td>{activity.avg_cadence_spm} spm</td>
                  <td>{activity.total_ascent_ft} ft</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

#!/usr/bin/env python3
"""
Serve a local dashboard for the Garmin SQLite data hub.

Usage:
    python local_dashboard.py
    python local_dashboard.py --port 8000
"""

import argparse
import json
import sqlite3
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from generate_visualizations import generate_all_visualizations


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_DB_PATH = Path("data_hub.db")
DEFAULT_SQL_PATH = Path("analytics/starter_queries.sql")
DEFAULT_OUTPUT_DIR = Path("output/visualizations")


def parse_args():
    parser = argparse.ArgumentParser(description="Serve a local Garmin dashboard.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    parser.add_argument(
        "--sql",
        default=str(DEFAULT_SQL_PATH),
        help="Analytics SQL path for creating views.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for generated visualization files.",
    )
    return parser.parse_args()


def fetch_rows(connection, query, params=()):
    cursor = connection.execute(query, params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def apply_views(connection, sql_path):
    connection.executescript(Path(sql_path).read_text(encoding="utf-8"))


def get_dashboard_data(db_path, sql_path):
    connection = sqlite3.connect(db_path)
    try:
        apply_views(connection, sql_path)
        summary = fetch_rows(
            connection,
            """
            SELECT
                COUNT(*) AS activity_count,
                ROUND(SUM(distance_m) / 1609.344, 2) AS total_miles,
                ROUND(SUM(duration_seconds) / 3600.0, 2) AS total_hours,
                ROUND(AVG(avg_heart_rate_bpm), 1) AS avg_heart_rate_bpm
            FROM activities
            """,
        )[0]
        activities = fetch_rows(
            connection,
            """
            SELECT *
            FROM vw_activity_overview
            ORDER BY started_at_utc DESC
            """,
        )
        weekly = fetch_rows(
            connection,
            """
            SELECT *
            FROM vw_weekly_activity_summary
            ORDER BY activity_week_utc DESC
            """,
        )
        latest_activity = activities[0] if activities else None
        latest_laps = []
        if latest_activity:
            latest_laps = fetch_rows(
                connection,
                """
                SELECT *
                FROM vw_lap_overview
                WHERE activity_id = ?
                ORDER BY lap_index
                """,
                (latest_activity["activity_id"],),
            )
        return {
            "summary": summary,
            "activities": activities,
            "weekly": weekly,
            "latest_activity": latest_activity,
            "latest_laps": latest_laps,
        }
    finally:
        connection.close()


def render_page(title, body):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f7f2e8;
      --panel: #fffaf1;
      --ink: #17221f;
      --muted: #55635d;
      --line: #d9d0bf;
      --green: #0b6e4f;
      --orange: #c84c09;
      --blue: #3366cc;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 32px;
      font-family: "Segoe UI", Arial, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #fffaf1 0, #f7f2e8 45%, #efe4d3 100%);
    }}
    a {{ color: var(--blue); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .shell {{
      max-width: 1240px;
      margin: 0 auto;
    }}
    .hero {{
      padding: 28px;
      border: 1px solid var(--line);
      border-radius: 24px;
      background: linear-gradient(135deg, #fffaf1, #f3ead9);
      margin-bottom: 24px;
    }}
    .hero h1 {{
      margin: 0 0 8px 0;
      font-size: 42px;
      line-height: 1;
    }}
    .hero p {{
      margin: 0;
      color: var(--muted);
      max-width: 760px;
      font-size: 16px;
      line-height: 1.5;
    }}
    .grid {{
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      margin-bottom: 24px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 18px;
      box-shadow: 0 8px 24px rgba(23, 34, 31, 0.05);
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .metric-value {{
      margin-top: 10px;
      font-size: 32px;
      font-weight: 700;
    }}
    .section {{
      margin-bottom: 24px;
    }}
    .section h2 {{
      margin: 0 0 14px 0;
      font-size: 24px;
    }}
    .chart-grid {{
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    }}
    .chart-frame {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 14px;
      overflow: hidden;
    }}
    .chart-frame img {{
      width: 100%;
      height: auto;
      display: block;
      border-radius: 12px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      overflow: hidden;
    }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid #ebe2d2;
      text-align: left;
      font-size: 14px;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      background: #fbf6ee;
    }}
    tr:last-child td {{
      border-bottom: none;
    }}
    .pill {{
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      background: #e6f2ee;
      color: var(--green);
      font-weight: 600;
      font-size: 12px;
    }}
    .toolbar {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 18px;
    }}
    .button {{
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      font-weight: 600;
    }}
    pre {{
      margin: 0;
      padding: 16px;
      background: #18221f;
      color: #f7f2e8;
      border-radius: 16px;
      overflow: auto;
      font-size: 13px;
    }}
    @media (max-width: 700px) {{
      body {{ padding: 18px; }}
      .hero h1 {{ font-size: 32px; }}
      .metric-value {{ font-size: 28px; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    {body}
  </div>
</body>
</html>
"""


def render_dashboard(data):
    summary = data["summary"]
    activity_rows = []
    for activity in data["activities"]:
        activity_rows.append(
            f"""
            <tr>
              <td><a href="/activity/{activity['activity_id']}">{escape(activity['activity_date_utc'])}</a></td>
              <td><span class="pill">{escape(activity['activity_type'] or 'unknown')}</span></td>
              <td>{activity['distance_miles'] or 0} mi</td>
              <td>{activity['duration_minutes'] or 0} min</td>
              <td>{activity['pace_min_per_mile'] or '-'} min/mi</td>
              <td>{activity['avg_heart_rate_bpm'] or '-'} bpm</td>
              <td>{activity['avg_cadence_spm'] or '-'} spm</td>
            </tr>
            """
        )

    weekly_rows = []
    for row in data["weekly"]:
        weekly_rows.append(
            f"""
            <tr>
              <td>{escape(row['activity_week_utc'])}</td>
              <td>{row['activity_count']}</td>
              <td>{row['total_miles'] or 0} mi</td>
              <td>{row['total_minutes'] or 0} min</td>
              <td>{row['avg_activity_heart_rate_bpm'] or '-'} bpm</td>
            </tr>
            """
        )

    latest_card = ""
    latest_activity = data["latest_activity"]
    if latest_activity:
        latest_card = f"""
        <div class="card">
          <div class="metric-label">Latest Activity</div>
          <div class="metric-value">{escape(latest_activity['activity_date_utc'])}</div>
          <p>{latest_activity['distance_miles']} mi at {latest_activity['pace_min_per_mile']} min/mi, avg HR {latest_activity['avg_heart_rate_bpm']} bpm.</p>
          <a class="button" href="/activity/{latest_activity['activity_id']}">Open Activity Detail</a>
        </div>
        """

    body = f"""
    <section class="hero">
      <h1>Corre Cortes Hub</h1>
      <p>
        This is the first local URL-backed version of the Garmin data hub. It is reading directly from the SQLite
        database, serving charts from our generated SVGs, and giving us a foundation we can later port into Next.js
        once Node is installed.
      </p>
    </section>

    <div class="toolbar">
      <a class="button" href="/api/activities">View JSON API</a>
      <a class="button" href="/api/summary">View Summary API</a>
      <a class="button" href="/refresh">Refresh Visualizations</a>
    </div>

    <section class="grid">
      <div class="card">
        <div class="metric-label">Activities</div>
        <div class="metric-value">{summary['activity_count'] or 0}</div>
      </div>
      <div class="card">
        <div class="metric-label">Total Miles</div>
        <div class="metric-value">{summary['total_miles'] or 0}</div>
      </div>
      <div class="card">
        <div class="metric-label">Total Hours</div>
        <div class="metric-value">{summary['total_hours'] or 0}</div>
      </div>
      <div class="card">
        <div class="metric-label">Avg Heart Rate</div>
        <div class="metric-value">{summary['avg_heart_rate_bpm'] or 0}</div>
      </div>
      {latest_card}
    </section>

    <section class="section">
      <h2>Visualizations</h2>
      <div class="chart-grid">
        <div class="chart-frame"><img src="/visualizations/activity_distance.svg" alt="Activity distance chart" /></div>
        <div class="chart-frame"><img src="/visualizations/pace_vs_hr.svg" alt="Pace versus heart rate chart" /></div>
        <div class="chart-frame"><img src="/visualizations/lap_pace_by_activity.svg" alt="Lap pace chart" /></div>
        <div class="chart-frame"><img src="/visualizations/latest_activity_heart_rate.svg" alt="Latest activity heart rate chart" /></div>
      </div>
    </section>

    <section class="section">
      <h2>Activities</h2>
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Type</th>
            <th>Distance</th>
            <th>Duration</th>
            <th>Pace</th>
            <th>Avg HR</th>
            <th>Cadence</th>
          </tr>
        </thead>
        <tbody>
          {''.join(activity_rows)}
        </tbody>
      </table>
    </section>

    <section class="section">
      <h2>Weekly Summary</h2>
      <table>
        <thead>
          <tr>
            <th>Week</th>
            <th>Activities</th>
            <th>Miles</th>
            <th>Minutes</th>
            <th>Avg HR</th>
          </tr>
        </thead>
        <tbody>
          {''.join(weekly_rows)}
        </tbody>
      </table>
    </section>
    """
    return render_page("Corre Cortes Hub", body)


def render_activity_detail(activity_id, db_path, sql_path):
    connection = sqlite3.connect(db_path)
    try:
        apply_views(connection, sql_path)
        activities = fetch_rows(
            connection,
            "SELECT * FROM vw_activity_overview WHERE activity_id = ?",
            (activity_id,),
        )
        if not activities:
            return None
        activity = activities[0]
        laps = fetch_rows(
            connection,
            """
            SELECT *
            FROM vw_lap_overview
            WHERE activity_id = ?
            ORDER BY lap_index
            """,
            (activity_id,),
        )
    finally:
        connection.close()

    lap_rows = []
    for lap in laps:
        lap_rows.append(
            f"""
            <tr>
              <td>{lap['lap_index']}</td>
              <td>{lap['lap_distance_miles'] or 0} mi</td>
              <td>{lap['lap_duration_minutes'] or 0} min</td>
              <td>{lap['lap_pace_min_per_mile'] or '-'} min/mi</td>
              <td>{lap['lap_avg_heart_rate_bpm'] or '-'} bpm</td>
              <td>{lap['lap_avg_cadence_spm'] or '-'} spm</td>
            </tr>
            """
        )

    body = f"""
    <section class="hero">
      <h1>{escape(activity['activity_date_utc'])} Activity Detail</h1>
      <p>
        {activity['distance_miles']} miles, {activity['duration_minutes']} minutes,
        pace {activity['pace_min_per_mile']} min/mi, avg HR {activity['avg_heart_rate_bpm']} bpm.
      </p>
    </section>

    <div class="toolbar">
      <a class="button" href="/">Back to Dashboard</a>
      <a class="button" href="/api/activities">JSON API</a>
    </div>

    <section class="grid">
      <div class="card">
        <div class="metric-label">Distance</div>
        <div class="metric-value">{activity['distance_miles']}</div>
      </div>
      <div class="card">
        <div class="metric-label">Duration Minutes</div>
        <div class="metric-value">{activity['duration_minutes']}</div>
      </div>
      <div class="card">
        <div class="metric-label">Pace</div>
        <div class="metric-value">{activity['pace_min_per_mile']}</div>
      </div>
      <div class="card">
        <div class="metric-label">Average Heart Rate</div>
        <div class="metric-value">{activity['avg_heart_rate_bpm']}</div>
      </div>
    </section>

    <section class="section">
      <h2>Lap Splits</h2>
      <table>
        <thead>
          <tr>
            <th>Lap</th>
            <th>Distance</th>
            <th>Duration</th>
            <th>Pace</th>
            <th>Avg HR</th>
            <th>Cadence</th>
          </tr>
        </thead>
        <tbody>
          {''.join(lap_rows)}
        </tbody>
      </table>
    </section>
    """
    return render_page(f"Activity {activity_id}", body)


class DashboardHandler(BaseHTTPRequestHandler):
    db_path = DEFAULT_DB_PATH
    sql_path = DEFAULT_SQL_PATH
    output_dir = DEFAULT_OUTPUT_DIR

    def _write_response(self, status, body, content_type="text/html; charset=utf-8"):
        payload = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, payload, status=200):
        self._write_response(
            status,
            json.dumps(payload, indent=2),
            "application/json; charset=utf-8",
        )

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/refresh":
            generate_all_visualizations(self.db_path, self.sql_path, self.output_dir)
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        if path.startswith("/visualizations/"):
            file_path = self.output_dir / path.split("/", 2)[2]
            if not file_path.exists():
                generate_all_visualizations(self.db_path, self.sql_path, self.output_dir)
            if file_path.exists():
                self._write_response(200, file_path.read_bytes(), "image/svg+xml")
            else:
                self._write_response(404, "Visualization not found")
            return

        if path == "/api/summary":
            data = get_dashboard_data(self.db_path, self.sql_path)
            self._json(data["summary"])
            return

        if path == "/api/activities":
            data = get_dashboard_data(self.db_path, self.sql_path)
            self._json(data["activities"])
            return

        if path.startswith("/activity/"):
            activity_id = path.rsplit("/", 1)[-1]
            if not activity_id.isdigit():
                self._write_response(400, "Invalid activity id")
                return
            page = render_activity_detail(int(activity_id), self.db_path, self.sql_path)
            if page is None:
                self._write_response(404, "Activity not found")
                return
            self._write_response(200, page)
            return

        if path == "/":
            generate_all_visualizations(self.db_path, self.sql_path, self.output_dir)
            data = get_dashboard_data(self.db_path, self.sql_path)
            self._write_response(200, render_dashboard(data))
            return

        self._write_response(404, "Not found")


def main():
    args = parse_args()
    db_path = Path(args.db)
    sql_path = Path(args.sql)
    output_dir = Path(args.output_dir)

    if not db_path.exists():
        raise SystemExit(f"Database does not exist: {db_path}")
    if not sql_path.exists():
        raise SystemExit(f"Analytics SQL file does not exist: {sql_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    DashboardHandler.db_path = db_path
    DashboardHandler.sql_path = sql_path
    DashboardHandler.output_dir = output_dir

    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Serving move2Zero dashboard at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

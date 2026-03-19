#!/usr/bin/env python3
"""
Generate first-pass SVG visualizations from the SQLite Garmin data hub.

Usage:
    python generate_visualizations.py
    python generate_visualizations.py --db data_hub.db --output-dir output/visualizations
"""

import argparse
import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("data_hub.db")
DEFAULT_SQL_PATH = Path("analytics/starter_queries.sql")
DEFAULT_OUTPUT_DIR = Path("output/visualizations")

WIDTH = 960
HEIGHT = 540
PADDING_LEFT = 90
PADDING_RIGHT = 40
PADDING_TOP = 50
PADDING_BOTTOM = 90

SERIES_COLORS = ["#0b6e4f", "#c84c09", "#3366cc", "#9c27b0", "#b71c1c"]


def parse_args():
    parser = argparse.ArgumentParser(description="Generate SVG charts from the SQLite data hub.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    parser.add_argument(
        "--sql",
        default=str(DEFAULT_SQL_PATH),
        help="Path to the analytics SQL file used to create views.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where SVG charts will be written.",
    )
    return parser.parse_args()


def apply_views(connection, sql_path):
    sql_text = Path(sql_path).read_text(encoding="utf-8")
    connection.executescript(sql_text)


def fetch_rows(connection, query, params=()):
    cursor = connection.execute(query, params)
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def ensure_output_dir(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)


def svg_canvas(title):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="100%" height="100%" fill="#f8f5ef" />',
        f'<text x="{WIDTH / 2}" y="30" text-anchor="middle" font-size="22" font-family="Segoe UI, Arial, sans-serif" fill="#162521">{escape_xml(title)}</text>',
    ]


def escape_xml(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def chart_bounds():
    return (
        PADDING_LEFT,
        PADDING_TOP,
        WIDTH - PADDING_RIGHT,
        HEIGHT - PADDING_BOTTOM,
    )


def scale_linear(value, domain_min, domain_max, range_min, range_max):
    if domain_max == domain_min:
        return (range_min + range_max) / 2
    ratio = (value - domain_min) / (domain_max - domain_min)
    return range_min + ratio * (range_max - range_min)


def write_svg(path, lines):
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def draw_axes(lines, x0, y0, x1, y1, y_ticks):
    lines.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="#38423b" stroke-width="2" />')
    lines.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="#38423b" stroke-width="2" />')
    for label, y in y_ticks:
        lines.append(f'<line x1="{x0 - 5}" y1="{y}" x2="{x1}" y2="{y}" stroke="#d9d2c3" stroke-width="1" />')
        lines.append(
            f'<text x="{x0 - 10}" y="{y + 4}" text-anchor="end" font-size="12" font-family="Segoe UI, Arial, sans-serif" fill="#38423b">{escape_xml(label)}</text>'
        )


def create_activity_distance_chart(activities, output_dir):
    lines = svg_canvas("Activity Distance")
    x0, y0, x1, y1 = chart_bounds()
    max_distance = max(activity["distance_miles"] for activity in activities) if activities else 1
    y_ticks = []
    for fraction in range(5):
        tick_value = round(max_distance * fraction / 4, 1)
        y = scale_linear(tick_value, 0, max_distance, y1, y0)
        y_ticks.append((f"{tick_value:.1f} mi", y))
    draw_axes(lines, x0, y0, x1, y1, y_ticks)

    chart_width = x1 - x0
    bar_width = max(40, chart_width / max(len(activities), 1) * 0.55)
    gap = chart_width / max(len(activities), 1)
    for index, activity in enumerate(activities):
        bar_height = scale_linear(activity["distance_miles"], 0, max_distance, 0, y1 - y0)
        left = x0 + (index * gap) + (gap - bar_width) / 2
        top = y1 - bar_height
        lines.append(
            f'<rect x="{left:.2f}" y="{top:.2f}" width="{bar_width:.2f}" height="{bar_height:.2f}" fill="#0b6e4f" rx="6" />'
        )
        label_x = left + bar_width / 2
        lines.append(
            f'<text x="{label_x:.2f}" y="{y1 + 22}" text-anchor="middle" font-size="12" font-family="Segoe UI, Arial, sans-serif" fill="#38423b">{escape_xml(activity["activity_date_utc"])}</text>'
        )
        lines.append(
            f'<text x="{label_x:.2f}" y="{top - 8:.2f}" text-anchor="middle" font-size="12" font-family="Segoe UI, Arial, sans-serif" fill="#162521">{activity["distance_miles"]:.2f}</text>'
        )

    lines.append(
        f'<text x="{WIDTH / 2}" y="{HEIGHT - 20}" text-anchor="middle" font-size="14" font-family="Segoe UI, Arial, sans-serif" fill="#38423b">Workout Date</text>'
    )
    lines.append(
        f'<text x="26" y="{HEIGHT / 2}" text-anchor="middle" font-size="14" font-family="Segoe UI, Arial, sans-serif" fill="#38423b" transform="rotate(-90 26 {HEIGHT / 2})">Distance (miles)</text>'
    )
    write_svg(output_dir / "activity_distance.svg", lines)


def create_pace_vs_hr_chart(activities, output_dir):
    lines = svg_canvas("Average Pace vs Heart Rate")
    x0, y0, x1, y1 = chart_bounds()
    pace_values = [activity["pace_min_per_mile"] for activity in activities if activity["pace_min_per_mile"] is not None]
    hr_values = [activity["avg_heart_rate_bpm"] for activity in activities if activity["avg_heart_rate_bpm"] is not None]
    min_pace = min(pace_values) if pace_values else 0
    max_pace = max(pace_values) if pace_values else 1
    min_hr = min(hr_values) if hr_values else 0
    max_hr = max(hr_values) if hr_values else 1

    y_ticks = []
    for fraction in range(5):
        tick_value = min_hr + ((max_hr - min_hr) * fraction / 4)
        y = scale_linear(tick_value, min_hr, max_hr, y1, y0)
        y_ticks.append((f"{tick_value:.0f} bpm", y))
    draw_axes(lines, x0, y0, x1, y1, y_ticks)

    for fraction in range(5):
        tick_value = min_pace + ((max_pace - min_pace) * fraction / 4)
        x = scale_linear(tick_value, min_pace, max_pace, x0, x1)
        lines.append(f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{y1}" stroke="#ece4d8" stroke-width="1" />')
        lines.append(
            f'<text x="{x}" y="{y1 + 22}" text-anchor="middle" font-size="12" font-family="Segoe UI, Arial, sans-serif" fill="#38423b">{tick_value:.2f}</text>'
        )

    for activity in activities:
        if activity["pace_min_per_mile"] is None or activity["avg_heart_rate_bpm"] is None:
            continue
        cx = scale_linear(activity["pace_min_per_mile"], min_pace, max_pace, x0, x1)
        cy = scale_linear(activity["avg_heart_rate_bpm"], min_hr, max_hr, y1, y0)
        radius = 8 + (activity["distance_miles"] / max(1, max(a["distance_miles"] for a in activities))) * 10
        lines.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{radius:.2f}" fill="#c84c09" fill-opacity="0.75" />')
        lines.append(
            f'<text x="{cx:.2f}" y="{cy - radius - 6:.2f}" text-anchor="middle" font-size="12" font-family="Segoe UI, Arial, sans-serif" fill="#162521">{escape_xml(activity["activity_date_utc"])}</text>'
        )

    lines.append(
        f'<text x="{WIDTH / 2}" y="{HEIGHT - 20}" text-anchor="middle" font-size="14" font-family="Segoe UI, Arial, sans-serif" fill="#38423b">Pace (min/mi)</text>'
    )
    lines.append(
        f'<text x="26" y="{HEIGHT / 2}" text-anchor="middle" font-size="14" font-family="Segoe UI, Arial, sans-serif" fill="#38423b" transform="rotate(-90 26 {HEIGHT / 2})">Average Heart Rate (bpm)</text>'
    )
    write_svg(output_dir / "pace_vs_hr.svg", lines)


def create_lap_pace_chart(laps, output_dir):
    lines = svg_canvas("Lap Pace by Activity")
    x0, y0, x1, y1 = chart_bounds()
    grouped = {}
    max_lap_index = 1
    valid_paces = []
    for lap in laps:
        grouped.setdefault(lap["activity_id"], []).append(lap)
        max_lap_index = max(max_lap_index, lap["lap_index"])
        if lap["lap_pace_min_per_mile"] is not None:
            valid_paces.append(lap["lap_pace_min_per_mile"])

    min_pace = min(valid_paces) if valid_paces else 0
    max_pace = max(valid_paces) if valid_paces else 1
    y_ticks = []
    for fraction in range(5):
        tick_value = min_pace + ((max_pace - min_pace) * fraction / 4)
        y = scale_linear(tick_value, min_pace, max_pace, y1, y0)
        y_ticks.append((f"{tick_value:.2f}", y))
    draw_axes(lines, x0, y0, x1, y1, y_ticks)

    for lap_index in range(1, max_lap_index + 1):
        x = scale_linear(lap_index, 1, max_lap_index, x0, x1)
        lines.append(f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{y1}" stroke="#ece4d8" stroke-width="1" />')
        lines.append(
            f'<text x="{x}" y="{y1 + 22}" text-anchor="middle" font-size="12" font-family="Segoe UI, Arial, sans-serif" fill="#38423b">{lap_index}</text>'
        )

    legend_x = x1 - 140
    legend_y = y0 + 10
    for index, activity_id in enumerate(sorted(grouped)):
        activity_laps = sorted(grouped[activity_id], key=lambda row: row["lap_index"])
        points = []
        for lap in activity_laps:
            if lap["lap_pace_min_per_mile"] is None:
                continue
            x = scale_linear(lap["lap_index"], 1, max_lap_index, x0, x1)
            y = scale_linear(lap["lap_pace_min_per_mile"], min_pace, max_pace, y1, y0)
            points.append((x, y))
        color = SERIES_COLORS[index % len(SERIES_COLORS)]
        if points:
            lines.append(
                '<polyline fill="none" stroke="{color}" stroke-width="3" points="{points}" />'.format(
                    color=color,
                    points=" ".join(f"{x:.2f},{y:.2f}" for x, y in points),
                )
            )
            for x, y in points:
                lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{color}" />')
        lines.append(f'<rect x="{legend_x}" y="{legend_y + (index * 24)}" width="14" height="14" fill="{color}" />')
        lines.append(
            f'<text x="{legend_x + 22}" y="{legend_y + 12 + (index * 24)}" font-size="12" font-family="Segoe UI, Arial, sans-serif" fill="#38423b">Activity {activity_id}</text>'
        )

    lines.append(
        f'<text x="{WIDTH / 2}" y="{HEIGHT - 20}" text-anchor="middle" font-size="14" font-family="Segoe UI, Arial, sans-serif" fill="#38423b">Lap Index</text>'
    )
    lines.append(
        f'<text x="26" y="{HEIGHT / 2}" text-anchor="middle" font-size="14" font-family="Segoe UI, Arial, sans-serif" fill="#38423b" transform="rotate(-90 26 {HEIGHT / 2})">Lap Pace (min/mi)</text>'
    )
    write_svg(output_dir / "lap_pace_by_activity.svg", lines)


def create_latest_activity_hr_chart(samples, output_dir):
    lines = svg_canvas("Latest Activity Heart Rate")
    x0, y0, x1, y1 = chart_bounds()
    valid_samples = [
        sample for sample in samples
        if sample["elapsed_seconds"] is not None and sample["heart_rate_bpm"] is not None
    ]
    if not valid_samples:
        write_svg(output_dir / "latest_activity_heart_rate.svg", lines)
        return

    max_minutes = max(sample["elapsed_seconds"] / 60.0 for sample in valid_samples)
    min_hr = min(sample["heart_rate_bpm"] for sample in valid_samples)
    max_hr = max(sample["heart_rate_bpm"] for sample in valid_samples)
    y_ticks = []
    for fraction in range(5):
        tick_value = min_hr + ((max_hr - min_hr) * fraction / 4)
        y = scale_linear(tick_value, min_hr, max_hr, y1, y0)
        y_ticks.append((f"{tick_value:.0f} bpm", y))
    draw_axes(lines, x0, y0, x1, y1, y_ticks)

    for fraction in range(6):
        tick_value = max_minutes * fraction / 5
        x = scale_linear(tick_value, 0, max_minutes, x0, x1)
        lines.append(f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{y1}" stroke="#ece4d8" stroke-width="1" />')
        lines.append(
            f'<text x="{x}" y="{y1 + 22}" text-anchor="middle" font-size="12" font-family="Segoe UI, Arial, sans-serif" fill="#38423b">{tick_value:.1f}</text>'
        )

    points = []
    for sample in valid_samples:
        x = scale_linear(sample["elapsed_seconds"] / 60.0, 0, max_minutes, x0, x1)
        y = scale_linear(sample["heart_rate_bpm"], min_hr, max_hr, y1, y0)
        points.append((x, y))
    lines.append(
        '<polyline fill="none" stroke="#3366cc" stroke-width="2" points="{points}" />'.format(
            points=" ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        )
    )

    lines.append(
        f'<text x="{WIDTH / 2}" y="{HEIGHT - 20}" text-anchor="middle" font-size="14" font-family="Segoe UI, Arial, sans-serif" fill="#38423b">Elapsed Minutes</text>'
    )
    lines.append(
        f'<text x="26" y="{HEIGHT / 2}" text-anchor="middle" font-size="14" font-family="Segoe UI, Arial, sans-serif" fill="#38423b" transform="rotate(-90 26 {HEIGHT / 2})">Heart Rate (bpm)</text>'
    )
    write_svg(output_dir / "latest_activity_heart_rate.svg", lines)


def generate_all_visualizations(db_path, sql_path, output_dir):
    if not db_path.exists():
        raise SystemExit(f"Database does not exist: {db_path}")
    if not sql_path.exists():
        raise SystemExit(f"Analytics SQL file does not exist: {sql_path}")

    ensure_output_dir(output_dir)
    connection = sqlite3.connect(db_path)

    try:
        apply_views(connection, sql_path)
        activities = fetch_rows(
            connection,
            """
            SELECT activity_id, activity_date_utc, distance_miles, duration_minutes,
                   pace_min_per_mile, avg_heart_rate_bpm
            FROM vw_activity_overview
            ORDER BY started_at_utc
            """,
        )
        laps = fetch_rows(
            connection,
            """
            SELECT activity_id, lap_index, lap_pace_min_per_mile
            FROM vw_lap_overview
            ORDER BY activity_id, lap_index
            """,
        )
        latest_activity = fetch_rows(
            connection,
            "SELECT MAX(id) AS activity_id FROM activities",
        )
        latest_activity_id = latest_activity[0]["activity_id"] if latest_activity else None
        latest_samples = []
        if latest_activity_id is not None:
            latest_samples = fetch_rows(
                connection,
                """
                SELECT elapsed_seconds, heart_rate_bpm
                FROM activity_samples
                WHERE activity_id = ?
                ORDER BY elapsed_seconds
                """,
                (latest_activity_id,),
            )

        create_activity_distance_chart(activities, output_dir)
        create_pace_vs_hr_chart(activities, output_dir)
        create_lap_pace_chart(laps, output_dir)
        create_latest_activity_hr_chart(latest_samples, output_dir)

    finally:
        connection.close()

    return output_dir


def main():
    args = parse_args()
    db_path = Path(args.db)
    sql_path = Path(args.sql)
    output_dir = Path(args.output_dir)
    generate_all_visualizations(db_path, sql_path, output_dir)
    print(f"Wrote 4 SVG charts to {output_dir}")


if __name__ == "__main__":
    main()

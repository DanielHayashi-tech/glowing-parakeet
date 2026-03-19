"use client";

import { useState } from "react";

function shouldRenderMonthLabel(weeks, index) {
  if (index === 0) {
    return true;
  }

  const [, month] = weeks[index].weekStartIso.split("-").map(Number);
  const [, previousMonth] = weeks[index - 1].weekStartIso.split("-").map(Number);
  return month !== previousMonth;
}

function monthLabelForPoint(weeks, index) {
  if (!shouldRenderMonthLabel(weeks, index)) {
    return "";
  }

  const [year, month] = weeks[index].weekStartIso.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, 1));
  const monthLabel = date.toLocaleDateString("en-US", {
    month: "short",
    timeZone: "UTC"
  });
  return monthLabel.toUpperCase();
}

export default function RunningTrendPanel({ summary, weeks, maxMiles }) {
  const [selectedWeekStart, setSelectedWeekStart] = useState(
    weeks.length ? weeks[weeks.length - 1].weekStartIso : null
  );

  if (!weeks.length) {
    return (
      <div className="empty-state">
        No running data yet. Import a run to draw the first trend line.
      </div>
    );
  }

  const selectedWeek =
    weeks.find((week) => week.weekStartIso === selectedWeekStart) ?? weeks[weeks.length - 1];

  const width = 920;
  const height = 320;
  const padding = { top: 24, right: 72, bottom: 48, left: 8 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const safeMax = Math.max(maxMiles, 1);
  const step = weeks.length > 1 ? innerWidth / (weeks.length - 1) : 0;

  const points = weeks.map((week, index) => {
    const x = padding.left + step * index;
    const y =
      padding.top +
      innerHeight -
      (Number(week.runningMiles || 0) / safeMax) * innerHeight;
    return { ...week, x, y, isSelected: week.weekStartIso === selectedWeek.weekStartIso };
  });

  const pathData = points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");
  const areaPath = `${pathData} L ${points.at(-1).x} ${padding.top + innerHeight} L ${points[0].x} ${padding.top + innerHeight} Z`;

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => {
    const value = Number((safeMax * fraction).toFixed(1));
    const y = padding.top + innerHeight - innerHeight * fraction;
    return { value, y };
  });

  return (
    <div className="running-panel">
      <div className="activity-pill-row">
        <span className="activity-pill active">Run</span>
      </div>

      <div className="running-panel-header">
        <div>
          <h2>This week</h2>
          <p className="muted-dark">
            Monday through Sunday, focused on running only.
          </p>
        </div>
      </div>

      <div className="running-stats-row">
        <div className="running-stat">
          <span className="running-stat-label">Distance</span>
          <span className="running-stat-value">{summary.totalMiles} mi</span>
        </div>
        <div className="running-stat">
          <span className="running-stat-label">Time</span>
          <span className="running-stat-value">{summary.totalTimeDisplay}</span>
        </div>
        <div className="running-stat">
          <span className="running-stat-label">Elev Gain</span>
          <span className="running-stat-value">{summary.totalAscentFt} ft</span>
        </div>
      </div>

      <div className="trend-header trend-header-dark">
        <div>
          <p className="chart-label chart-label-dark">Weekly Running Consistency</p>
          <p className="muted-dark">
            Last 12 weeks, Monday through Sunday, with the oldest week on the left.
          </p>
        </div>
      </div>

      <div className="selected-week-card">
        <div className="selected-week-range">{selectedWeek.weekRangeLabel}</div>
        <div className="selected-week-value">
          {selectedWeek.runningMiles.toFixed(2)} mi
        </div>
        <div className="selected-week-meta">
          {selectedWeek.runCount} run{selectedWeek.runCount === 1 ? "" : "s"} |{" "}
          {selectedWeek.runningMinutes.toFixed(1)} min
        </div>
      </div>

      <div className="trend-svg-wrap trend-svg-wrap-dark">
        <svg
          aria-label="Weekly running mileage trend"
          className="trend-svg trend-svg-dark"
          role="img"
          viewBox={`0 0 ${width} ${height}`}
        >
          <defs>
            <linearGradient id="runningTrendFill" x1="0%" x2="0%" y1="0%" y2="100%">
              <stop offset="0%" stopColor="rgba(200, 76, 9, 0.36)" />
              <stop offset="100%" stopColor="rgba(200, 76, 9, 0.04)" />
            </linearGradient>
          </defs>

          {yTicks.map((tick) => (
            <g key={tick.value}>
              <line
                stroke="#dccfbf"
                x1={padding.left}
                x2={width - padding.right}
                y1={tick.y}
                y2={tick.y}
              />
              <text
                fill="#59665f"
                fontSize="11"
                textAnchor="start"
                x={width - padding.right + 14}
                y={tick.y + 4}
              >
                {Math.round(tick.value)} mi
              </text>
            </g>
          ))}

          <path d={areaPath} fill="url(#runningTrendFill)" />
          <path
            d={pathData}
            fill="none"
            stroke="#c84c09"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="5"
          />

          {points.map((point, index) => (
            <g
              key={point.weekStartIso}
              onClick={() => setSelectedWeekStart(point.weekStartIso)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setSelectedWeekStart(point.weekStartIso);
                }
              }}
              role="button"
              tabIndex={0}
            >
              {point.isSelected ? (
                <circle
                  cx={point.x}
                  cy={point.y}
                  fill="rgba(200, 76, 9, 0.18)"
                  r="16"
                />
              ) : null}
              <circle
                cx={point.x}
                cy={point.y}
                fill="#fffaf1"
                r={point.isSelected ? "8" : "7"}
                stroke={point.isSelected ? "#c84c09" : "#0b6e4f"}
                strokeWidth={point.isSelected ? "5" : "4"}
              />
              <text
                fill="#7a877f"
                fontSize="12"
                fontWeight="700"
                textAnchor="middle"
                x={point.x}
                y={height - 24}
              >
                {monthLabelForPoint(weeks, index)}
              </text>
            </g>
          ))}
        </svg>
      </div>

      <div className="running-progress-cta">
        Click any dot to inspect that week&apos;s running load.
      </div>
    </div>
  );
}

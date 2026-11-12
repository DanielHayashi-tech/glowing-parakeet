"use client";

import { useRef, useState } from "react";

import {
  ChartTooltip,
  TooltipLine,
  TooltipValue,
  VIZ,
  pointerInSvg
} from "@/app/chartKit";
import { formatPace } from "@/lib/format";

const WIDTH = 920;
const HEIGHT = 280;
// Same horizontal padding and 30-day slots as DailyDistanceChart so the two
// charts share an x-axis when stacked.
const PAD = { top: 28, right: 8, bottom: 30, left: 44 };
const HIT_RADIUS = 30;
const DOT_RADIUS = 5;

export default function PaceTrendChart({ runs, dayCount, days }) {
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);

  const innerWidth = WIDTH - PAD.left - PAD.right;
  const innerHeight = HEIGHT - PAD.top - PAD.bottom;
  const slot = innerWidth / dayCount;

  const paces = runs.map((run) => run.paceMinPerMile);
  const fastest = Math.min(...paces);
  const slowest = Math.max(...paces);
  const tickStep = slowest - fastest > 3 ? 1 : 0.5;
  const axisMin = Math.floor((fastest - 0.1) / tickStep) * tickStep;
  const axisMax = Math.ceil((slowest + 0.1) / tickStep) * tickStep;
  const ticks = [];
  for (let value = axisMin; value <= axisMax + 1e-9; value += tickStep) {
    ticks.push(Number(value.toFixed(3)));
  }

  // Faster pace (smaller number) sits higher, so "up" always means "better".
  const yFor = (pace) =>
    PAD.top + ((pace - axisMin) / (axisMax - axisMin)) * innerHeight;
  const xFor = (dayIndex) => PAD.left + slot * (dayIndex + 0.5);

  const dots = runs.map((run) => ({ ...run, cx: xFor(run.dayIndex), cy: yFor(run.paceMinPerMile) }));
  const fastestDot = dots.reduce((best, dot) => (dot.cy < best.cy ? dot : best), dots[0]);

  function nearestDot(point) {
    let best = null;
    let bestDistance = HIT_RADIUS;
    dots.forEach((dot) => {
      const distance = Math.hypot(dot.cx - point.x, dot.cy - point.y);
      if (distance < bestDistance) {
        best = dot;
        bestDistance = distance;
      }
    });
    return best;
  }

  function onPointerMove(event) {
    const point = pointerInSvg(event, svgRef.current, WIDTH, HEIGHT);
    const dot = nearestDot(point);
    if (!dot) {
      setHover(null);
      return;
    }
    const scale = point.wrapperWidth / WIDTH;
    setHover({ id: dot.id, px: dot.cx * scale, py: (dot.cy - DOT_RADIUS) * scale, wrapperWidth: point.wrapperWidth });
  }

  function onFocusDot(dot) {
    const rect = svgRef.current.getBoundingClientRect();
    const scale = rect.width / WIDTH;
    setHover({ id: dot.id, px: dot.cx * scale, py: (dot.cy - DOT_RADIUS) * scale, wrapperWidth: rect.width });
  }

  const hovered = hover ? dots.find((dot) => dot.id === hover.id) : null;
  const dateTicks = days.filter((_, index) => (dayCount - 1 - index) % 7 === 0);

  return (
    <>
      <div className="viz-legend" aria-hidden="true">
        <span className="viz-legend-item">
          <svg height="14" width="14">
            <circle cx="7" cy="7" fill={VIZ.accent} r="5" />
          </svg>
          Outdoor
        </span>
        <span className="viz-legend-item">
          <svg height="14" width="14">
            <circle cx="7" cy="7" fill={VIZ.surface} r="4" stroke={VIZ.accent} strokeWidth="2" />
          </svg>
          Treadmill
        </span>
      </div>

      <div className="chart-wrap">
        <svg
          aria-label="Average pace of each run over the last 30 days"
          className="viz-svg"
          onPointerLeave={() => setHover(null)}
          onPointerMove={onPointerMove}
          ref={svgRef}
          role="img"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        >
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                stroke={VIZ.grid}
                strokeWidth="1"
                x1={PAD.left}
                x2={WIDTH - PAD.right}
                y1={yFor(tick)}
                y2={yFor(tick)}
              />
              <text
                fill={VIZ.muted}
                fontSize="11"
                textAnchor="end"
                x={PAD.left - 10}
                y={yFor(tick) + 4}
              >
                {formatPace(tick)}
              </text>
            </g>
          ))}
          <text fill={VIZ.muted} fontSize="11" x={2} y={14}>
            ↑ faster
          </text>

          {dateTicks.map((day) => (
            <text
              fill={VIZ.muted}
              fontSize="11"
              key={day.iso}
              textAnchor="middle"
              x={xFor(days.indexOf(day))}
              y={HEIGHT - 8}
            >
              {day.label}
            </text>
          ))}

          {dots.map((dot) => {
            const isHovered = hover?.id === dot.id;
            return (
              <g
                aria-label={`${dot.label}: ${formatPace(dot.paceMinPerMile)} per mile, ${dot.miles.toFixed(2)} miles, ${dot.treadmill ? "treadmill" : "outdoor"}`}
                key={dot.id}
                onBlur={() => setHover(null)}
                onFocus={() => onFocusDot(dot)}
                role="img"
                tabIndex={0}
              >
                {isHovered ? <circle cx={dot.cx} cy={dot.cy} fill={VIZ.accentWash} r="14" /> : null}
                {/* 2px surface ring keeps overlapping dots separable */}
                <circle cx={dot.cx} cy={dot.cy} fill={VIZ.surface} r={DOT_RADIUS + 2} />
                <circle
                  cx={dot.cx}
                  cy={dot.cy}
                  fill={dot.treadmill ? VIZ.surface : isHovered ? VIZ.accentHover : VIZ.accent}
                  r={dot.treadmill ? DOT_RADIUS - 1 : DOT_RADIUS}
                  stroke={VIZ.accent}
                  strokeWidth={dot.treadmill ? 2 : 0}
                />
              </g>
            );
          })}

          <text
            fill={VIZ.ink}
            fontSize="11"
            fontWeight="700"
            textAnchor="middle"
            x={fastestDot.cx}
            y={fastestDot.cy - 14}
          >
            {formatPace(fastestDot.paceMinPerMile)}
          </text>
        </svg>

        {hovered ? (
          <ChartTooltip px={hover.px} py={hover.py} wrapperWidth={hover.wrapperWidth}>
            <TooltipValue>{formatPace(hovered.paceMinPerMile)} /mi</TooltipValue>
            <TooltipLine>
              {hovered.label} · {hovered.treadmill ? "Treadmill" : "Outdoor"}
            </TooltipLine>
            <TooltipLine>
              {hovered.miles.toFixed(2)} mi · {Math.round(hovered.minutes)} min
              {hovered.avgHeartRate ? ` · ${Math.round(hovered.avgHeartRate)} bpm` : ""}
            </TooltipLine>
          </ChartTooltip>
        ) : null}
      </div>

      <details className="viz-table">
        <summary>View as table</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Type</th>
                <th>Miles</th>
                <th>Pace</th>
                <th>Avg HR</th>
              </tr>
            </thead>
            <tbody>
              {runs
                .slice()
                .reverse()
                .map((run) => (
                  <tr key={run.id}>
                    <td>{run.label}</td>
                    <td>{run.treadmill ? "Treadmill" : "Outdoor"}</td>
                    <td>{run.miles.toFixed(2)}</td>
                    <td>{formatPace(run.paceMinPerMile)} /mi</td>
                    <td>{run.avgHeartRate ? Math.round(run.avgHeartRate) : "--"}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

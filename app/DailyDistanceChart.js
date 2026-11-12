"use client";

import { useRef, useState } from "react";

import {
  ChartTooltip,
  TooltipLine,
  TooltipValue,
  VIZ,
  niceScale,
  pointerInSvg
} from "@/app/chartKit";

const WIDTH = 920;
const HEIGHT = 250;
// Left padding matches PaceTrendChart so the two x-axes line up.
const PAD = { top: 24, right: 8, bottom: 30, left: 44 };
const BAR_MAX_WIDTH = 20;

function columnPath(x, width, top, base) {
  const radius = Math.min(4, (base - top) / 2, width / 2);
  return [
    `M ${x} ${base}`,
    `L ${x} ${top + radius}`,
    `Q ${x} ${top} ${x + radius} ${top}`,
    `L ${x + width - radius} ${top}`,
    `Q ${x + width} ${top} ${x + width} ${top + radius}`,
    `L ${x + width} ${base}`,
    "Z"
  ].join(" ");
}

function durationLabel(minutes) {
  const hours = Math.floor(minutes / 60);
  const remainder = Math.round(minutes % 60);
  return hours > 0 ? `${hours}h ${remainder}m` : `${remainder} min`;
}

export default function DailyDistanceChart({ days }) {
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);

  const innerWidth = WIDTH - PAD.left - PAD.right;
  const innerHeight = HEIGHT - PAD.top - PAD.bottom;
  const baseline = PAD.top + innerHeight;
  const slot = innerWidth / days.length;
  const barWidth = Math.min(BAR_MAX_WIDTH, slot - 6);

  const maxMiles = days.reduce((max, day) => Math.max(max, day.miles), 0);
  const { max: axisMax, ticks } = niceScale(maxMiles);
  const yFor = (miles) => baseline - (miles / axisMax) * innerHeight;

  // Label only the tallest column (latest one on ties), not every bar.
  let peakIndex = -1;
  days.forEach((day, index) => {
    if (day.miles > 0 && (peakIndex === -1 || day.miles >= days[peakIndex].miles)) {
      peakIndex = index;
    }
  });

  function show(event, index) {
    const point = pointerInSvg(event, svgRef.current, WIDTH, HEIGHT);
    const scale = point.wrapperWidth / WIDTH;
    setHover({
      index,
      px: point.px,
      py: yFor(days[index].miles) * scale,
      wrapperWidth: point.wrapperWidth
    });
  }

  function showFromFocus(index) {
    const rect = svgRef.current.getBoundingClientRect();
    const px = ((PAD.left + slot * (index + 0.5)) / WIDTH) * rect.width;
    const py = (yFor(days[index].miles) / HEIGHT) * rect.height;
    setHover({ index, px, py, wrapperWidth: rect.width });
  }

  const hoveredDay = hover ? days[hover.index] : null;
  const runDays = days.filter((day) => day.runCount > 0);

  return (
    <>
      <div className="chart-wrap">
        <svg
          aria-label="Running distance for each of the last 30 days"
          className="viz-svg"
          ref={svgRef}
          role="img"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        >
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                stroke={tick === 0 ? VIZ.baseline : VIZ.grid}
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
                {tick}
              </text>
            </g>
          ))}
          <text fill={VIZ.muted} fontSize="11" x={PAD.left - 10} y={12} textAnchor="end">
            mi
          </text>

          {days.map((day, index) => {
            const x = PAD.left + slot * index + (slot - barWidth) / 2;
            const isHovered = hover?.index === index;
            return (
              <g key={day.iso}>
                {day.miles > 0 ? (
                  <path
                    d={columnPath(x, barWidth, yFor(day.miles), baseline)}
                    fill={isHovered ? VIZ.accentHover : VIZ.accent}
                  />
                ) : null}
                {(days.length - 1 - index) % 7 === 0 ? (
                  <text
                    fill={VIZ.muted}
                    fontSize="11"
                    textAnchor="middle"
                    x={x + barWidth / 2}
                    y={HEIGHT - 8}
                  >
                    {day.label}
                  </text>
                ) : null}
                {index === peakIndex ? (
                  <text
                    fill={VIZ.ink}
                    fontSize="11"
                    fontWeight="700"
                    textAnchor="middle"
                    x={x + barWidth / 2}
                    y={yFor(day.miles) - 6}
                  >
                    {day.miles.toFixed(1)}
                  </text>
                ) : null}
                <rect
                  aria-label={`${day.label}: ${day.miles.toFixed(2)} miles`}
                  fill="transparent"
                  height={innerHeight + PAD.top}
                  onBlur={() => setHover(null)}
                  onFocus={() => showFromFocus(index)}
                  onPointerLeave={() => setHover(null)}
                  onPointerMove={(event) => show(event, index)}
                  tabIndex={day.runCount > 0 ? 0 : -1}
                  width={slot}
                  x={PAD.left + slot * index}
                  y={0}
                />
              </g>
            );
          })}
        </svg>

        {hoveredDay ? (
          <ChartTooltip px={hover.px} py={hover.py} wrapperWidth={hover.wrapperWidth}>
            <TooltipValue>{hoveredDay.miles.toFixed(2)} mi</TooltipValue>
            <TooltipLine>{hoveredDay.label}</TooltipLine>
            {hoveredDay.runCount > 0 ? (
              <TooltipLine>
                {hoveredDay.runCount} run{hoveredDay.runCount === 1 ? "" : "s"} ·{" "}
                {durationLabel(hoveredDay.minutes)}
              </TooltipLine>
            ) : (
              <TooltipLine>Rest day</TooltipLine>
            )}
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
                <th>Runs</th>
                <th>Miles</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {runDays
                .slice()
                .reverse()
                .map((day) => (
                  <tr key={day.iso}>
                    <td>{day.label}</td>
                    <td>{day.runCount}</td>
                    <td>{day.miles.toFixed(2)}</td>
                    <td>{durationLabel(day.minutes)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        <p className="muted">Days without a run are left out.</p>
      </details>
    </>
  );
}

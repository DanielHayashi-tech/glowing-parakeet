"use client";

import { useRef, useState } from "react";

import {
  ChartTooltip,
  TooltipLine,
  TooltipValue,
  VIZ,
  pointerInSvg
} from "@/app/chartKit";
import { formatHours as hoursLabel } from "@/lib/format";

const PAD = { top: 24, right: 8, bottom: 30, left: 44 };

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

function pickStep(range, steps) {
  return steps.find((step) => range / step <= 4) ?? steps[steps.length - 1];
}

// Nightly sleep duration. Same slots and left padding as the training charts so
// the x-axes line up when stacked.
export function SleepChart({ days }) {
  const WIDTH = 920;
  const HEIGHT = 240;
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);

  const innerWidth = WIDTH - PAD.left - PAD.right;
  const innerHeight = HEIGHT - PAD.top - PAD.bottom;
  const baseline = PAD.top + innerHeight;
  const slot = innerWidth / days.length;
  const barWidth = Math.min(20, slot - 6);

  const maxHours = Math.max(8, ...days.map((day) => day.sleepHours ?? 0));
  const step = pickStep(maxHours, [2, 4]);
  const axisMax = Math.ceil(maxHours / step) * step;
  const ticks = [];
  for (let value = 0; value <= axisMax; value += step) {
    ticks.push(value);
  }
  const yFor = (hours) => baseline - (hours / axisMax) * innerHeight;

  const latestIndex = days.reduce((last, day, index) => (day.sleepHours !== null ? index : last), -1);

  function place(index, event) {
    const rect = svgRef.current.getBoundingClientRect();
    const scale = rect.width / WIDTH;
    const point = event ? pointerInSvg(event, svgRef.current, WIDTH, HEIGHT) : null;
    setHover({
      index,
      px: point ? point.px : (PAD.left + slot * (index + 0.5)) * scale,
      py: yFor(days[index].sleepHours ?? 0) * scale,
      wrapperWidth: rect.width
    });
  }

  const hovered = hover ? days[hover.index] : null;
  const nights = days.filter((day) => day.sleepHours !== null);

  return (
    <>
      <div className="chart-wrap">
        <svg
          aria-label="Hours slept each night over the last 30 days"
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
              <text fill={VIZ.muted} fontSize="11" textAnchor="end" x={PAD.left - 10} y={yFor(tick) + 4}>
                {tick}
              </text>
            </g>
          ))}
          <text fill={VIZ.muted} fontSize="11" textAnchor="end" x={PAD.left - 10} y={12}>
            hours
          </text>

          {days.map((day, index) => {
            const x = PAD.left + slot * index + (slot - barWidth) / 2;
            const isHovered = hover?.index === index;
            return (
              <g key={day.iso}>
                {day.sleepHours !== null ? (
                  <path
                    d={columnPath(x, barWidth, yFor(day.sleepHours), baseline)}
                    fill={isHovered ? VIZ.recoveryHover : VIZ.recovery}
                  />
                ) : null}
                {(days.length - 1 - index) % 7 === 0 ? (
                  <text fill={VIZ.muted} fontSize="11" textAnchor="middle" x={x + barWidth / 2} y={HEIGHT - 8}>
                    {day.label}
                  </text>
                ) : null}
                {index === latestIndex ? (
                  <text
                    fill={VIZ.ink}
                    fontSize="11"
                    fontWeight="700"
                    textAnchor="middle"
                    x={x + barWidth / 2}
                    y={yFor(day.sleepHours) - 6}
                  >
                    {hoursLabel(day.sleepHours)}
                  </text>
                ) : null}
                <rect
                  aria-label={`${day.label}: ${hoursLabel(day.sleepHours)} of sleep`}
                  fill="transparent"
                  height={innerHeight + PAD.top}
                  onBlur={() => setHover(null)}
                  onFocus={() => place(index, null)}
                  onPointerLeave={() => setHover(null)}
                  onPointerMove={(event) => place(index, event)}
                  tabIndex={day.sleepHours !== null ? 0 : -1}
                  width={slot}
                  x={PAD.left + slot * index}
                  y={0}
                />
              </g>
            );
          })}
        </svg>

        {hovered ? (
          <ChartTooltip px={hover.px} py={hover.py} wrapperWidth={hover.wrapperWidth}>
            <TooltipValue>{hoursLabel(hovered.sleepHours)}</TooltipValue>
            <TooltipLine>
              Night ending {hovered.label}
              {hovered.sleepScore != null ? ` · score ${hovered.sleepScore}` : ""}
            </TooltipLine>
            {hovered.deepHours != null ? (
              <TooltipLine>
                Deep {hoursLabel(hovered.deepHours)} · Light {hoursLabel(hovered.lightHours)} · REM{" "}
                {hoursLabel(hovered.remHours)}
              </TooltipLine>
            ) : null}
          </ChartTooltip>
        ) : null}
      </div>

      <details className="viz-table">
        <summary>View as table</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Night ending</th>
                <th>Sleep</th>
                <th>Score</th>
                <th>Deep</th>
                <th>Light</th>
                <th>REM</th>
                <th>Awake</th>
              </tr>
            </thead>
            <tbody>
              {nights
                .slice()
                .reverse()
                .map((day) => (
                  <tr key={day.iso}>
                    <td>{day.label}</td>
                    <td>{hoursLabel(day.sleepHours)}</td>
                    <td>{day.sleepScore ?? "--"}</td>
                    <td>{hoursLabel(day.deepHours)}</td>
                    <td>{hoursLabel(day.lightHours)}</td>
                    <td>{hoursLabel(day.remHours)}</td>
                    <td>{hoursLabel(day.awakeHours)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

// One measure as a line over 30 days, with an optional shaded "normal" range.
// valueKey / bandLowKey / bandHighKey pick fields off each day.
export function TrendChart({ days, valueKey, bandLowKey, bandHighKey, unit, label, statusKey, bandNote }) {
  const WIDTH = 450;
  const HEIGHT = 230;
  const pad = { top: 16, right: 12, bottom: 30, left: 38 };
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);

  const innerWidth = WIDTH - pad.left - pad.right;
  const innerHeight = HEIGHT - pad.top - pad.bottom;
  const slot = innerWidth / days.length;
  const xFor = (index) => pad.left + slot * (index + 0.5);

  const values = days.map((day) => day[valueKey]).filter((value) => value != null);
  if (values.length === 0) {
    return <div className="empty-state">No {label.toLowerCase()} data yet.</div>;
  }
  const bandValues = bandLowKey
    ? days.flatMap((day) => [day[bandLowKey], day[bandHighKey]]).filter((value) => value != null)
    : [];
  const low = Math.min(...values, ...bandValues);
  const high = Math.max(...values, ...bandValues);
  const step = pickStep(high - low || 1, [1, 2, 5, 10, 20]);
  const axisMin = Math.floor(low / step) * step;
  const axisMax = Math.max(Math.ceil(high / step) * step, axisMin + step);
  const ticks = [];
  for (let value = axisMin; value <= axisMax + 1e-9; value += step) {
    ticks.push(value);
  }
  const yFor = (value) => pad.top + (1 - (value - axisMin) / (axisMax - axisMin)) * innerHeight;

  // Break the line where a day has no value instead of bridging the gap.
  const segments = [];
  let current = [];
  days.forEach((day, index) => {
    if (day[valueKey] == null) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push(index);
    }
  });
  if (current.length) segments.push(current);
  const linePath = segments
    .map((segment) =>
      segment
        .map((index, i) => `${i === 0 ? "M" : "L"} ${xFor(index).toFixed(1)} ${yFor(days[index][valueKey]).toFixed(1)}`)
        .join(" ")
    )
    .join(" ");

  const bandIndexes = bandLowKey
    ? days.map((day, index) => index).filter((index) => days[index][bandLowKey] != null && days[index][bandHighKey] != null)
    : [];
  const bandPath = bandIndexes.length > 1
    ? [
        ...bandIndexes.map((index, i) => `${i === 0 ? "M" : "L"} ${xFor(index).toFixed(1)} ${yFor(days[index][bandHighKey]).toFixed(1)}`),
        ...[...bandIndexes].reverse().map((index) => `L ${xFor(index).toFixed(1)} ${yFor(days[index][bandLowKey]).toFixed(1)}`),
        "Z"
      ].join(" ")
    : null;

  const withValues = days.map((day, index) => index).filter((index) => days[index][valueKey] != null);
  const lastIndex = withValues[withValues.length - 1];

  function nearest(point) {
    const guess = Math.round((point.x - pad.left) / slot - 0.5);
    return withValues.reduce(
      (best, index) => (Math.abs(index - guess) < Math.abs(best - guess) ? index : best),
      withValues[0]
    );
  }

  function place(index) {
    const rect = svgRef.current.getBoundingClientRect();
    const scale = rect.width / WIDTH;
    setHover({
      index,
      px: xFor(index) * scale,
      py: yFor(days[index][valueKey]) * scale - 6,
      wrapperWidth: rect.width
    });
  }

  function onKeyDown(event) {
    if (event.key === "Escape") {
      setHover(null);
      return;
    }
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
      return;
    }
    event.preventDefault();
    const position = hover ? withValues.indexOf(hover.index) : withValues.length;
    const next = Math.min(
      Math.max(position + (event.key === "ArrowRight" ? 1 : -1), 0),
      withValues.length - 1
    );
    place(withValues[next]);
  }

  const hovered = hover ? days[hover.index] : null;
  const shownIndex = hover ? hover.index : null;

  return (
    <>
      <div className="chart-wrap">
        <svg
          aria-label={`${label} over the last 30 days. Use the left and right arrow keys to read values.`}
          className="viz-svg"
          onBlur={() => setHover(null)}
          onKeyDown={onKeyDown}
          onPointerLeave={() => setHover(null)}
          onPointerMove={(event) => place(nearest(pointerInSvg(event, svgRef.current, WIDTH, HEIGHT)))}
          ref={svgRef}
          role="img"
          tabIndex={0}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        >
          {ticks.map((tick) => (
            <g key={tick}>
              <line stroke={VIZ.grid} strokeWidth="1" x1={pad.left} x2={WIDTH - pad.right} y1={yFor(tick)} y2={yFor(tick)} />
              <text fill={VIZ.muted} fontSize="11" textAnchor="end" x={pad.left - 8} y={yFor(tick) + 4}>
                {tick}
              </text>
            </g>
          ))}
          {days.map((day, index) =>
            (days.length - 1 - index) % 7 === 0 ? (
              <text fill={VIZ.muted} fontSize="11" key={day.iso} textAnchor="middle" x={xFor(index)} y={HEIGHT - 8}>
                {day.label}
              </text>
            ) : null
          )}

          {bandPath ? <path d={bandPath} fill={VIZ.recoveryWash} /> : null}
          <path d={linePath} fill="none" stroke={VIZ.recovery} strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />

          {/* end dot: the latest value, with a surface ring */}
          <circle cx={xFor(lastIndex)} cy={yFor(days[lastIndex][valueKey])} fill={VIZ.surface} r="6" />
          <circle cx={xFor(lastIndex)} cy={yFor(days[lastIndex][valueKey])} fill={VIZ.recovery} r="4" />

          {hovered ? (
            <g>
              <line stroke={VIZ.baseline} strokeWidth="1" x1={xFor(shownIndex)} x2={xFor(shownIndex)} y1={pad.top} y2={HEIGHT - pad.bottom} />
              <circle cx={xFor(shownIndex)} cy={yFor(hovered[valueKey])} fill={VIZ.surface} r="6" />
              <circle cx={xFor(shownIndex)} cy={yFor(hovered[valueKey])} fill={VIZ.recovery} r="4" />
            </g>
          ) : null}
        </svg>

        {hovered ? (
          <ChartTooltip px={hover.px} py={hover.py} wrapperWidth={hover.wrapperWidth}>
            <TooltipValue>
              {hovered[valueKey]} {unit}
            </TooltipValue>
            <TooltipLine>{hovered.label}</TooltipLine>
            {statusKey && hovered[statusKey] ? (
              <TooltipLine>{hovered[statusKey].toLowerCase()}</TooltipLine>
            ) : null}
          </ChartTooltip>
        ) : null}
      </div>
      {bandNote && bandPath ? <p className="muted viz-note">{bandNote}</p> : null}

      <details className="viz-table">
        <summary>View as table</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>{label}</th>
                {statusKey ? <th>Status</th> : null}
              </tr>
            </thead>
            <tbody>
              {withValues
                .slice()
                .reverse()
                .map((index) => (
                  <tr key={days[index].iso}>
                    <td>{days[index].label}</td>
                    <td>
                      {days[index][valueKey]} {unit}
                    </td>
                    {statusKey ? <td>{days[index][statusKey] ?? "--"}</td> : null}
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

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
import { formatPace } from "@/lib/format";

const PROFILE_WIDTH = 560;
const PROFILE_HEIGHT = 150;
const PROFILE_PAD = { top: 14, right: 8, bottom: 24, left: 44 };

function pickStep(range, steps) {
  return steps.find((step) => range / step <= 3.5) ?? steps[steps.length - 1];
}

function percentile(sortedValues, fraction) {
  const index = Math.min(sortedValues.length - 1, Math.floor(sortedValues.length * fraction));
  return sortedValues[index];
}

// One measure against distance. Pace is drawn with faster at the top.
function ProfileChart({
  points,
  totalMiles,
  valueFor,
  color,
  label,
  formatTick,
  tickSteps,
  faster,
  showDistanceAxis,
  hover,
  onHover,
  renderTooltip
}) {
  const svgRef = useRef(null);
  const hoverIndex = hover ? hover.index : null;
  const usable = points
    .map((point, index) => ({ index, miles: point.miles, value: valueFor(point) }))
    .filter((point) => Number.isFinite(point.value));

  const innerWidth = PROFILE_WIDTH - PROFILE_PAD.left - PROFILE_PAD.right;
  const innerHeight = PROFILE_HEIGHT - PROFILE_PAD.top - PROFILE_PAD.bottom;

  const sorted = usable.map((point) => point.value).sort((a, b) => a - b);
  // Trim the extremes (stops, GPS hiccups) so they can't flatten the line;
  // values outside the axis are clamped to its edge.
  const low = percentile(sorted, 0.04);
  const high = percentile(sorted, 0.96);
  const step = pickStep(high - low || 1, tickSteps);
  const axisMin = Math.floor(low / step) * step;
  const axisMax = Math.ceil(high / step) * step;

  const xFor = (miles) => PROFILE_PAD.left + (miles / totalMiles) * innerWidth;
  const clamp = (value) => Math.min(Math.max(value, axisMin), axisMax);
  const yFor = (value) => {
    const fraction = (clamp(value) - axisMin) / (axisMax - axisMin);
    return PROFILE_PAD.top + (faster ? fraction : 1 - fraction) * innerHeight;
  };

  const line = usable
    .map((point, i) => `${i === 0 ? "M" : "L"} ${xFor(point.miles).toFixed(1)} ${yFor(point.value).toFixed(1)}`)
    .join(" ");

  const yTicks = [];
  for (let value = axisMin; value <= axisMax + 1e-9; value += step) {
    yTicks.push(Number(value.toFixed(3)));
  }
  const xTicks = niceScale(totalMiles, 4).ticks.filter((tick) => tick <= totalMiles);

  function handleMove(event) {
    const point = pointerInSvg(event, svgRef.current, PROFILE_WIDTH, PROFILE_HEIGHT);
    const miles = ((point.x - PROFILE_PAD.left) / innerWidth) * totalMiles;
    let best = 0;
    let bestGap = Infinity;
    points.forEach((candidate, index) => {
      const gap = Math.abs(candidate.miles - miles);
      if (gap < bestGap) {
        best = index;
        bestGap = gap;
      }
    });
    onHover({ index: best, px: point.px, py: point.py, wrapperWidth: point.wrapperWidth, source: label });
  }

  const hovered = hoverIndex !== null ? points[hoverIndex] : null;
  const hoveredValue = hovered ? valueFor(hovered) : null;

  return (
    <div className="chart-wrap">
      <svg
        aria-label={`${label} across the run`}
        className="viz-svg"
        onPointerLeave={() => onHover(null)}
        onPointerMove={handleMove}
        ref={svgRef}
        role="img"
        viewBox={`0 0 ${PROFILE_WIDTH} ${PROFILE_HEIGHT}`}
      >
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              stroke={VIZ.grid}
              strokeWidth="1"
              x1={PROFILE_PAD.left}
              x2={PROFILE_WIDTH - PROFILE_PAD.right}
              y1={yFor(tick)}
              y2={yFor(tick)}
            />
            <text fill={VIZ.muted} fontSize="11" textAnchor="end" x={PROFILE_PAD.left - 8} y={yFor(tick) + 4}>
              {formatTick(tick)}
            </text>
          </g>
        ))}
        {showDistanceAxis
          ? xTicks.map((tick) => (
              <text
                fill={VIZ.muted}
                fontSize="11"
                key={tick}
                textAnchor="middle"
                x={xFor(tick)}
                y={PROFILE_HEIGHT - 6}
              >
                {tick === 0 ? "0 mi" : tick}
              </text>
            ))
          : null}

        <path d={line} fill="none" stroke={color} strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />

        {hovered && Number.isFinite(hoveredValue) ? (
          <g>
            <line
              stroke={VIZ.baseline}
              strokeWidth="1"
              x1={xFor(hovered.miles)}
              x2={xFor(hovered.miles)}
              y1={PROFILE_PAD.top}
              y2={PROFILE_HEIGHT - PROFILE_PAD.bottom}
            />
            <circle cx={xFor(hovered.miles)} cy={yFor(hoveredValue)} fill={VIZ.surface} r="6" />
            <circle cx={xFor(hovered.miles)} cy={yFor(hoveredValue)} fill={color} r="4" />
          </g>
        ) : null}
      </svg>

      {hover && hover.source === label ? (
        <ChartTooltip px={hover.px} py={hover.py} wrapperWidth={hover.wrapperWidth}>
          {renderTooltip(points[hover.index])}
        </ChartTooltip>
      ) : null}
    </div>
  );
}

export default function LatestRunPanel({ route }) {
  const [hover, setHover] = useState(null);

  if (!route) {
    return (
      <div className="empty-state">
        No outdoor run with GPS yet. Treadmill runs don&apos;t record a route.
      </div>
    );
  }

  const { points } = route;
  const totalMiles = points[points.length - 1].miles || route.miles;

  const mapSize = 300;
  const mapPad = 18;
  const mapWidth = route.aspect * mapSize + mapPad * 2;
  const mapHeight = route.heightRatio * mapSize + mapPad * 2;
  const mx = (point) => mapPad + point.x * mapSize;
  const my = (point) => mapPad + point.y * mapSize;

  const routePath = points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${mx(point).toFixed(1)} ${my(point).toFixed(1)}`)
    .join(" ");
  const start = points[0];
  const finish = points[points.length - 1];
  const hovered = hover ? points[hover.index] : null;

  const renderTooltip = (point) => (
    <>
      <TooltipValue>Mile {point.miles.toFixed(2)}</TooltipValue>
      <TooltipLine>
        {point.paceMinPerMile ? `${formatPace(point.paceMinPerMile)} /mi` : "Pace --"}
        {point.heartRate ? ` · ${Math.round(point.heartRate)} bpm` : ""}
      </TooltipLine>
    </>
  );

  return (
    <div className="run-panel">
      <div className="run-map">
        <svg
          aria-label={`Route of the ${route.dateLabel} run`}
          className="viz-svg"
          role="img"
          viewBox={`0 0 ${mapWidth.toFixed(0)} ${mapHeight.toFixed(0)}`}
        >
          <path d={routePath} fill="none" stroke={VIZ.accent} strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" />
          <circle cx={mx(start)} cy={my(start)} fill={VIZ.surface} r="7" />
          <circle cx={mx(start)} cy={my(start)} fill={VIZ.surface} r="4" stroke={VIZ.ink} strokeWidth="2" />
          <circle cx={mx(finish)} cy={my(finish)} fill={VIZ.surface} r="7" />
          <circle cx={mx(finish)} cy={my(finish)} fill={VIZ.accent} r="4.5" />
          {hovered ? (
            <g>
              <circle cx={mx(hovered)} cy={my(hovered)} fill={VIZ.surface} r="8" />
              <circle cx={mx(hovered)} cy={my(hovered)} fill={VIZ.ink} r="5" />
            </g>
          ) : null}
        </svg>
        <div className="viz-legend" aria-hidden="true">
          <span className="viz-legend-item">
            <svg height="14" width="14">
              <circle cx="7" cy="7" fill={VIZ.surface} r="4" stroke={VIZ.ink} strokeWidth="2" />
            </svg>
            Start
          </span>
          <span className="viz-legend-item">
            <svg height="14" width="14">
              <circle cx="7" cy="7" fill={VIZ.accent} r="4.5" />
            </svg>
            Finish
          </span>
        </div>
      </div>

      <div className="run-profiles">
        <div className="run-profile-label">Pace (faster is higher)</div>
        <ProfileChart
          color={VIZ.accent}
          faster
          formatTick={(value) => formatPace(value)}
          tickSteps={[0.5, 1, 2, 5]}
          hover={hover}
          label="Pace"
          onHover={setHover}
          renderTooltip={renderTooltip}
          points={points}
          totalMiles={totalMiles}
          valueFor={(point) => point.paceMinPerMile}
        />
        <div className="run-profile-label">Heart rate (bpm)</div>
        <ProfileChart
          color={VIZ.heartRate}
          formatTick={(value) => Math.round(value)}
          tickSteps={[5, 10, 20, 25]}
          hover={hover}
          label="Heart rate"
          onHover={setHover}
          renderTooltip={renderTooltip}
          points={points}
          showDistanceAxis
          totalMiles={totalMiles}
          valueFor={(point) => point.heartRate}
        />

      </div>
    </div>
  );
}

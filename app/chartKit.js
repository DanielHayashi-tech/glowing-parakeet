"use client";

// Shared pieces for the dashboard charts. Colors mirror the CSS tokens in
// globals.css (--viz-*); SVG attributes can't read CSS variables for every
// property we need, so the values live here too. Orange and blue were checked
// with the dataviz palette validator against the panel surface.
export const VIZ = {
  accent: "#c84c09",
  accentHover: "#e0642a",
  accentWash: "rgba(200, 76, 9, 0.16)",
  heartRate: "#3366cc",
  surface: "#fffaf1",
  grid: "#e6dccb",
  baseline: "#cbbda5",
  ink: "#13201b",
  muted: "#59665f"
};

// Round a maximum up to a clean axis bound and return the tick values.
export function niceScale(maxValue, targetTicks = 4) {
  const safe = Math.max(maxValue, 1);
  const rough = safe / targetTicks;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const residual = rough / magnitude;
  const factor = residual <= 1 ? 1 : residual <= 2 ? 2 : residual <= 5 ? 5 : 10;
  const step = factor * magnitude;
  const max = Math.ceil(safe / step) * step;
  const ticks = [];
  for (let value = 0; value <= max + 1e-9; value += step) {
    ticks.push(Number(value.toFixed(6)));
  }
  return { max, ticks };
}

// Pointer position in both SVG viewBox units and wrapper pixels. The wrapper
// holds only the svg, so the svg rect is the wrapper rect.
export function pointerInSvg(event, svgElement, width, height) {
  const rect = svgElement.getBoundingClientRect();
  const px = event.clientX - rect.left;
  const py = event.clientY - rect.top;
  return {
    x: (px / rect.width) * width,
    y: (py / rect.height) * height,
    px,
    py,
    wrapperWidth: rect.width
  };
}

export function ChartTooltip({ px, py, wrapperWidth, children }) {
  const half = 96;
  const left = Math.min(Math.max(px, half), Math.max(wrapperWidth - half, half));
  return (
    <div className="chart-tooltip" role="status" style={{ left, top: py }}>
      {children}
    </div>
  );
}

export function TooltipValue({ children }) {
  return <div className="chart-tooltip-value">{children}</div>;
}

export function TooltipLine({ children }) {
  return <div className="chart-tooltip-line">{children}</div>;
}

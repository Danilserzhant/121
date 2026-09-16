"use client";

import { useChartWidth } from "./util";

export function Sparkline({ values, height = 56 }: { values: number[]; height?: number }) {
  const { ref, width } = useChartWidth(400);
  const max = Math.max(1, ...values);
  const x = (i: number) => (values.length < 2 ? width / 2 : (i / (values.length - 1)) * width);
  const y = (v: number) => height - 4 - (v / max) * (height - 10);
  return (
    <div ref={ref}>
      <svg width={width} height={height} role="img" aria-label="Сообщения по дням">
        <line x1={0} x2={width} y1={height - 4} y2={height - 4} stroke="var(--grid)" strokeWidth={1} />
        <polyline
          fill="none"
          stroke="var(--series-1)"
          strokeWidth={2}
          strokeLinejoin="round"
          points={values.map((v, i) => `${x(i)},${y(v)}`).join(" ")}
        />
      </svg>
    </div>
  );
}

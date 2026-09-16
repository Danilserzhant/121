"use client";

import { useState } from "react";
import { Legend, Tooltip, TooltipRow, niceTicks, shortDay, useChartWidth } from "./util";

export type FlowPoint = { day: string; joins: number; leaves: number };

/**
 * Приток вверх, отток вниз от нулевой линии: видно и объём, и знак.
 * Одна ось — обе серии в одних единицах (людях).
 */
export function FlowChart({ data, height = 220 }: { data: FlowPoint[]; height?: number }) {
  const { ref, width } = useChartWidth();
  const [hover, setHover] = useState<number | null>(null);

  const pad = { top: 12, right: 12, bottom: 22, left: 38 };
  const innerW = Math.max(10, width - pad.left - pad.right);
  const innerH = height - pad.top - pad.bottom;
  const max = Math.max(1, ...data.map((d) => Math.max(d.joins, d.leaves)));
  const ticks = niceTicks(max, 3);
  const top = ticks[ticks.length - 1] || 1;
  const zeroY = pad.top + innerH / 2;
  const scale = (v: number) => (v / top) * (innerH / 2);
  const band = innerW / Math.max(1, data.length);
  const barW = Math.max(1, Math.min(14, band - 2));

  const point = hover !== null ? data[hover] : null;

  return (
    <div ref={ref} className="relative">
      <Legend
        items={[
          { color: "var(--series-1)", label: "Пришли" },
          { color: "var(--series-2)", label: "Ушли" },
        ]}
      />
      <svg
        width={width}
        height={height}
        role="img"
        aria-label="Приток и отток участников по дням"
        onMouseLeave={() => setHover(null)}
      >
        {[...ticks].reverse().map((t) =>
          [1, -1].map((sign) => (
            <g key={`${t}-${sign}`}>
              <line
                x1={pad.left}
                x2={width - pad.right}
                y1={zeroY - sign * scale(t)}
                y2={zeroY - sign * scale(t)}
                stroke={t === 0 ? "var(--axis)" : "var(--grid)"}
                strokeWidth={1}
              />
              {t > 0 || sign === 1 ? (
                <text
                  x={pad.left - 6}
                  y={zeroY - sign * scale(t) + 3}
                  textAnchor="end"
                  fontSize={10}
                  className="tnum"
                  fill="var(--text-muted)"
                >
                  {t === 0 ? 0 : t}
                </text>
              ) : null}
            </g>
          )),
        )}

        {data.map((d, i) => {
          const x = pad.left + i * band + (band - barW) / 2;
          const up = scale(d.joins);
          const down = scale(d.leaves);
          return (
            <g key={d.day}>
              <rect
                x={pad.left + i * band}
                y={pad.top}
                width={band}
                height={innerH}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
              />
              {hover === i ? (
                <rect x={pad.left + i * band} y={pad.top} width={band} height={innerH} fill="var(--hover)" />
              ) : null}
              <rect x={x} y={zeroY - up} width={barW} height={Math.max(0, up)} rx={2} fill="var(--series-1)" />
              <rect x={x} y={zeroY + 1} width={barW} height={Math.max(0, down)} rx={2} fill="var(--series-2)" />
            </g>
          );
        })}

        {data.map((d, i) =>
          i % Math.ceil(data.length / Math.max(2, Math.floor(innerW / 70))) === 0 ? (
            <text
              key={`lbl-${d.day}`}
              x={pad.left + i * band + band / 2}
              y={height - 6}
              textAnchor="middle"
              fontSize={10}
              fill="var(--text-muted)"
            >
              {shortDay(d.day)}
            </text>
          ) : null,
        )}
      </svg>

      {point && hover !== null ? (
        <Tooltip x={pad.left + hover * band + band / 2} y={8} width={width}>
          <div className="mb-1 font-medium">{shortDay(point.day)}</div>
          <TooltipRow color="var(--series-1)" label="Пришли" value={String(point.joins)} />
          <TooltipRow color="var(--series-2)" label="Ушли" value={String(point.leaves)} />
          <TooltipRow label="Чистый прирост" value={`${point.joins - point.leaves > 0 ? "+" : ""}${point.joins - point.leaves}`} />
        </Tooltip>
      ) : null}
    </div>
  );
}

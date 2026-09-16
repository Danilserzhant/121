"use client";

import { useState } from "react";
import { Legend, Tooltip, TooltipRow, niceTicks, shortDay, useChartWidth } from "./util";

export type Series = { key: string; label: string; color: string; values: number[] };

/** Линии с общей осью Y. Две шкалы на одном графике не рисуем никогда. */
export function LineChart({
  labels,
  series,
  height = 220,
  valueUnit = "number",
  labelKind = "date",
}: {
  labels: string[];
  series: Series[];
  height?: number;
  /** Подпись значения по оси Y и в подсказке. */
  valueUnit?: "number" | "percent";
  /** Подписи по оси X — даты ISO или готовый текст. */
  labelKind?: "date" | "text";
}) {
  const valueFormat = (v: number) => (valueUnit === "percent" ? `${Math.round(v)}%` : String(v));
  const labelFormat = (l: string) => (labelKind === "date" ? shortDay(l) : l);
  const { ref, width } = useChartWidth();
  const [hover, setHover] = useState<number | null>(null);

  const pad = { top: 12, right: 12, bottom: 22, left: 44 };
  const innerW = Math.max(10, width - pad.left - pad.right);
  const innerH = height - pad.top - pad.bottom;
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const ticks = niceTicks(max, 4);
  const top = ticks[ticks.length - 1] || 1;
  const x = (i: number) => pad.left + (labels.length === 1 ? innerW / 2 : (i / (labels.length - 1)) * innerW);
  const y = (v: number) => pad.top + innerH - (v / top) * innerH;

  return (
    <div ref={ref} className="relative">
      {series.length > 1 ? <Legend items={series.map((s) => ({ color: s.color, label: s.label }))} /> : null}
      <svg width={width} height={height} role="img" aria-label={series.map((s) => s.label).join(", ")} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--axis)" : "var(--grid)"} strokeWidth={1} />
            <text x={pad.left - 6} y={y(t) + 3} textAnchor="end" fontSize={10} className="tnum" fill="var(--text-muted)">
              {valueFormat(t)}
            </text>
          </g>
        ))}

        {series.map((s) => (
          <polyline
            key={s.key}
            fill="none"
            stroke={s.color}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ")}
          />
        ))}

        {hover !== null ? (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={pad.top} y2={pad.top + innerH} stroke="var(--axis)" strokeWidth={1} />
            {series.map((s) => (
              <circle key={s.key} cx={x(hover)} cy={y(s.values[hover] ?? 0)} r={4.5} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
            ))}
          </g>
        ) : null}

        {labels.map((l, i) => (
          <rect
            key={`hit-${l}`}
            x={x(i) - innerW / Math.max(1, labels.length) / 2}
            y={pad.top}
            width={innerW / Math.max(1, labels.length)}
            height={innerH}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}

        {labels.map((l, i) =>
          i % Math.ceil(labels.length / Math.max(2, Math.floor(innerW / 70))) === 0 ? (
            <text key={`lbl-${l}`} x={x(i)} y={height - 6} textAnchor="middle" fontSize={10} fill="var(--text-muted)">
              {labelFormat(l)}
            </text>
          ) : null,
        )}
      </svg>

      {hover !== null ? (
        <Tooltip x={x(hover)} y={8} width={width}>
          <div className="mb-1 font-medium">{labelFormat(labels[hover])}</div>
          {series.map((s) => (
            <TooltipRow key={s.key} color={s.color} label={s.label} value={valueFormat(s.values[hover] ?? 0)} />
          ))}
        </Tooltip>
      ) : null}
    </div>
  );
}

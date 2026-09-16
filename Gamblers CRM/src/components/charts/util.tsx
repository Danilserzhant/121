"use client";

import { useEffect, useRef, useState } from "react";

/** Ширина контейнера — чтобы SVG не растягивался вместе с подписями. */
export function useChartWidth(fallback = 720) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}

export function niceTicks(max: number, count = 4) {
  if (max <= 0) return [0];
  const raw = max / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  const ticks: number[] = [];
  // Последняя засечка обязана накрывать максимум, иначе линия уходит за пределы области.
  for (let v = 0; v < max - step * 0.001 || ticks.length < 2; v += step) ticks.push(Number(v.toFixed(6)));
  ticks.push(Number((ticks[ticks.length - 1] + step).toFixed(6)));
  return ticks;
}

export function Tooltip({
  x,
  y,
  width,
  children,
}: {
  x: number;
  y: number;
  width: number;
  children: React.ReactNode;
}) {
  const flip = x > width - 170;
  return (
    <div
      className="pointer-events-none absolute z-10 rounded-lg px-3 py-2 text-[12px] shadow-lg"
      style={{
        left: flip ? undefined : x + 12,
        right: flip ? width - x + 12 : undefined,
        top: y,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        color: "var(--text-primary)",
        minWidth: 130,
      }}
    >
      {children}
    </div>
  );
}

export function TooltipRow({ color, label, value }: { color?: string; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 leading-5">
      <span className="flex items-center gap-1.5" style={{ color: "var(--text-secondary)" }}>
        {color ? <span style={{ background: color, width: 8, height: 8, borderRadius: 2, display: "inline-block" }} /> : null}
        {label}
      </span>
      <span className="tnum font-medium">{value}</span>
    </div>
  );
}

export function Legend({ items }: { items: { color: string; label: string }[] }) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px]" style={{ color: "var(--text-secondary)" }}>
      {items.map((i) => (
        <span key={i.label} className="flex items-center gap-1.5">
          <span aria-hidden style={{ background: i.color, width: 10, height: 3, borderRadius: 2, display: "inline-block" }} />
          {i.label}
        </span>
      ))}
    </div>
  );
}

/** Шаг непрерывной шкалы 0..1 → одна из семи ступеней синей рампы. */
export function seqStep(t: number) {
  if (t <= 0) return "var(--seq-0)";
  const idx = Math.min(6, Math.max(1, Math.ceil(t * 6)));
  return `var(--seq-${idx})`;
}

/** Текст поверх ступени: на тёмных ступенях — светлый. */
export function seqInk(t: number) {
  const idx = t <= 0 ? 0 : Math.min(6, Math.max(1, Math.ceil(t * 6)));
  return `var(--seq-ink-${idx})`;
}

export const shortDay = (iso: string) =>
  new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short" }).format(new Date(iso + "T00:00:00"));

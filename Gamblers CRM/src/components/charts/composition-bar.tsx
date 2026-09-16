"use client";

import { useState } from "react";

export type Part = { key: string; label: string; hint?: string; value: number; color: string };

/** Состав аудитории одной полосой: доли читаются сразу, 2px зазор вместо обводки. */
export function CompositionBar({ parts }: { parts: Part[] }) {
  const total = parts.reduce((s, p) => s + p.value, 0) || 1;
  const [hover, setHover] = useState<string | null>(null);

  return (
    <div>
      <div className="flex h-9 w-full gap-[2px] overflow-hidden rounded-lg">
        {parts.map((p) => (
          <div
            key={p.key}
            title={`${p.label}: ${p.value}`}
            onMouseEnter={() => setHover(p.key)}
            onMouseLeave={() => setHover(null)}
            style={{
              width: `${(p.value / total) * 100}%`,
              background: p.color,
              opacity: hover && hover !== p.key ? 0.45 : 1,
              transition: "opacity .12s",
            }}
          />
        ))}
      </div>
      <ul className="mt-4 grid gap-x-8 gap-y-3 sm:grid-cols-2">
        {parts.map((p) => (
          <li key={p.key} className="text-[12px]">
            <div className="flex items-baseline justify-between gap-3">
              <span className="flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
                <span aria-hidden style={{ background: p.color, width: 10, height: 10, borderRadius: 3, display: "inline-block" }} />
                {p.label}
              </span>
              <span className="tnum whitespace-nowrap">
                {p.value.toLocaleString("ru-RU")}{" "}
                <span style={{ color: "var(--text-muted)" }}>{Math.round((p.value / total) * 100)}%</span>
              </span>
            </div>
            {p.hint ? (
              <div className="mt-0.5 pl-[18px]" style={{ color: "var(--text-muted)" }}>
                {p.hint}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

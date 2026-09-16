"use client";

import { seqInk, seqStep } from "./util";

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

/** Когда чат живой: день недели × час в таймзоне отчётов. */
export function ActivityHeatmap({ cells, tz }: { cells: { weekday: number; hour: number; messages: number }[]; tz: string }) {
  const grid = new Map<string, number>();
  let max = 0;
  for (const c of cells) {
    grid.set(`${c.weekday}:${c.hour}`, c.messages);
    if (c.messages > max) max = c.messages;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] border-separate" style={{ borderSpacing: "2px" }}>
        <thead>
          <tr>
            <th />
            {Array.from({ length: 24 }, (_, h) => (
              <th key={h} className="tnum text-[10px] font-normal" style={{ color: "var(--text-muted)" }}>
                {h % 3 === 0 ? h : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {WEEKDAYS.map((label, wd) => (
            <tr key={label}>
              <td className="pr-2 text-[11px]" style={{ color: "var(--text-secondary)" }}>
                {label}
              </td>
              {Array.from({ length: 24 }, (_, h) => {
                const v = grid.get(`${wd}:${h}`) ?? 0;
                const t = max ? v / max : 0;
                return (
                  <td
                    key={h}
                    title={`${label}, ${String(h).padStart(2, "0")}:00 — ${v} сообщений`}
                    className="tnum h-6 rounded text-center text-[10px]"
                    style={{ background: seqStep(t), color: seqInk(t) }}
                  >
                    {t > 0.72 ? v : ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex items-center gap-2 text-[11px]" style={{ color: "var(--text-muted)" }}>
        <span>реже</span>
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <span key={i} aria-hidden style={{ background: `var(--seq-${i})`, width: 22, height: 8, borderRadius: 2, display: "inline-block" }} />
        ))}
        <span>чаще</span>
        <span className="ml-3">пик — {max} сообщ./час · таймзона {tz}</span>
      </div>
    </div>
  );
}

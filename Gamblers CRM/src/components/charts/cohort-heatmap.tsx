"use client";

import { useState } from "react";
import { Tooltip, TooltipRow, seqInk, seqStep } from "./util";

export type CohortMatrix = {
  cohort: string;
  /** Готовая подпись строки: серверные компоненты не передают функции. */
  label: string;
  size: number;
  cells: (number | null)[];
};

/** Когортная матрица: строка — неделя прихода, столбец — отсечка жизни. */
export function CohortHeatmap({
  rows,
  columns,
  cellTitle = "Доля",
}: {
  rows: CohortMatrix[];
  columns: string[];
  cellTitle?: string;
}) {
  const [hover, setHover] = useState<{ r: number; c: number; x: number; y: number } | null>(null);

  return (
    <div className="relative overflow-x-auto">
      <table className="w-full border-separate" style={{ borderSpacing: "2px" }}>
        <thead>
          <tr>
            <th className="whitespace-nowrap px-2 text-left text-[11px] font-medium" style={{ color: "var(--text-muted)" }}>
              Когорта
            </th>
            <th className="px-2 text-right text-[11px] font-medium" style={{ color: "var(--text-muted)" }}>
              Людей
            </th>
            {columns.map((c) => (
              <th key={c} className="px-2 text-center text-[11px] font-medium" style={{ color: "var(--text-muted)" }}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={row.cohort}>
              <td className="whitespace-nowrap px-2 text-[12px]" style={{ color: "var(--text-secondary)" }}>
                {row.label}
              </td>
              <td className="tnum px-2 text-right text-[12px]" style={{ color: "var(--text-secondary)" }}>
                {row.size}
              </td>
              {row.cells.map((v, c) => (
                <td
                  key={c}
                  className="tnum h-8 min-w-[52px] rounded text-center text-[12px]"
                  style={{
                    background: v === null ? "transparent" : seqStep(v),
                    color: v === null ? "var(--text-muted)" : seqInk(v),
                    border: v === null ? "1px dashed var(--grid)" : "none",
                  }}
                  onMouseEnter={(e) => {
                    const box = (e.currentTarget.closest(".relative") as HTMLElement)?.getBoundingClientRect();
                    const cell = e.currentTarget.getBoundingClientRect();
                    setHover({ r, c, x: cell.left - (box?.left ?? 0) + cell.width / 2, y: cell.top - (box?.top ?? 0) - 8 });
                  }}
                  onMouseLeave={() => setHover(null)}
                >
                  {v === null ? "—" : `${Math.round(v * 100)}%`}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      {hover ? (
        <Tooltip x={hover.x} y={Math.max(0, hover.y - 40)} width={9999}>
          <div className="mb-1 font-medium">{rows[hover.r].label}</div>
          <TooltipRow label="Когорта" value={`${rows[hover.r].size} чел.`} />
          <TooltipRow label={columns[hover.c]} value={rows[hover.r].cells[hover.c] === null ? "рано судить" : `${Math.round((rows[hover.r].cells[hover.c] as number) * 100)}% · ${cellTitle}`} />
        </Tooltip>
      ) : null}

      <div className="mt-3 flex items-center gap-2 text-[11px]" style={{ color: "var(--text-muted)" }}>
        <span>0%</span>
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <span key={i} aria-hidden style={{ background: `var(--seq-${i})`, width: 22, height: 8, borderRadius: 2, display: "inline-block" }} />
        ))}
        <span>100%</span>
        <span className="ml-3">«—» — когорта ещё не дожила до отсечки</span>
      </div>
    </div>
  );
}

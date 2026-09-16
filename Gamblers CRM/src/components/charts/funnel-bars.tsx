"use client";

/** Воронка: упорядоченные шаги → порядковая шкала одного тона. */
export function FunnelBars({ steps }: { steps: { key: string; label: string; value: number }[] }) {
  const base = steps[0]?.value || 1;
  return (
    <div className="flex flex-col gap-2.5">
      {steps.map((s, i) => {
        const share = s.value / base;
        return (
          <div key={s.key}>
            <div className="mb-1 flex items-baseline justify-between gap-3 text-[12px]">
              <span style={{ color: "var(--text-secondary)" }}>{s.label}</span>
              <span className="tnum" style={{ color: "var(--text-primary)" }}>
                {s.value.toLocaleString("ru-RU")}
                <span style={{ color: "var(--text-muted)" }}> · {Math.round(share * 100)}%</span>
              </span>
            </div>
            <div className="h-2.5 w-full rounded-full" style={{ background: "var(--grid)" }}>
              <div
                className="h-2.5 rounded-full"
                style={{ width: `${Math.max(1, share * 100)}%`, background: `var(--ord-${Math.min(5, i + 1)})` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

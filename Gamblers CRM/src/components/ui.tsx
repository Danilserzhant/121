import Link from "next/link";
import { ReactNode } from "react";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle ? (
          <p className="mt-1 text-[13px]" style={{ color: "var(--text-secondary)" }}>
            {subtitle}
          </p>
        ) : null}
      </div>
      {actions}
    </div>
  );
}

export function Card({
  title,
  hint,
  children,
  className = "",
  actions,
}: {
  title?: string;
  hint?: string;
  children: ReactNode;
  className?: string;
  actions?: ReactNode;
}) {
  return (
    <section className={`card p-4 sm:p-5 ${className}`}>
      {title ? (
        <header className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[14px] font-medium">{title}</h2>
            {hint ? (
              <p className="mt-0.5 text-[12px]" style={{ color: "var(--text-muted)" }}>
                {hint}
              </p>
            ) : null}
          </div>
          {actions}
        </header>
      ) : null}
      {children}
    </section>
  );
}

export function StatTile({
  label,
  value,
  hint,
  delta,
  deltaGoodWhen = "up",
}: {
  label: string;
  value: string;
  hint?: string;
  delta?: number | null;
  deltaGoodWhen?: "up" | "down";
}) {
  const showDelta = delta !== null && delta !== undefined && Number.isFinite(delta);
  const positive = showDelta && delta! > 0;
  const good = showDelta && (deltaGoodWhen === "up" ? delta! > 0 : delta! < 0);
  return (
    <div className="card p-4">
      <div className="text-[12px]" style={{ color: "var(--text-muted)" }}>
        {label}
      </div>
      <div className="mt-1.5 text-[26px] font-semibold leading-none">{value}</div>
      <div className="mt-2 flex items-center gap-2 text-[12px]">
        {showDelta ? (
          <span style={{ color: delta === 0 ? "var(--text-muted)" : good ? "var(--delta-up)" : "var(--critical)" }}>
            {positive ? "▲" : delta === 0 ? "—" : "▼"} {Math.abs(delta! * 100).toFixed(0)}%
          </span>
        ) : null}
        {hint ? <span style={{ color: "var(--text-muted)" }}>{hint}</span> : null}
      </div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="px-2 py-10 text-center text-[13px]" style={{ color: "var(--text-muted)" }}>
      {children}
    </div>
  );
}

export function ChipLink({ href, active, children }: { href: string; active: boolean; children: ReactNode }) {
  return (
    <Link href={href} className="chip" data-active={active}>
      {children}
    </Link>
  );
}

const SEGMENT_STYLE: Record<string, string> = {
  core: "var(--ord-5)",
  active: "var(--ord-4)",
  sleeping: "var(--ord-3)",
  lurker: "var(--ord-2)",
  left: "var(--ord-1)",
};

export function SegmentBadge({ segment, label }: { segment: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px]" style={{ color: "var(--text-secondary)" }}>
      <span
        aria-hidden
        style={{ background: SEGMENT_STYLE[segment] ?? "var(--text-muted)", width: 8, height: 8, borderRadius: 3, display: "inline-block" }}
      />
      {label}
    </span>
  );
}

export const SEGMENT_COLORS = SEGMENT_STYLE;

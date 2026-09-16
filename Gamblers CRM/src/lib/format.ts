const nf = new Intl.NumberFormat("ru-RU");

export const num = (n: number | bigint | null | undefined) =>
  n === null || n === undefined ? "—" : nf.format(Number(n));

export const pct = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(digits)}%`;

export const money = (v: number | null | undefined, currency = "USD") =>
  v === null || v === undefined
    ? "—"
    : new Intl.NumberFormat("ru-RU", { style: "currency", currency, maximumFractionDigits: 2 }).format(v);

export const days = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v.toFixed(v < 10 ? 1 : 0)} дн.`;

export const shortDate = (d: Date | string) =>
  new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short" }).format(new Date(d));

export const fullDate = (d: Date | string) =>
  new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", year: "numeric" }).format(new Date(d));

export const dateTime = (d: Date | string | null | undefined) =>
  d ? new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(d)) : "—";

export function personName(p: { firstName: string | null; lastName: string | null; username: string | null; tgUserId: bigint }) {
  const name = [p.firstName, p.lastName].filter(Boolean).join(" ").trim();
  if (name) return name;
  if (p.username) return `@${p.username}`;
  return `id${p.tgUserId}`;
}

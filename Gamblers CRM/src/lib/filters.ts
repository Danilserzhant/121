import { db } from "./db";

export type Range = { from: Date; to: Date; days: number; preset: string };

const PRESETS: Record<string, number> = { "7d": 7, "30d": 30, "90d": 90, "180d": 180, "365d": 365 };

export const RANGE_OPTIONS = [
  { value: "7d", label: "7 дней" },
  { value: "30d", label: "30 дней" },
  { value: "90d", label: "90 дней" },
  { value: "180d", label: "180 дней" },
  { value: "365d", label: "Год" },
  { value: "all", label: "Всё время" },
];

/** Разбирает ?range=30d в конкретные границы. `all` растягивается до первого события. */
export async function resolveRange(preset: string | undefined, chatId: number | null): Promise<Range> {
  const key = preset && (preset in PRESETS || preset === "all") ? preset : "30d";
  const to = new Date();
  if (key === "all") {
    const first = await db.event.findFirst({
      where: chatId ? { chatId } : {},
      orderBy: { at: "asc" },
      select: { at: true },
    });
    const from = first?.at ?? new Date(to.getTime() - 30 * 864e5);
    return { from, to, days: Math.max(1, Math.round((+to - +from) / 864e5)), preset: key };
  }
  const n = PRESETS[key];
  return { from: new Date(to.getTime() - n * 864e5), to, days: n, preset: key };
}

export async function resolveChat(param: string | undefined) {
  const chats = await db.chat.findMany({ where: { isActive: true }, orderBy: { id: "asc" } });
  const asked = param ? chats.find((c) => String(c.id) === param) : undefined;
  return { chats, chat: asked ?? chats[0] ?? null };
}

/** Строит querystring, сохраняя текущие фильтры и меняя одну пару. */
export function withParam(params: Record<string, string | undefined>, key: string, value: string) {
  const next = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v && k !== key) next.set(k, v);
  if (value) next.set(key, value);
  const qs = next.toString();
  return qs ? `?${qs}` : "";
}

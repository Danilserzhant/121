import { Chat, Source } from "@prisma/client";
import { RANGE_OPTIONS, withParam } from "@/lib/filters";
import { ChipLink } from "./ui";

export type SearchParams = Record<string, string | undefined>;

export function FilterBar({
  basePath,
  params,
  chats,
  chatId,
  sources,
  showRange = true,
  showSource = true,
  activeRange,
}: {
  basePath: string;
  params: SearchParams;
  chats: Chat[];
  chatId: number | null;
  sources?: Source[];
  showRange?: boolean;
  showSource?: boolean;
  /** Применённый период — может отличаться от параметра, если у страницы свой по умолчанию. */
  activeRange?: string;
}) {
  const range = params.range ?? activeRange ?? "30d";
  const source = params.source ?? "";
  return (
    <div className="mb-5 flex flex-wrap items-center gap-x-6 gap-y-2">
      {chats.length > 1 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[12px]" style={{ color: "var(--text-muted)" }}>
            Чат
          </span>
          {chats.map((c) => (
            <ChipLink key={c.id} href={`${basePath}${withParam(params, "chat", String(c.id))}`} active={chatId === c.id}>
              {c.title}
            </ChipLink>
          ))}
        </div>
      ) : null}

      {showRange ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[12px]" style={{ color: "var(--text-muted)" }}>
            Период
          </span>
          {RANGE_OPTIONS.map((o) => (
            <ChipLink key={o.value} href={`${basePath}${withParam(params, "range", o.value)}`} active={range === o.value}>
              {o.label}
            </ChipLink>
          ))}
        </div>
      ) : null}

      {showSource && sources && sources.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[12px]" style={{ color: "var(--text-muted)" }}>
            Источник
          </span>
          <ChipLink href={`${basePath}${withParam(params, "source", "")}`} active={!source}>
            Все
          </ChipLink>
          {sources.map((s) => (
            <ChipLink key={s.id} href={`${basePath}${withParam(params, "source", String(s.id))}`} active={source === String(s.id)}>
              {s.title}
            </ChipLink>
          ))}
          <ChipLink href={`${basePath}${withParam(params, "source", "0")}`} active={source === "0"}>
            Без метки
          </ChipLink>
        </div>
      ) : null}
    </div>
  );
}

export function parseSource(params: SearchParams): number | null {
  if (params.source === undefined || params.source === "") return null;
  const v = Number(params.source);
  return Number.isFinite(v) ? v : null;
}

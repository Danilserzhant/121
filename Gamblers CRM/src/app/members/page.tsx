import Link from "next/link";
import { FilterBar, parseSource, SearchParams } from "@/components/filter-bar";
import { NoChats } from "@/components/no-chats";
import { Card, ChipLink, Empty, PageHeader, SegmentBadge } from "@/components/ui";
import { db } from "@/lib/db";
import { resolveChat, withParam } from "@/lib/filters";
import { dateTime, days, num, personName } from "@/lib/format";
import { getMembers, SEGMENTS, SegmentKey } from "@/lib/metrics";

export const dynamic = "force-dynamic";

const SORTS = [
  { value: "joined", label: "По дате входа" },
  { value: "messages", label: "По сообщениям" },
  { value: "lastMessage", label: "По последнему сообщению" },
] as const;

export default async function MembersPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const { chats, chat } = await resolveChat(params.chat);
  if (!chat) return <NoChats />;

  const segment = (params.segment as SegmentKey | "all") ?? "all";
  const sort = (params.sort as "joined" | "messages" | "lastMessage") ?? "joined";
  const page = Math.max(1, Number(params.page ?? 1) || 1);
  const perPage = 50;

  const [sources, { rows, total }] = await Promise.all([
    db.source.findMany({ orderBy: { title: "asc" } }),
    getMembers({
      chatId: chat.id,
      segment,
      sourceId: parseSource(params),
      search: params.q,
      sort,
      page,
      perPage,
    }),
  ]);

  const pages = Math.max(1, Math.ceil(total / perPage));

  return (
    <>
      <PageHeader title="Люди" subtitle={`${num(total)} записей в «${chat.title}»`} />
      <FilterBar basePath="/members" params={params} chats={chats} chatId={chat.id} sources={sources} showRange={false} />

      <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[12px]" style={{ color: "var(--text-muted)" }}>
            Сегмент
          </span>
          <ChipLink href={`/members${withParam(params, "segment", "")}`} active={segment === "all"}>
            Все
          </ChipLink>
          {SEGMENTS.map((s) => (
            <ChipLink key={s.key} href={`/members${withParam(params, "segment", s.key)}`} active={segment === s.key}>
              {s.label}
            </ChipLink>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[12px]" style={{ color: "var(--text-muted)" }}>
            Сортировка
          </span>
          {SORTS.map((s) => (
            <ChipLink key={s.value} href={`/members${withParam(params, "sort", s.value)}`} active={sort === s.value}>
              {s.label}
            </ChipLink>
          ))}
        </div>
        <form action="/members" className="flex items-center gap-2">
          <input type="hidden" name="chat" value={String(chat.id)} />
          {params.segment ? <input type="hidden" name="segment" value={params.segment} /> : null}
          <input
            name="q"
            defaultValue={params.q ?? ""}
            placeholder="Имя или @username"
            className="rounded-lg px-3 py-1.5 text-[13px] outline-none"
            style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
          />
          <button type="submit" className="chip">
            Найти
          </button>
        </form>
      </div>

      <Card>
        {rows.length === 0 ? (
          <Empty>Никого не нашлось — попробуйте другой сегмент или запрос.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="data">
              <thead>
                <tr>
                  <th>Человек</th>
                  <th>Сегмент</th>
                  <th>Источник</th>
                  <th className="n">Вошёл</th>
                  <th className="n">В группе</th>
                  <th className="n">Сообщений</th>
                  <th className="n">Последнее сообщение</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.personId}>
                    <td>
                      <Link href={`/members/${r.personId}?chat=${chat.id}`} className="underline-offset-2 hover:underline">
                        {personName(r)}
                      </Link>
                      {r.username ? (
                        <span className="ml-2 text-[12px]" style={{ color: "var(--text-muted)" }}>
                          @{r.username}
                        </span>
                      ) : null}
                    </td>
                    <td>
                      <SegmentBadge segment={r.segment} label={SEGMENTS.find((s) => s.key === r.segment)?.label ?? r.segment} />
                    </td>
                    <td style={{ color: "var(--text-secondary)" }}>{r.sourceTitle ?? "Без метки"}</td>
                    <td className="n" style={{ color: "var(--text-secondary)" }}>{dateTime(r.joinedAt)}</td>
                    <td className="n">{days(r.lifetimeDays)}</td>
                    <td className="n">{num(r.messageCount)}</td>
                    <td className="n" style={{ color: "var(--text-secondary)" }}>{dateTime(r.lastMessageAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {pages > 1 ? (
        <div className="mt-4 flex items-center gap-2">
          {page > 1 ? (
            <Link href={`/members${withParam(params, "page", String(page - 1))}`} className="chip">
              ← Назад
            </Link>
          ) : null}
          <span className="text-[12px]" style={{ color: "var(--text-muted)" }}>
            Страница {page} из {pages}
          </span>
          {page < pages ? (
            <Link href={`/members${withParam(params, "page", String(page + 1))}`} className="chip">
              Вперёд →
            </Link>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

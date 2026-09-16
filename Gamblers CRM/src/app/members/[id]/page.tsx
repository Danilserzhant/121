import Link from "next/link";
import { notFound } from "next/navigation";
import { Card, Empty, PageHeader, StatTile } from "@/components/ui";
import { Sparkline } from "@/components/charts/sparkline";
import { db } from "@/lib/db";
import { INACTIVE_DAYS } from "@/lib/env";
import { dateTime, days, num, personName } from "@/lib/format";
import { getPersonActivity } from "@/lib/metrics";

export const dynamic = "force-dynamic";

const EVENT_LABEL: Record<string, string> = {
  join: "Вступил",
  leave: "Вышел",
  kick: "Удалён из группы",
};

export default async function MemberPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const personId = Number(id);
  if (!Number.isFinite(personId)) notFound();

  const person = await db.person.findUnique({
    where: { id: personId },
    include: {
      memberships: { include: { chat: true, source: true }, orderBy: { joinedAt: "asc" } },
      events: { include: { chat: true }, orderBy: { at: "desc" }, take: 20 },
    },
  });
  if (!person) notFound();

  const chatId = Number(sp.chat) || person.memberships[0]?.chatId;
  const membership = person.memberships.find((m) => m.chatId === chatId) ?? person.memberships[0];
  const activity = membership ? await getPersonActivity(person.id, membership.chatId, 90) : [];
  const recent = membership
    ? await db.message.findMany({
        where: { personId: person.id, chatId: membership.chatId },
        orderBy: { at: "desc" },
        take: 10,
      })
    : [];

  const lifetimeDays = membership
    ? ((membership.leftAt ?? new Date()).getTime() - membership.joinedAt.getTime()) / 864e5
    : null;
  const silentFor = membership?.lastMessageAt
    ? (Date.now() - membership.lastMessageAt.getTime()) / 864e5
    : null;

  return (
    <>
      <PageHeader
        title={personName(person)}
        subtitle={[person.username ? `@${person.username}` : null, `tg id ${person.tgUserId}`, person.langCode]
          .filter(Boolean)
          .join(" · ")}
        actions={
          <Link href={`/members?chat=${membership?.chatId ?? ""}`} className="chip">
            ← Ко всем людям
          </Link>
        }
      />

      {!membership ? (
        <Empty>Человек не состоит ни в одном отслеживаемом чате.</Empty>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Статус" value={membership.status === "active" ? "В группе" : membership.status === "kicked" ? "Удалён" : "Ушёл"} hint={membership.chat.title} />
            <StatTile label="В группе" value={days(lifetimeDays)} hint={`с ${dateTime(membership.joinedAt)}`} />
            <StatTile label="Сообщений" value={num(membership.messageCount)} hint={membership.firstMessageAt ? `первое ${dateTime(membership.firstMessageAt)}` : "ни одного"} />
            <StatTile
              label="Молчит"
              value={silentFor === null ? "всегда" : days(silentFor)}
              hint={silentFor !== null && silentFor > INACTIVE_DAYS ? "дольше порога отвала" : undefined}
            />
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <Card title="Активность за 90 дней" hint="сообщений в день">
              <Sparkline values={activity.map((a) => a.messages)} height={72} />
            </Card>

            <Card title="Атрибуция">
              <dl className="grid grid-cols-[auto,1fr] gap-x-6 gap-y-2 text-[13px]">
                <dt style={{ color: "var(--text-muted)" }}>Источник</dt>
                <dd>{membership.source?.title ?? "Без метки"}</dd>
                <dt style={{ color: "var(--text-muted)" }}>Пригласительная ссылка</dt>
                <dd className="truncate">{membership.inviteLinkId ? `#${membership.inviteLinkId}` : "—"}</dd>
                <dt style={{ color: "var(--text-muted)" }}>Заходов в группу</dt>
                <dd>{membership.joinCount}</dd>
                <dt style={{ color: "var(--text-muted)" }}>Premium</dt>
                <dd>{person.isPremium ? "да" : "нет"}</dd>
              </dl>
            </Card>
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <Card title="История событий">
              {person.events.length === 0 ? (
                <Empty>Событий пока нет.</Empty>
              ) : (
                <ul className="flex flex-col gap-2 text-[13px]">
                  {person.events.map((e) => (
                    <li key={e.id} className="flex items-baseline justify-between gap-3">
                      <span>{EVENT_LABEL[e.type] ?? e.type}</span>
                      <span style={{ color: "var(--text-muted)" }}>
                        {e.chat.title} · {dateTime(e.at)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Последние сообщения" hint="текст хранится только при включённом STORE_MESSAGE_PREVIEW">
              {recent.length === 0 ? (
                <Empty>Сообщений нет.</Empty>
              ) : (
                <ul className="flex flex-col gap-2.5 text-[13px]">
                  {recent.map((m) => (
                    <li key={m.id}>
                      <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
                        {dateTime(m.at)} · {m.wordCount} сл.{m.isQuestion ? " · вопрос" : ""}
                        {m.hasMedia ? " · медиа" : ""}
                      </div>
                      {m.preview ? <div className="mt-0.5">{m.preview}</div> : null}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          {person.memberships.length > 1 ? (
            <Card title="Другие чаты" className="mt-3">
              <ul className="flex flex-wrap gap-2">
                {person.memberships.map((m) => (
                  <li key={m.id}>
                    <Link href={`/members/${person.id}?chat=${m.chatId}`} className="chip" data-active={m.chatId === membership.chatId}>
                      {m.chat.title}
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </>
      )}
    </>
  );
}

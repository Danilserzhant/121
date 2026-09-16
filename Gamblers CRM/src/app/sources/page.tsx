import Link from "next/link";
import { FilterBar, SearchParams } from "@/components/filter-bar";
import { NoChats } from "@/components/no-chats";
import { Card, Empty, PageHeader } from "@/components/ui";
import { resolveChat, resolveRange } from "@/lib/filters";
import { days, fullDate, money, num, pct } from "@/lib/format";
import { getSources } from "@/lib/metrics";

export const dynamic = "force-dynamic";

export default async function SourcesPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const { chats, chat } = await resolveChat(params.chat);
  if (!chat) return <NoChats />;

  const range = await resolveRange(params.range, chat.id);
  const rows = await getSources({ chatId: chat.id, from: range.from, to: range.to });
  const totals = rows.reduce(
    (acc, r) => ({
      joins: acc.joins + r.joins,
      alive: acc.alive + r.aliveNow,
      talkers: acc.talkers + r.talkers,
      spend: acc.spend + (r.spend ?? 0),
    }),
    { joins: 0, alive: 0, talkers: 0, spend: 0 },
  );

  return (
    <>
      <PageHeader
        title="Источники"
        subtitle={`Кто приводит людей, которые остаются. ${fullDate(range.from)} — ${fullDate(range.to)}`}
      />
      <FilterBar basePath="/sources" params={params} chats={chats} chatId={chat.id} showSource={false} />

      <Card
        title="Качество трафика по источникам"
        hint="«Дожили 7 дн.» считается только по тем, кто пришёл достаточно давно; расход — суммарный по источнику, не за период"
      >
        {rows.length === 0 ? (
          <Empty>За период никто не вступал.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="data">
              <thead>
                <tr>
                  <th>Источник</th>
                  <th>Тип</th>
                  <th className="n">Пришло</th>
                  <th className="n">В группе</th>
                  <th className="n">Дожили 7 дн.</th>
                  <th className="n">Заговорили</th>
                  <th className="n">Сообщений/чел.</th>
                  <th className="n">Медиана жизни</th>
                  <th className="n">Расход</th>
                  <th className="n">Цена входа</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.sourceId}>
                    <td>
                      {r.sourceId ? (
                        <Link href={`/members?source=${r.sourceId}`} className="underline-offset-2 hover:underline">
                          {r.title}
                        </Link>
                      ) : (
                        <span style={{ color: "var(--text-secondary)" }}>{r.title}</span>
                      )}
                    </td>
                    <td style={{ color: "var(--text-secondary)" }}>{KIND_LABEL[r.kind] ?? r.kind}</td>
                    <td className="n">{num(r.joins)}</td>
                    <td className="n">{num(r.aliveNow)}</td>
                    <td className="n">{pct(r.alive7)}</td>
                    <td className="n">{pct(r.joins ? r.talkers / r.joins : null)}</td>
                    <td className="n">{r.joins ? (r.messages / r.joins).toFixed(1) : "—"}</td>
                    <td className="n">{days(r.medianLifetimeDays)}</td>
                    <td className="n">{money(r.spend, r.currency)}</td>
                    <td className="n">{money(r.cpl, r.currency)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td style={{ color: "var(--text-secondary)" }}>Итого</td>
                  <td />
                  <td className="n">{num(totals.joins)}</td>
                  <td className="n">{num(totals.alive)}</td>
                  <td className="n">—</td>
                  <td className="n">{pct(totals.joins ? totals.talkers / totals.joins : null)}</td>
                  <td className="n">—</td>
                  <td className="n">—</td>
                  <td className="n">{money(totals.spend)}</td>
                  <td className="n">{money(totals.joins ? totals.spend / totals.joins : null)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </Card>

      <p className="mt-4 text-[12px]" style={{ color: "var(--text-muted)" }}>
        Атрибуция идёт по пригласительным ссылкам Telegram: каждая ссылка привязана к источнику в «Настройках».
        Люди, пришедшие по общей ссылке или добавленные вручную, попадают в строку «Без метки».
      </p>
    </>
  );
}

const KIND_LABEL: Record<string, string> = {
  blogger: "Блогер",
  ads: "Реклама",
  seeding: "Посев",
  organic: "Органика",
  partner: "Партнёр",
  other: "Другое",
  unknown: "—",
};

import Link from "next/link";
import { FilterBar, SearchParams } from "@/components/filter-bar";
import { NoChats } from "@/components/no-chats";
import { Card, Empty, PageHeader, StatTile } from "@/components/ui";
import { ActivityHeatmap } from "@/components/charts/activity-heatmap";
import { LineChart } from "@/components/charts/line-chart";
import { resolveChat, resolveRange } from "@/lib/filters";
import { REPORT_TZ } from "@/lib/env";
import { dateTime, fullDate, num, personName, pct } from "@/lib/format";
import { getActivityHeatmap, getDailyFlow, getOverview, getTopTalkers } from "@/lib/metrics";

export const dynamic = "force-dynamic";

export default async function EngagementPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const { chats, chat } = await resolveChat(params.chat);
  if (!chat) return <NoChats />;

  const range = await resolveRange(params.range, chat.id);
  const scope = { chatId: chat.id, from: range.from, to: range.to };

  const [overview, flow, heat, talkers] = await Promise.all([
    getOverview(scope),
    getDailyFlow(scope),
    getActivityHeatmap(scope),
    getTopTalkers(scope, 20),
  ]);

  const questions = talkers.reduce((s, t) => s + t.questions, 0);
  const avgPerTalker = overview.current.talkers ? overview.current.messages / overview.current.talkers : null;

  return (
    <>
      <PageHeader
        title="Активность чата"
        subtitle={`Кто общается и когда. ${fullDate(range.from)} — ${fullDate(range.to)}`}
      />
      <FilterBar basePath="/engagement" params={params} chats={chats} chatId={chat.id} showSource={false} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Сообщений" value={num(overview.current.messages)} />
        <StatTile label="Уникальных авторов" value={num(overview.current.talkers)} hint={`${pct(overview.membersNow ? overview.current.talkers / overview.membersNow : null)} от группы`} />
        <StatTile label="Сообщений на автора" value={avgPerTalker ? avgPerTalker.toFixed(1) : "—"} />
        <StatTile label="Вопросов у топ-20" value={num(questions)} hint="сообщения со знаком вопроса" />
      </div>

      <div className="mt-3 grid gap-3">
        <Card title="Когда чат живой" hint="сообщения по дням недели и часам">
          {heat.length === 0 ? <Empty>За период сообщений нет.</Empty> : <ActivityHeatmap cells={heat} tz={REPORT_TZ} />}
        </Card>

        <Card title="Объём общения" hint="сообщения и число авторов по дням">
          <LineChart
            labels={flow.map((d) => d.day)}
            series={[
              { key: "messages", label: "Сообщений", color: "var(--series-1)", values: flow.map((d) => d.messages) },
              { key: "senders", label: "Авторов", color: "var(--series-2)", values: flow.map((d) => d.senders) },
            ]}
          />
        </Card>

        <Card title="Кто держит чат" hint="топ авторов за период">
          {talkers.length === 0 ? (
            <Empty>За период сообщений нет.</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table className="data">
                <thead>
                  <tr>
                    <th>Человек</th>
                    <th>Telegram</th>
                    <th className="n">Сообщений</th>
                    <th className="n">Вопросов</th>
                    <th className="n">Последнее</th>
                  </tr>
                </thead>
                <tbody>
                  {talkers.map((t) => (
                    <tr key={t.personId}>
                      <td>
                        <Link href={`/members/${t.personId}?chat=${chat.id}`} className="underline-offset-2 hover:underline">
                          {personName(t)}
                        </Link>
                      </td>
                      <td style={{ color: "var(--text-secondary)" }}>{t.username ? `@${t.username}` : "—"}</td>
                      <td className="n">{num(t.messages)}</td>
                      <td className="n">{num(t.questions)}</td>
                      <td className="n" style={{ color: "var(--text-secondary)" }}>{dateTime(t.lastMessageAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

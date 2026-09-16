import { FilterBar, parseSource, SearchParams } from "@/components/filter-bar";
import { NoChats } from "@/components/no-chats";
import { Card, Empty, PageHeader, StatTile } from "@/components/ui";
import { CohortHeatmap } from "@/components/charts/cohort-heatmap";
import { LineChart } from "@/components/charts/line-chart";
import { db } from "@/lib/db";
import { resolveChat, resolveRange } from "@/lib/filters";
import { days, fullDate, num, pct } from "@/lib/format";
import { ENGAGEMENT_WEEKS, getEngagementCohorts, getOverview, getSurvivalCohorts, SURVIVAL_OFFSETS } from "@/lib/metrics";

export const dynamic = "force-dynamic";

export default async function RetentionPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const { chats, chat } = await resolveChat(params.chat);
  if (!chat) return <NoChats />;

  const range = await resolveRange(params.range ?? "90d", chat.id);
  const sourceId = parseSource(params);
  const scope = { chatId: chat.id, from: range.from, to: range.to, sourceId };

  const [sources, survival, engagement, overview] = await Promise.all([
    db.source.findMany({ orderBy: { title: "asc" } }),
    getSurvivalCohorts(scope),
    getEngagementCohorts(scope),
    getOverview(scope),
  ]);

  // Средняя кривая дожития по всем когортам периода, взвешенная по размеру.
  const curve = SURVIVAL_OFFSETS.map((_, i) => {
    let weighted = 0;
    let den = 0;
    for (const row of survival) {
      const v = row.cells[i];
      if (v !== null) {
        weighted += v * row.size;
        den += row.size;
      }
    }
    return den ? (weighted / den) * 100 : 0;
  });

  return (
    <>
      <PageHeader
        title="Удержание"
        subtitle={`Кто доживает до конца потока. Когорты по неделе вступления, ${fullDate(range.from)} — ${fullDate(range.to)}`}
      />
      <FilterBar basePath="/retention" params={params} chats={chats} chatId={chat.id} sources={sources} activeRange={range.preset} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Дожили из пришедших" value={pct(overview.cohortAlive)} hint={`из ${num(overview.cohortSize)} чел. за период`} />
        <StatTile label="Медианная жизнь" value={days(overview.medianLifetimeDays)} hint="у тех, кто ушёл" />
        <StatTile label="Пишут регулярно" value={pct(overview.engagedShare)} hint="из тех, кто в группе" />
        <StatTile label="Молчат совсем" value={pct(overview.silentShare)} hint="ни одного сообщения" />
      </div>

      <div className="mt-3 grid gap-3">
        <Card title="Дожитие в группе" hint="доля когорты, которая всё ещё в чате спустя N дней после вступления">
          {survival.length === 0 ? (
            <Empty>За период нет когорт.</Empty>
          ) : (
            <CohortHeatmap
              rows={survival.map((r) => ({ ...r, label: `неделя ${fullDate(r.cohort)}` }))}
              columns={SURVIVAL_OFFSETS.map((d) => `${d} дн.`)}
              cellTitle="ещё в группе"
            />
          )}
        </Card>

        <Card title="Средняя кривая дожития" hint="взвешено по размеру когорт; показывает, на каком дне обычно отваливаются">
          <LineChart
            labels={SURVIVAL_OFFSETS.map((d) => `${d} дн.`)}
            series={[{ key: "alive", label: "Осталось, %", color: "var(--series-1)", values: curve }]}
            valueUnit="percent"
            labelKind="text"
          />
        </Card>

        <Card title="Вовлечённость по неделям жизни" hint="доля когорты, писавшая в чат на N-й неделе после вступления">
          {engagement.length === 0 ? (
            <Empty>За период нет когорт.</Empty>
          ) : (
            <CohortHeatmap
              rows={engagement.map((r) => ({ ...r, label: `неделя ${fullDate(r.cohort)}` }))}
              columns={ENGAGEMENT_WEEKS.map((w) => `нед. ${w + 1}`)}
              cellTitle="писали в чат"
            />
          )}
        </Card>
      </div>
    </>
  );
}

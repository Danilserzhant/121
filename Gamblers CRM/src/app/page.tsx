import { FilterBar, parseSource, SearchParams } from "@/components/filter-bar";
import { NoChats } from "@/components/no-chats";
import { Card, PageHeader, SEGMENT_COLORS, StatTile } from "@/components/ui";
import { CompositionBar } from "@/components/charts/composition-bar";
import { FlowChart } from "@/components/charts/flow-chart";
import { FunnelBars } from "@/components/charts/funnel-bars";
import { LineChart } from "@/components/charts/line-chart";
import { db } from "@/lib/db";
import { resolveChat, resolveRange } from "@/lib/filters";
import { days, fullDate, num, pct } from "@/lib/format";
import { getDailyFlow, getFunnel, getOverview, getSegments } from "@/lib/metrics";

export const dynamic = "force-dynamic";

const delta = (now: number, before: number) => (before === 0 ? null : (now - before) / before);

export default async function OverviewPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const { chats, chat } = await resolveChat(params.chat);
  if (!chat) return <NoChats />;

  const range = await resolveRange(params.range, chat.id);
  const sourceId = parseSource(params);
  const scope = { chatId: chat.id, from: range.from, to: range.to, sourceId };

  const [sources, overview, flow, funnel, segments] = await Promise.all([
    db.source.findMany({ orderBy: { title: "asc" } }),
    getOverview(scope),
    getDailyFlow(scope),
    getFunnel(scope),
    getSegments(scope),
  ]);

  return (
    <>
      <PageHeader
        title="Обзор"
        subtitle={`${chat.title} · ${fullDate(range.from)} — ${fullDate(range.to)}`}
      />
      <FilterBar basePath="/" params={params} chats={chats} chatId={chat.id} sources={sources} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="В группе сейчас" value={num(overview.membersNow)} hint={`чистый прирост ${overview.netGrowth > 0 ? "+" : ""}${overview.netGrowth}`} />
        <StatTile
          label="Пришли за период"
          value={num(overview.current.joins)}
          delta={delta(overview.current.joins, overview.previous.joins)}
          hint="к прошлому периоду"
        />
        <StatTile
          label="Ушли за период"
          value={num(overview.current.leaves)}
          delta={delta(overview.current.leaves, overview.previous.leaves)}
          deltaGoodWhen="down"
          hint="к прошлому периоду"
        />
        <StatTile
          label="Дожили из пришедших"
          value={pct(overview.cohortAlive)}
          hint={`из ${num(overview.cohortSize)} чел.`}
        />
        <StatTile label="Писали в чат" value={num(overview.current.talkers)} delta={delta(overview.current.talkers, overview.previous.talkers)} hint="уникальных авторов" />
        <StatTile label="Сообщений" value={num(overview.current.messages)} delta={delta(overview.current.messages, overview.previous.messages)} />
        <StatTile label="Молчат совсем" value={pct(overview.silentShare)} hint="из тех, кто в группе" />
        <StatTile label="Медианная жизнь" value={days(overview.medianLifetimeDays)} hint="у тех, кто уже ушёл" />
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <Card title="Приток и отток" hint="люди в день; вверх — вступления, вниз — выходы">
          <FlowChart data={flow.map((d) => ({ day: d.day, joins: d.joins, leaves: d.leaves }))} />
        </Card>
        <Card title="Размер аудитории" hint="сколько человек состояло в группе на конец дня">
          <LineChart
            labels={flow.map((d) => d.day)}
            series={[{ key: "members", label: "В группе", color: "var(--series-1)", values: flow.map((d) => d.members) }]}
          />
        </Card>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <Card title="Путь пришедших за период" hint="сколько людей доходит до каждого шага">
          <FunnelBars steps={funnel} />
        </Card>
        <Card title="Состав аудитории" hint="все, кто когда-либо вступал в группу">
          <CompositionBar
            parts={segments.map((s) => ({
              key: s.key,
              label: s.label,
              hint: s.hint,
              value: s.value,
              color: SEGMENT_COLORS[s.key],
            }))}
          />
        </Card>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <Card title="Сообщения в день" hint="объём общения в чате">
          <LineChart
            labels={flow.map((d) => d.day)}
            series={[
              { key: "messages", label: "Сообщений", color: "var(--series-1)", values: flow.map((d) => d.messages) },
              { key: "senders", label: "Авторов", color: "var(--series-2)", values: flow.map((d) => d.senders) },
            ]}
          />
        </Card>
        <Card title="Вовлечённость" hint={`доля тех, кто в группе и пишет`}>
          <div className="flex h-full flex-col justify-center gap-4 py-2">
            <div>
              <div className="text-[34px] font-semibold leading-none">{pct(overview.engagedShare)}</div>
              <p className="mt-2 text-[13px]" style={{ color: "var(--text-secondary)" }}>
                участников группы писали за последние две недели. Остальные — тихие: их видно в разделе «Люди»
                по сегментам «Засыпают» и «Молчуны».
              </p>
            </div>
          </div>
        </Card>
      </div>
    </>
  );
}

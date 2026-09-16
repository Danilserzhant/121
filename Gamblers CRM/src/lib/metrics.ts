import { Prisma } from "@prisma/client";
import { db } from "./db";
import { CORE_MESSAGES, INACTIVE_DAYS, REPORT_TZ } from "./env";

export type Scope = {
  chatId: number;
  from: Date;
  to: Date;
  /** null — все источники; 0 — «без метки». */
  sourceId?: number | null;
};

const n = (v: unknown) => (v === null || v === undefined ? 0 : Number(v));
const nn = (v: unknown) => (v === null || v === undefined ? null : Number(v));

/** Фильтр по источнику для таблицы Membership с алиасом m. */
function sourceFilter(sourceId: number | null | undefined) {
  if (sourceId === null || sourceId === undefined) return Prisma.empty;
  if (sourceId === 0) return Prisma.sql` and m."sourceId" is null`;
  return Prisma.sql` and m."sourceId" = ${sourceId}`;
}

/* ------------------------------------------------------------------ обзор */

export type WindowStats = {
  joins: number;
  leaves: number;
  messages: number;
  talkers: number;
};

async function windowStats(chatId: number, from: Date, to: Date, sourceId?: number | null): Promise<WindowStats> {
  const sf = sourceFilter(sourceId);
  const rows = await db.$queryRaw<Record<string, unknown>[]>`
    select
      (select count(*) from "Event" e join "Membership" m on m."personId" = e."personId" and m."chatId" = e."chatId"
         where e."chatId" = ${chatId} and e.type = 'join' and e.at >= ${from} and e.at <= ${to} ${sf}) as joins,
      (select count(*) from "Event" e join "Membership" m on m."personId" = e."personId" and m."chatId" = e."chatId"
         where e."chatId" = ${chatId} and e.type in ('leave','kick') and e.at >= ${from} and e.at <= ${to} ${sf}) as leaves,
      (select count(*) from "Message" x join "Membership" m on m."personId" = x."personId" and m."chatId" = x."chatId"
         where x."chatId" = ${chatId} and x.at >= ${from} and x.at <= ${to} ${sf}) as messages,
      (select count(distinct x."personId") from "Message" x join "Membership" m on m."personId" = x."personId" and m."chatId" = x."chatId"
         where x."chatId" = ${chatId} and x.at >= ${from} and x.at <= ${to} ${sf}) as talkers
  `;
  const r = rows[0] ?? {};
  return { joins: n(r.joins), leaves: n(r.leaves), messages: n(r.messages), talkers: n(r.talkers) };
}

export type Overview = {
  membersNow: number;
  current: WindowStats;
  previous: WindowStats;
  netGrowth: number;
  /** Доля пришедших за период, кто ещё в чате. */
  cohortAlive: number | null;
  cohortSize: number;
  /** Доля активных участников, не написавших ни одного сообщения. */
  silentShare: number | null;
  /** Доля активных участников, писавших за последние INACTIVE_DAYS дней. */
  engagedShare: number | null;
  medianLifetimeDays: number | null;
};

export async function getOverview(scope: Scope): Promise<Overview> {
  const { chatId, from, to, sourceId } = scope;
  const span = +to - +from;
  const sf = sourceFilter(sourceId);
  const [current, previous, rows] = await Promise.all([
    windowStats(chatId, from, to, sourceId),
    windowStats(chatId, new Date(+from - span), from, sourceId),
    db.$queryRaw<Record<string, unknown>[]>`
      select
        count(*) filter (where m.status = 'active') as members_now,
        count(*) filter (where m.status = 'active' and m."messageCount" = 0) as silent_active,
        count(*) filter (where m.status = 'active' and m."lastMessageAt" >= now() - make_interval(days => ${INACTIVE_DAYS}::int)) as engaged_active,
        count(*) filter (where m."joinedAt" >= ${from} and m."joinedAt" <= ${to}) as cohort_size,
        count(*) filter (where m."joinedAt" >= ${from} and m."joinedAt" <= ${to} and m.status = 'active') as cohort_alive,
        percentile_cont(0.5) within group (
          order by extract(epoch from (m."leftAt" - m."joinedAt")) / 86400
        ) filter (where m."leftAt" is not null) as median_lifetime
      from "Membership" m
      where m."chatId" = ${chatId} ${sf}
    `,
  ]);
  const r = rows[0] ?? {};
  const membersNow = n(r.members_now);
  const cohortSize = n(r.cohort_size);
  return {
    membersNow,
    current,
    previous,
    netGrowth: current.joins - current.leaves,
    cohortSize,
    cohortAlive: cohortSize ? n(r.cohort_alive) / cohortSize : null,
    silentShare: membersNow ? n(r.silent_active) / membersNow : null,
    engagedShare: membersNow ? n(r.engaged_active) / membersNow : null,
    medianLifetimeDays: nn(r.median_lifetime),
  };
}

/* --------------------------------------------------- динамика по дням */

export type DayRow = {
  day: string;
  joins: number;
  leaves: number;
  members: number;
  messages: number;
  senders: number;
};

export async function getDailyFlow(scope: Scope): Promise<DayRow[]> {
  const { chatId, from, to, sourceId } = scope;
  const sf = sourceFilter(sourceId);
  const rows = await db.$queryRaw<Record<string, unknown>[]>`
    with days as (
      select generate_series(
        (${from} at time zone ${REPORT_TZ})::date,
        (${to} at time zone ${REPORT_TZ})::date,
        interval '1 day'
      )::date as d
    ),
    ev as (
      select (e.at at time zone ${REPORT_TZ})::date as d,
             count(*) filter (where e.type = 'join') as joins,
             count(*) filter (where e.type in ('leave','kick')) as leaves
      from "Event" e
      join "Membership" m on m."personId" = e."personId" and m."chatId" = e."chatId"
      where e."chatId" = ${chatId} and e.at >= ${from} and e.at <= ${to} ${sf}
      group by 1
    ),
    msg as (
      select (x.at at time zone ${REPORT_TZ})::date as d,
             count(*) as messages,
             count(distinct x."personId") as senders
      from "Message" x
      join "Membership" m on m."personId" = x."personId" and m."chatId" = x."chatId"
      where x."chatId" = ${chatId} and x.at >= ${from} and x.at <= ${to} ${sf}
      group by 1
    )
    select days.d::text as day,
           coalesce(ev.joins, 0) as joins,
           coalesce(ev.leaves, 0) as leaves,
           coalesce(msg.messages, 0) as messages,
           coalesce(msg.senders, 0) as senders,
           (select count(*) from "Membership" m
             where m."chatId" = ${chatId} ${sf}
               and (m."joinedAt" at time zone ${REPORT_TZ})::date <= days.d
               and (m."leftAt" is null or (m."leftAt" at time zone ${REPORT_TZ})::date > days.d)) as members
    from days
    left join ev on ev.d = days.d
    left join msg on msg.d = days.d
    order by days.d
  `;
  return rows.map((r) => ({
    day: String(r.day),
    joins: n(r.joins),
    leaves: n(r.leaves),
    members: n(r.members),
    messages: n(r.messages),
    senders: n(r.senders),
  }));
}

/* ------------------------------------------------------------- воронка */

export type FunnelStep = { key: string; label: string; value: number };

/** Путь пришедшего за период: вступил → заговорил → закрепился → дожил. */
export async function getFunnel(scope: Scope): Promise<FunnelStep[]> {
  const { chatId, from, to, sourceId } = scope;
  const sf = sourceFilter(sourceId);
  const rows = await db.$queryRaw<Record<string, unknown>[]>`
    select
      count(*) as joined,
      count(*) filter (where m."messageCount" >= 1) as spoke,
      count(*) filter (where m."messageCount" >= ${CORE_MESSAGES}) as engaged,
      count(*) filter (where m.status = 'active') as alive,
      count(*) filter (where m.status = 'active' and m."lastMessageAt" >= now() - make_interval(days => ${INACTIVE_DAYS}::int)) as alive_active
    from "Membership" m
    where m."chatId" = ${chatId} and m."joinedAt" >= ${from} and m."joinedAt" <= ${to} ${sf}
  `;
  const r = rows[0] ?? {};
  return [
    { key: "joined", label: "Вступили", value: n(r.joined) },
    { key: "spoke", label: "Написали хотя бы раз", value: n(r.spoke) },
    { key: "engaged", label: `Написали ${CORE_MESSAGES}+ сообщений`, value: n(r.engaged) },
    { key: "alive", label: "Ещё в группе", value: n(r.alive) },
    { key: "alive_active", label: `Живы и пишут (${INACTIVE_DAYS} дн.)`, value: n(r.alive_active) },
  ];
}

/* ------------------------------------------------------------- когорты */

export const SURVIVAL_OFFSETS = [1, 3, 7, 14, 30, 60] as const;
export const ENGAGEMENT_WEEKS = [0, 1, 2, 3, 4, 5] as const;

export type CohortRow = {
  cohort: string;
  size: number;
  /** null — когорта ещё не дожила до этой отсечки. */
  cells: (number | null)[];
};

/** Сколько % когорты недели X ещё состоит в чате спустя N дней. */
export async function getSurvivalCohorts(scope: Scope): Promise<CohortRow[]> {
  const { chatId, from, to, sourceId } = scope;
  const sf = sourceFilter(sourceId);
  const cells = Prisma.join(
    SURVIVAL_OFFSETS.map(
      (d) => Prisma.sql`
        count(*) filter (where now() >= m."joinedAt" + make_interval(days => ${d}::int)) as ${Prisma.raw(`mature_${d}`)},
        count(*) filter (
          where now() >= m."joinedAt" + make_interval(days => ${d}::int)
            and (m."leftAt" is null or m."leftAt" >= m."joinedAt" + make_interval(days => ${d}::int))
        ) as ${Prisma.raw(`alive_${d}`)}`,
    ),
    ",",
  );
  const rows = await db.$queryRaw<Record<string, unknown>[]>`
    select to_char(date_trunc('week', m."joinedAt" at time zone ${REPORT_TZ}), 'YYYY-MM-DD') as cohort,
           count(*) as size,
           ${cells}
    from "Membership" m
    where m."chatId" = ${chatId} and m."joinedAt" >= ${from} and m."joinedAt" <= ${to} ${sf}
    group by 1
    order by 1
  `;
  return rows.map((r) => ({
    cohort: String(r.cohort),
    size: n(r.size),
    cells: SURVIVAL_OFFSETS.map((d) => {
      const mature = n(r[`mature_${d}`]);
      return mature ? n(r[`alive_${d}`]) / mature : null;
    }),
  }));
}

/** Сколько % когорты писало в чат на N-й неделе жизни. */
export async function getEngagementCohorts(scope: Scope): Promise<CohortRow[]> {
  const { chatId, from, to, sourceId } = scope;
  const sf = sourceFilter(sourceId);
  const cells = Prisma.join(
    ENGAGEMENT_WEEKS.map(
      (w) => Prisma.sql`
        count(*) filter (where now() >= m."joinedAt" + make_interval(days => ${(w + 1) * 7}::int)) as ${Prisma.raw(`mature_${w}`)},
        count(*) filter (
          where now() >= m."joinedAt" + make_interval(days => ${(w + 1) * 7}::int)
            and exists (
              select 1 from "Message" x
              where x."personId" = m."personId" and x."chatId" = m."chatId"
                and x.at >= m."joinedAt" + make_interval(days => ${w * 7}::int)
                and x.at < m."joinedAt" + make_interval(days => ${(w + 1) * 7}::int)
            )
        ) as ${Prisma.raw(`active_${w}`)}`,
    ),
    ",",
  );
  const rows = await db.$queryRaw<Record<string, unknown>[]>`
    select to_char(date_trunc('week', m."joinedAt" at time zone ${REPORT_TZ}), 'YYYY-MM-DD') as cohort,
           count(*) as size,
           ${cells}
    from "Membership" m
    where m."chatId" = ${chatId} and m."joinedAt" >= ${from} and m."joinedAt" <= ${to} ${sf}
    group by 1
    order by 1
  `;
  return rows.map((r) => ({
    cohort: String(r.cohort),
    size: n(r.size),
    cells: ENGAGEMENT_WEEKS.map((w) => {
      const mature = n(r[`mature_${w}`]);
      return mature ? n(r[`active_${w}`]) / mature : null;
    }),
  }));
}

/* ------------------------------------------------------------ источники */

export type SourceRow = {
  sourceId: number;
  slug: string;
  title: string;
  kind: string;
  spend: number | null;
  currency: string;
  joins: number;
  aliveNow: number;
  alive7: number | null;
  talkers: number;
  messages: number;
  medianLifetimeDays: number | null;
  cpl: number | null;
};

export async function getSources(scope: Scope): Promise<SourceRow[]> {
  const { chatId, from, to } = scope;
  const rows = await db.$queryRaw<Record<string, unknown>[]>`
    select coalesce(s.id, 0) as source_id,
           coalesce(max(s.slug), 'unattributed') as slug,
           coalesce(max(s.title), 'Без метки') as title,
           coalesce(max(s.kind), 'unknown') as kind,
           max(s.spend) as spend,
           coalesce(max(s.currency), 'USD') as currency,
           count(*) as joins,
           count(*) filter (where m.status = 'active') as alive_now,
           count(*) filter (where now() >= m."joinedAt" + make_interval(days => 7)) as mature_7,
           count(*) filter (
             where now() >= m."joinedAt" + make_interval(days => 7)
               and (m."leftAt" is null or m."leftAt" >= m."joinedAt" + make_interval(days => 7))
           ) as alive_7,
           count(*) filter (where m."messageCount" > 0) as talkers,
           sum(m."messageCount") as messages,
           percentile_cont(0.5) within group (
             order by extract(epoch from (m."leftAt" - m."joinedAt")) / 86400
           ) filter (where m."leftAt" is not null) as median_lifetime
    from "Membership" m
    left join "Source" s on s.id = m."sourceId"
    where m."chatId" = ${chatId} and m."joinedAt" >= ${from} and m."joinedAt" <= ${to}
    group by coalesce(s.id, 0)
    order by joins desc
  `;
  return rows.map((r) => {
    const joins = n(r.joins);
    const spend = nn(r.spend);
    const mature7 = n(r.mature_7);
    return {
      sourceId: n(r.source_id),
      slug: String(r.slug),
      title: String(r.title),
      kind: String(r.kind),
      spend,
      currency: String(r.currency),
      joins,
      aliveNow: n(r.alive_now),
      alive7: mature7 ? n(r.alive_7) / mature7 : null,
      talkers: n(r.talkers),
      messages: n(r.messages),
      medianLifetimeDays: nn(r.median_lifetime),
      cpl: spend && joins ? spend / joins : null,
    };
  });
}

/* ----------------------------------------------------------- активность */

export type HeatCell = { weekday: number; hour: number; messages: number };

export async function getActivityHeatmap(scope: Scope): Promise<HeatCell[]> {
  const { chatId, from, to } = scope;
  const rows = await db.$queryRaw<Record<string, unknown>[]>`
    select extract(isodow from (x.at at time zone ${REPORT_TZ}))::int - 1 as weekday,
           extract(hour from (x.at at time zone ${REPORT_TZ}))::int as hour,
           count(*) as messages
    from "Message" x
    where x."chatId" = ${chatId} and x.at >= ${from} and x.at <= ${to}
    group by 1, 2
  `;
  return rows.map((r) => ({ weekday: n(r.weekday), hour: n(r.hour), messages: n(r.messages) }));
}

export type TalkerRow = {
  personId: number;
  tgUserId: bigint;
  username: string | null;
  firstName: string | null;
  lastName: string | null;
  messages: number;
  questions: number;
  lastMessageAt: Date | null;
};

export async function getTopTalkers(scope: Scope, limit = 15): Promise<TalkerRow[]> {
  const { chatId, from, to } = scope;
  const rows = await db.$queryRaw<Record<string, unknown>[]>`
    select p.id as person_id, p."tgUserId", p.username, p."firstName", p."lastName",
           count(*) as messages,
           count(*) filter (where x."isQuestion") as questions,
           max(x.at) as last_message_at
    from "Message" x
    join "Person" p on p.id = x."personId"
    where x."chatId" = ${chatId} and x.at >= ${from} and x.at <= ${to}
    group by p.id
    order by messages desc
    limit ${limit}
  `;
  return rows.map((r) => ({
    personId: n(r.person_id),
    tgUserId: r.tgUserId as bigint,
    username: (r.username as string) ?? null,
    firstName: (r.firstName as string) ?? null,
    lastName: (r.lastName as string) ?? null,
    messages: n(r.messages),
    questions: n(r.questions),
    lastMessageAt: (r.last_message_at as Date) ?? null,
  }));
}

/* ------------------------------------------------------------ сегменты */

export const SEGMENTS = [
  { key: "core", label: "Ядро", hint: `${CORE_MESSAGES}+ сообщений за ${INACTIVE_DAYS} дн.` },
  { key: "active", label: "Активные", hint: `1–${CORE_MESSAGES - 1} сообщений за ${INACTIVE_DAYS} дн.` },
  { key: "sleeping", label: "Засыпают", hint: `писали раньше, молчат ${INACTIVE_DAYS}+ дн.` },
  { key: "lurker", label: "Молчуны", hint: "в группе, не написали ни разу" },
  { key: "left", label: "Ушли", hint: "покинули группу или забанены" },
] as const;

export type SegmentKey = (typeof SEGMENTS)[number]["key"];

/** SQL-выражение сегмента — общее для счётчиков и для фильтра в списке людей. */
export function segmentCondition(key: SegmentKey) {
  const inactive = Prisma.sql`now() - make_interval(days => ${INACTIVE_DAYS}::int)`;
  switch (key) {
    case "core":
      return Prisma.sql`m.status = 'active' and m."lastMessageAt" >= ${inactive} and (
        select count(*) from "Message" x where x."personId" = m."personId" and x."chatId" = m."chatId" and x.at >= ${inactive}
      ) >= ${CORE_MESSAGES}`;
    case "active":
      return Prisma.sql`m.status = 'active' and m."lastMessageAt" >= ${inactive} and (
        select count(*) from "Message" x where x."personId" = m."personId" and x."chatId" = m."chatId" and x.at >= ${inactive}
      ) < ${CORE_MESSAGES}`;
    case "sleeping":
      return Prisma.sql`m.status = 'active' and m."messageCount" > 0 and (m."lastMessageAt" is null or m."lastMessageAt" < ${inactive})`;
    case "lurker":
      return Prisma.sql`m.status = 'active' and m."messageCount" = 0`;
    case "left":
      return Prisma.sql`m.status <> 'active'`;
  }
}

export async function getSegments(scope: Scope): Promise<{ key: SegmentKey; label: string; hint: string; value: number }[]> {
  const { chatId, sourceId } = scope;
  const sf = sourceFilter(sourceId);
  const cells = Prisma.join(
    SEGMENTS.map((s) => Prisma.sql`count(*) filter (where ${segmentCondition(s.key)}) as ${Prisma.raw(s.key)}`),
    ",",
  );
  const rows = await db.$queryRaw<Record<string, unknown>[]>`
    select ${cells} from "Membership" m where m."chatId" = ${chatId} ${sf}
  `;
  const r = rows[0] ?? {};
  return SEGMENTS.map((s) => ({ key: s.key, label: s.label, hint: s.hint, value: n(r[s.key]) }));
}

/* ---------------------------------------------------------------- люди */

export type MemberRow = {
  personId: number;
  tgUserId: bigint;
  username: string | null;
  firstName: string | null;
  lastName: string | null;
  joinedAt: Date;
  leftAt: Date | null;
  status: string;
  messageCount: number;
  lastMessageAt: Date | null;
  sourceTitle: string | null;
  lifetimeDays: number;
  segment: SegmentKey;
};

export type MemberQuery = {
  chatId: number;
  segment?: SegmentKey | "all";
  sourceId?: number | null;
  search?: string;
  sort?: "joined" | "messages" | "lastMessage";
  page?: number;
  perPage?: number;
};

export async function getMembers(q: MemberQuery): Promise<{ rows: MemberRow[]; total: number }> {
  const perPage = q.perPage ?? 50;
  const page = Math.max(1, q.page ?? 1);
  const where: Prisma.Sql[] = [Prisma.sql`m."chatId" = ${q.chatId}`];
  if (q.segment && q.segment !== "all") where.push(segmentCondition(q.segment));
  if (q.sourceId !== null && q.sourceId !== undefined) {
    where.push(q.sourceId === 0 ? Prisma.sql`m."sourceId" is null` : Prisma.sql`m."sourceId" = ${q.sourceId}`);
  }
  if (q.search) {
    const like = `%${q.search.replace(/^@/, "")}%`;
    where.push(Prisma.sql`(p.username ilike ${like} or p."firstName" ilike ${like} or p."lastName" ilike ${like})`);
  }
  const whereSql = Prisma.join(where, " and ");
  const order =
    q.sort === "messages"
      ? Prisma.sql`m."messageCount" desc nulls last`
      : q.sort === "lastMessage"
        ? Prisma.sql`m."lastMessageAt" desc nulls last`
        : Prisma.sql`m."joinedAt" desc`;

  const segmentCase = Prisma.join(
    SEGMENTS.map((s) => Prisma.sql`when ${segmentCondition(s.key)} then ${s.key}`),
    " ",
  );

  const [rows, totals] = await Promise.all([
    db.$queryRaw<Record<string, unknown>[]>`
      select p.id as person_id, p."tgUserId", p.username, p."firstName", p."lastName",
             m."joinedAt", m."leftAt", m.status, m."messageCount", m."lastMessageAt",
             s.title as source_title,
             extract(epoch from (coalesce(m."leftAt", now()) - m."joinedAt")) / 86400 as lifetime_days,
             (case ${segmentCase} else 'lurker' end) as segment
      from "Membership" m
      join "Person" p on p.id = m."personId"
      left join "Source" s on s.id = m."sourceId"
      where ${whereSql}
      order by ${order}
      limit ${perPage} offset ${(page - 1) * perPage}
    `,
    db.$queryRaw<Record<string, unknown>[]>`
      select count(*) as total
      from "Membership" m
      join "Person" p on p.id = m."personId"
      where ${whereSql}
    `,
  ]);

  return {
    total: n(totals[0]?.total),
    rows: rows.map((r) => ({
      personId: n(r.person_id),
      tgUserId: r.tgUserId as bigint,
      username: (r.username as string) ?? null,
      firstName: (r.firstName as string) ?? null,
      lastName: (r.lastName as string) ?? null,
      joinedAt: r.joinedAt as Date,
      leftAt: (r.leftAt as Date) ?? null,
      status: String(r.status),
      messageCount: n(r.messageCount),
      lastMessageAt: (r.lastMessageAt as Date) ?? null,
      sourceTitle: (r.source_title as string) ?? null,
      lifetimeDays: n(r.lifetime_days),
      segment: String(r.segment) as SegmentKey,
    })),
  };
}

/** Активность одного человека по дням — для карточки. */
export async function getPersonActivity(personId: number, chatId: number, days = 90) {
  const rows = await db.$queryRaw<Record<string, unknown>[]>`
    with d as (
      select generate_series((now() at time zone ${REPORT_TZ})::date - make_interval(days => ${days - 1}::int),
                             (now() at time zone ${REPORT_TZ})::date, interval '1 day')::date as day
    )
    select d.day::text as day, coalesce(m.c, 0) as messages
    from d
    left join (
      select (x.at at time zone ${REPORT_TZ})::date as day, count(*) as c
      from "Message" x
      where x."personId" = ${personId} and x."chatId" = ${chatId}
      group by 1
    ) m on m.day = d.day
    order by d.day
  `;
  return rows.map((r) => ({ day: String(r.day), messages: n(r.messages) }));
}

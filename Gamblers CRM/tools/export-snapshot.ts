import { writeFileSync } from "node:fs";
import { db } from "@/lib/db";
import * as m from "@/lib/metrics";

const RANGES: Record<string, number> = { "30d": 30, "90d": 90 };

async function main() {
  const chat = await db.chat.findFirst({ orderBy: { id: "asc" } });
  if (!chat) throw new Error("нет чата");
  const sources = await db.source.findMany({ orderBy: { title: "asc" } });
  const to = new Date();
  const combos: Record<string, unknown> = {};

  for (const [key, n] of Object.entries(RANGES)) {
    const from = new Date(to.getTime() - n * 864e5);
    for (const s of [null, ...sources.map((x) => x.id)]) {
      const scope = { chatId: chat.id, from, to, sourceId: s };
      combos[`${key}:${s ?? "all"}`] = {
        overview: await m.getOverview(scope),
        funnel: await m.getFunnel(scope),
        flow: await m.getDailyFlow(scope),
        segments: await m.getSegments(scope),
      };
    }
  }

  const from90 = new Date(to.getTime() - 90 * 864e5);
  const from30 = new Date(to.getTime() - 30 * 864e5);
  const members = await m.getMembers({ chatId: chat.id, perPage: 250, sort: "messages" });

  const snapshot = {
    meta: {
      chat: chat.title.replace("[demo] ", ""),
      generatedAt: to.toISOString(),
      tz: process.env.REPORT_TZ || "Europe/Kyiv",
      offsets: m.SURVIVAL_OFFSETS,
      weeks: m.ENGAGEMENT_WEEKS,
      segments: m.SEGMENTS,
    },
    sources: sources.map((s) => ({ id: s.id, title: s.title, kind: s.kind })),
    combos,
    survival: await m.getSurvivalCohorts({ chatId: chat.id, from: from90, to }),
    engagement: await m.getEngagementCohorts({ chatId: chat.id, from: from90, to }),
    sourceTable: await m.getSources({ chatId: chat.id, from: from90, to }),
    heatmap: await m.getActivityHeatmap({ chatId: chat.id, from: from30, to }),
    talkers: (await m.getTopTalkers({ chatId: chat.id, from: from30, to }, 12)).map((t) => ({
      name: [t.firstName, t.lastName].filter(Boolean).join(" ") || (t.username ? "@" + t.username : "—"),
      username: t.username,
      messages: t.messages,
      questions: t.questions,
    })),
    members: members.rows.slice(0, 200).map((r) => ({
      name: [r.firstName, r.lastName].filter(Boolean).join(" ") || (r.username ? "@" + r.username : "—"),
      username: r.username,
      segment: r.segment,
      source: r.sourceTitle ?? "Без метки",
      joinedAt: r.joinedAt.toISOString(),
      lifetimeDays: Math.round(r.lifetimeDays * 10) / 10,
      messages: r.messageCount,
      lastMessageAt: r.lastMessageAt?.toISOString() ?? null,
    })),
  };

  const json = JSON.stringify(snapshot, (_k, v) => (typeof v === "bigint" ? Number(v) : v));
  writeFileSync("/tmp/claude-0/snapshot.json", json);
  console.log("размер:", Math.round(json.length / 1024), "КБ");
  await db.$disconnect();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

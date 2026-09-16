/**
 * Демо-данные: синтетический поток по трейдингу за последние ~120 дней.
 * Нужен, чтобы дашборд можно было смотреть и проверять до подключения Telegram.
 * Запуск: npm run db:seed   (данные помечены demo-* и сносятся при повторном запуске)
 */
import { PrismaClient } from "@prisma/client";

const db = new PrismaClient();

const DAYS = 120;
const now = new Date();
const dayStart = (offset: number) => new Date(now.getTime() - offset * 864e5);

let seed = 20260916;
/** Детерминированный ГПСЧ — одинаковый датасет между запусками. */
function rnd() {
  seed = (seed * 1664525 + 1013904223) % 4294967296;
  return seed / 4294967296;
}
const pick = <T,>(arr: T[]) => arr[Math.floor(rnd() * arr.length)];
const poisson = (lambda: number) => {
  let l = Math.exp(-lambda), k = 0, p = 1;
  do { k++; p *= rnd(); } while (p > l);
  return k - 1;
};

const SOURCES = [
  { slug: "demo-blogger-alex", title: "Блогер Alex (YouTube)", kind: "blogger", spend: 1200, quality: 0.85, volume: 5.5 },
  { slug: "demo-tg-ads", title: "Telegram Ads", kind: "ads", spend: 2400, quality: 0.55, volume: 7.5 },
  { slug: "demo-seeding-chats", title: "Посевы в трейдинг-чатах", kind: "seeding", spend: 600, quality: 0.35, volume: 6.0 },
  { slug: "demo-insta-reels", title: "Reels-воронка", kind: "ads", spend: 900, quality: 0.5, volume: 4.0 },
  { slug: "demo-partner-crypto", title: "Партнёр: крипто-канал", kind: "partner", spend: null, quality: 0.75, volume: 2.5 },
  { slug: "demo-organic", title: "Органика / сарафан", kind: "organic", spend: null, quality: 0.95, volume: 1.2 },
];

const FIRST = ["Артём", "Данил", "Игорь", "Олег", "Марина", "Света", "Кирилл", "Рустам", "Ника", "Влад", "Егор", "Алина", "Тимур", "Женя", "Саша", "Макс", "Дима", "Катя", "Лёша", "Юра"];
const LAST = ["Ковальчук", "Петров", "Гринь", "Мороз", "Соколов", "Ткач", "Лисицын", "Кравец", "Юсупов", "Белов", "", "", ""];

async function main() {
  console.log("Чистим прошлые демо-данные…");
  const demoChat = await db.chat.findFirst({ where: { title: { startsWith: "[demo]" } } });
  if (demoChat) await db.chat.delete({ where: { id: demoChat.id } });
  await db.source.deleteMany({ where: { slug: { startsWith: "demo-" } } });
  await db.person.deleteMany({ where: { tgUserId: { gte: 900_000_000n, lt: 910_000_000n } } });

  const chat = await db.chat.create({
    data: {
      tgChatId: -1001234567890n,
      title: "[demo] Поток по трейдингу — общий чат",
      type: "group",
      role: "main",
      lastSyncedAt: now,
    },
  });

  const sources = [];
  for (const s of SOURCES) {
    const source = await db.source.create({
      data: { slug: s.slug, title: s.title, kind: s.kind, spend: s.spend, currency: "USD" },
    });
    const link = await db.inviteLink.create({
      data: {
        link: `https://t.me/+demo_${s.slug.replace(/-/g, "")}`,
        title: s.title,
        chatId: chat.id,
        sourceId: source.id,
        tgUsage: 0,
      },
    });
    sources.push({ ...s, id: source.id, linkId: link.id });
  }

  let tgId = 900_000_001n;
  let created = 0;
  const messages: { chatId: number; personId: number; tgMessageId: bigint; at: Date; charLen: number; wordCount: number; isReply: boolean; hasMedia: boolean; isQuestion: boolean }[] = [];
  let msgCounter = 1n;

  for (let d = DAYS; d >= 0; d--) {
    const date = dayStart(d);
    // Всплески трафика: запуск потока и вебинары
    const boost = d === 110 || d === 75 || d === 40 || d === 12 ? 4.5 : 1;
    for (const s of sources) {
      const joins = poisson(s.volume * boost);
      for (let i = 0; i < joins; i++) {
        const joinedAt = new Date(date.getTime() + Math.floor(rnd() * 864e5));
        if (joinedAt > now) continue;
        const person = await db.person.create({
          data: {
            tgUserId: tgId++,
            username: rnd() > 0.35 ? `user${Math.floor(rnd() * 99999)}` : null,
            firstName: pick(FIRST),
            lastName: pick(LAST) || null,
            isPremium: rnd() > 0.85,
            langCode: rnd() > 0.2 ? "ru" : "uk",
            firstSeenAt: joinedAt,
          },
        });
        created++;

        // Живучесть: качество источника + личный разброс
        const q = Math.min(0.98, Math.max(0.02, s.quality * (0.5 + rnd())));
        const lifetime = q > 0.8 ? 400 : -Math.log(1 - rnd()) * (4 + q * 55);
        const ageDays = (now.getTime() - joinedAt.getTime()) / 864e5;
        const left = lifetime < ageDays;
        const leftAt = left ? new Date(joinedAt.getTime() + lifetime * 864e5) : null;
        const until = leftAt ?? now;

        // Сообщения: интенсивность падает со временем жизни в чате
        const chatty = rnd() < q * 0.75;
        const personMessages: Date[] = [];
        if (chatty) {
          const base = 0.2 + q * 2.2;
          for (let k = 0; k < Math.ceil((until.getTime() - joinedAt.getTime()) / 864e5); k++) {
            const decay = Math.exp(-k / (6 + q * 30));
            const cnt = poisson(base * decay);
            for (let m = 0; m < cnt; m++) {
              const hour = pick([9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 20, 21, 21, 22, 23]);
              const at = new Date(joinedAt.getTime() + k * 864e5);
              at.setHours(hour, Math.floor(rnd() * 60), Math.floor(rnd() * 60), 0);
              if (at >= joinedAt && at <= until && at <= now) personMessages.push(at);
            }
          }
        }
        personMessages.sort((a, b) => +a - +b);

        await db.membership.create({
          data: {
            personId: person.id,
            chatId: chat.id,
            joinedAt,
            leftAt,
            status: left ? (rnd() > 0.93 ? "kicked" : "left") : "active",
            inviteLinkId: s.linkId,
            sourceId: s.id,
            messageCount: personMessages.length,
            firstMessageAt: personMessages[0] ?? null,
            lastMessageAt: personMessages[personMessages.length - 1] ?? null,
          },
        });

        await db.event.create({
          data: {
            chatId: chat.id,
            personId: person.id,
            type: "join",
            at: joinedAt,
            inviteLinkId: s.linkId,
            dedupKey: `demo:join:${person.id}`,
          },
        });
        if (leftAt) {
          await db.event.create({
            data: {
              chatId: chat.id,
              personId: person.id,
              type: rnd() > 0.93 ? "kick" : "leave",
              at: leftAt,
              dedupKey: `demo:leave:${person.id}`,
            },
          });
        }

        for (const at of personMessages) {
          const words = 2 + Math.floor(rnd() * 24);
          messages.push({
            chatId: chat.id,
            personId: person.id,
            tgMessageId: msgCounter++,
            at,
            charLen: words * 6,
            wordCount: words,
            isReply: rnd() > 0.6,
            hasMedia: rnd() > 0.88,
            isQuestion: rnd() > 0.72,
          });
        }
      }
    }
  }

  console.log(`Записываем ${messages.length} сообщений…`);
  for (let i = 0; i < messages.length; i += 2000) {
    await db.message.createMany({ data: messages.slice(i, i + 2000) });
  }

  for (const s of sources) {
    const usage = await db.membership.count({ where: { inviteLinkId: s.linkId } });
    await db.inviteLink.update({ where: { id: s.linkId }, data: { tgUsage: usage } });
  }

  console.log(`Готово: ${created} участников, ${messages.length} сообщений, ${sources.length} источников.`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => db.$disconnect());

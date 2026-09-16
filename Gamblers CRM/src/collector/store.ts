import { Api } from "telegram";
import { db } from "@/lib/db";

const STORE_PREVIEW = process.env.STORE_MESSAGE_PREVIEW === "true";

/** Канонический id чата в формате Bot API: -100… для супергрупп и каналов, -… для старых групп. */
export function canonicalChatId(entity: Api.Chat | Api.Channel) {
  return entity instanceof Api.Channel ? BigInt(`-100${entity.id}`) : BigInt(`-${entity.id}`);
}

export async function upsertChat(entity: Api.Chat | Api.Channel) {
  const tgChatId = canonicalChatId(entity);
  return db.chat.upsert({
    where: { tgChatId },
    create: {
      tgChatId,
      title: entity.title ?? String(tgChatId),
      type: entity instanceof Api.Channel && !entity.megagroup ? "channel" : "group",
      accessHash: entity instanceof Api.Channel ? String(entity.accessHash ?? "") : null,
    },
    update: { title: entity.title ?? undefined },
  });
}

export async function upsertPerson(user: Api.User) {
  const tgUserId = BigInt(String(user.id));
  return db.person.upsert({
    where: { tgUserId },
    create: {
      tgUserId,
      username: user.username ?? null,
      firstName: user.firstName ?? null,
      lastName: user.lastName ?? null,
      isBot: Boolean(user.bot),
      isPremium: Boolean(user.premium),
      langCode: user.langCode ?? null,
    },
    update: {
      username: user.username ?? null,
      firstName: user.firstName ?? null,
      lastName: user.lastName ?? null,
      isPremium: Boolean(user.premium),
    },
  });
}

/** Вступление: пишем событие и поднимаем участие. Повторный вход считаем новой когортой. */
export async function recordJoin(opts: {
  chatId: number;
  personId: number;
  at: Date;
  inviteLinkId?: number | null;
  inviterTgId?: bigint | null;
  dedupKey: string;
  raw?: unknown;
}) {
  const { chatId, personId, at, inviteLinkId = null, inviterTgId = null, dedupKey } = opts;
  const created = await db.event.createMany({
    data: [{ chatId, personId, type: "join", at, inviteLinkId, inviterTgId, dedupKey, raw: opts.raw as never }],
    skipDuplicates: true,
  });
  if (created.count === 0) return;

  const existing = await db.membership.findUnique({ where: { personId_chatId: { personId, chatId } } });
  const sourceId = inviteLinkId
    ? (await db.inviteLink.findUnique({ where: { id: inviteLinkId }, select: { sourceId: true } }))?.sourceId ?? null
    : null;

  if (!existing) {
    await db.membership.create({
      data: { personId, chatId, joinedAt: at, status: "active", inviteLinkId, sourceId, inviterTgId },
    });
    return;
  }
  await db.membership.update({
    where: { id: existing.id },
    data: {
      status: "active",
      leftAt: null,
      joinedAt: at > existing.joinedAt ? at : existing.joinedAt,
      joinCount: existing.joinCount + 1,
      inviteLinkId: inviteLinkId ?? existing.inviteLinkId,
      sourceId: sourceId ?? existing.sourceId,
    },
  });
}

export async function recordLeave(opts: {
  chatId: number;
  personId: number;
  at: Date;
  kicked?: boolean;
  dedupKey: string;
}) {
  const { chatId, personId, at, kicked = false, dedupKey } = opts;
  const created = await db.event.createMany({
    data: [{ chatId, personId, type: kicked ? "kick" : "leave", at, dedupKey }],
    skipDuplicates: true,
  });
  if (created.count === 0) return;

  await db.membership.updateMany({
    where: { personId, chatId },
    data: { status: kicked ? "kicked" : "left", leftAt: at },
  });
}

/** Участник виден в списке, но события вступления нет — заводим участие по дате из Telegram. */
export async function ensureMembership(chatId: number, personId: number, joinedAt: Date) {
  const existing = await db.membership.findUnique({ where: { personId_chatId: { personId, chatId } } });
  if (existing) {
    if (existing.status !== "active") {
      await db.membership.update({ where: { id: existing.id }, data: { status: "active", leftAt: null } });
    }
    return;
  }
  await db.membership.create({ data: { personId, chatId, joinedAt, status: "active" } });
  await db.event.createMany({
    data: [{ chatId, personId, type: "join", at: joinedAt, dedupKey: `participant:${chatId}:${personId}` }],
    skipDuplicates: true,
  });
}

export type MessageInput = {
  chatId: number;
  personId: number;
  tgMessageId: bigint;
  at: Date;
  text: string;
  isReply: boolean;
  hasMedia: boolean;
};

export async function saveMessages(rows: MessageInput[]) {
  if (rows.length === 0) return 0;
  const res = await db.message.createMany({
    data: rows.map((r) => ({
      chatId: r.chatId,
      personId: r.personId,
      tgMessageId: r.tgMessageId,
      at: r.at,
      charLen: r.text.length,
      wordCount: r.text.trim() ? r.text.trim().split(/\s+/).length : 0,
      isReply: r.isReply,
      hasMedia: r.hasMedia,
      isQuestion: r.text.includes("?"),
      preview: STORE_PREVIEW ? r.text.slice(0, 200) || null : null,
    })),
    skipDuplicates: true,
  });
  return res.count;
}

/** Пересчёт денормализованных счётчиков участия — после каждой выгрузки. */
export async function recomputeMembershipStats(chatId: number) {
  await db.$executeRaw`
    update "Membership" m
    set "messageCount" = coalesce(s.cnt, 0),
        "firstMessageAt" = s.first_at,
        "lastMessageAt" = s.last_at
    from (
      select x."personId", count(*) as cnt, min(x.at) as first_at, max(x.at) as last_at
      from "Message" x
      where x."chatId" = ${chatId}
      group by x."personId"
    ) s
    where m."chatId" = ${chatId} and m."personId" = s."personId"
  `;
}

export async function getSyncState(key: string) {
  const row = await db.syncState.findUnique({ where: { key } });
  return row?.value ?? null;
}

export async function setSyncState(key: string, value: string) {
  await db.syncState.upsert({ where: { key }, create: { key, value }, update: { value } });
}

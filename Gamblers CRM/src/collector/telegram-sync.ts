/**
 * Общая логика выгрузки из Telegram: ссылки, участники, сообщения, журнал администратора.
 * backfill.ts тянет всё с нуля, sync.ts — только новое; отличается лишь глубиной.
 */
import bigInt from "big-integer";
import { Api, TelegramClient } from "telegram";
import { db } from "@/lib/db";
import {
  ensureMembership,
  getSyncState,
  recomputeMembershipStats,
  recordJoin,
  recordLeave,
  saveMessages,
  setSyncState,
  upsertChat,
  upsertPerson,
  type MessageInput,
} from "./store";

const secondsToDate = (s: number) => new Date(s * 1000);

/** Пригласительные ссылки: единица атрибуции. Источник назначается в интерфейсе. */
export async function syncInviteLinks(client: TelegramClient, entity: Api.Chat | Api.Channel, chatId: number) {
  let saved = 0;
  try {
    let offsetDate: number | undefined;
    let offsetLink: string | undefined;
    for (;;) {
      const res = (await client.invoke(
        new Api.messages.GetExportedChatInvites({
          peer: entity,
          adminId: new Api.InputUserSelf(),
          limit: 100,
          offsetDate,
          offsetLink,
        }),
      )) as Api.messages.ExportedChatInvites;

      const invites = res.invites.filter((i): i is Api.ChatInviteExported => i instanceof Api.ChatInviteExported);
      if (invites.length === 0) break;

      for (const inv of invites) {
        await db.inviteLink.upsert({
          where: { link: inv.link },
          create: {
            link: inv.link,
            title: inv.title ?? null,
            chatId,
            tgUsage: inv.usage ?? 0,
            isRevoked: Boolean(inv.revoked),
            createdAt: secondsToDate(inv.date),
            expiresAt: inv.expireDate ? secondsToDate(inv.expireDate) : null,
          },
          update: {
            title: inv.title ?? null,
            tgUsage: inv.usage ?? 0,
            isRevoked: Boolean(inv.revoked),
          },
        });
        saved++;
      }
      const last = invites[invites.length - 1];
      offsetDate = last.date;
      offsetLink = last.link;
      if (invites.length < 100) break;
    }
  } catch (e) {
    console.warn(`  ссылки: недоступны (${(e as Error).message}) — нужны права администратора`);
  }
  return saved;
}

/** Текущий состав группы. Даёт дату вступления даже без журнала администратора. */
export async function syncParticipants(client: TelegramClient, entity: Api.Chat | Api.Channel, chatId: number) {
  const seen = new Set<number>();
  let count = 0;
  for await (const user of client.iterParticipants(entity, {})) {
    if (!(user instanceof Api.User) || user.bot) continue;
    const person = await upsertPerson(user);
    seen.add(person.id);
    const participant = (user as Api.User & { participant?: { date?: number } }).participant;
    const joinedAt = participant?.date ? secondsToDate(participant.date) : new Date();
    await ensureMembership(chatId, person.id, joinedAt);
    count++;
  }

  // Кто числился активным, но в списке его нет — значит вышел между выгрузками.
  const active = await db.membership.findMany({
    where: { chatId, status: "active" },
    select: { id: true, personId: true },
  });
  const gone = active.filter((m) => !seen.has(m.personId));
  const at = new Date();
  for (const m of gone) {
    await recordLeave({
      chatId,
      personId: m.personId,
      at,
      dedupKey: `diff:${chatId}:${m.personId}:${at.toISOString().slice(0, 10)}`,
    });
  }
  return { present: count, left: gone.length };
}

/** Сообщения. minId = 0 при полной выгрузке, иначе последний сохранённый id. */
export async function syncMessages(
  client: TelegramClient,
  entity: Api.Chat | Api.Channel,
  chatId: number,
  opts: { minId?: number; limit?: number } = {},
) {
  const minId = opts.minId ?? 0;
  let batch: MessageInput[] = [];
  let saved = 0;
  let maxId = minId;

  for await (const msg of client.iterMessages(entity, { minId, limit: opts.limit, reverse: true })) {
    if (typeof msg.id === "number" && msg.id > maxId) maxId = msg.id;

    // Служебные сообщения о входах и выходах — запасной источник событий без прав администратора.
    if (msg instanceof Api.MessageService) {
      await handleServiceMessage(msg, chatId);
      continue;
    }
    const sender = msg.senderId ? await msg.getSender() : null;
    if (!(sender instanceof Api.User) || sender.bot) continue;

    const person = await upsertPerson(sender);
    batch.push({
      chatId,
      personId: person.id,
      tgMessageId: BigInt(msg.id),
      at: secondsToDate(msg.date),
      text: msg.message ?? "",
      isReply: Boolean(msg.replyTo),
      hasMedia: Boolean(msg.media),
    });

    if (batch.length >= 500) {
      saved += await saveMessages(batch);
      batch = [];
    }
  }
  saved += await saveMessages(batch);
  if (maxId > minId) await setSyncState(`chat:${chatId}:lastMessageId`, String(maxId));
  return saved;
}

async function handleServiceMessage(msg: Api.MessageService, chatId: number) {
  const at = secondsToDate(msg.date);
  const action = msg.action;

  const addUser = async (tgUserId: bigint, inviterTgId: bigint | null) => {
    const person = await db.person.findUnique({ where: { tgUserId } });
    if (!person) return;
    await recordJoin({
      chatId,
      personId: person.id,
      at,
      inviterTgId,
      dedupKey: `service:${chatId}:${msg.id}:${tgUserId}`,
    });
  };

  if (action instanceof Api.MessageActionChatAddUser) {
    for (const uid of action.users) await addUser(BigInt(String(uid)), msg.fromId ? BigInt(String(msg.fromId)) : null);
  } else if (action instanceof Api.MessageActionChatJoinedByLink) {
    if (msg.fromId instanceof Api.PeerUser) {
      await addUser(BigInt(String(msg.fromId.userId)), BigInt(String(action.inviterId)));
    }
  } else if (action instanceof Api.MessageActionChatDeleteUser) {
    const person = await db.person.findUnique({ where: { tgUserId: BigInt(String(action.userId)) } });
    if (person) {
      await recordLeave({
        chatId,
        personId: person.id,
        at,
        kicked: msg.fromId instanceof Api.PeerUser && String(msg.fromId.userId) !== String(action.userId),
        dedupKey: `service:${chatId}:${msg.id}:${action.userId}`,
      });
    }
  }
}

/**
 * Журнал администратора — единственный способ узнать, по какой ссылке пришёл человек.
 * Работает только если аккаунт админ группы; без прав молча пропускаем.
 */
export async function syncAdminLog(
  client: TelegramClient,
  entity: Api.Chat | Api.Channel,
  chatId: number,
  opts: { minId?: bigint } = {},
) {
  if (!(entity instanceof Api.Channel)) return 0;
  const minId = opts.minId ?? 0n;
  let maxId = minId;
  let handled = 0;

  try {
    let maxIdCursor = 0n;
    for (;;) {
      const res = (await client.invoke(
        new Api.channels.GetAdminLog({
          channel: entity,
          q: "",
          limit: 100,
          maxId: bigInt(maxIdCursor.toString()),
          minId: bigInt(minId.toString()),
          eventsFilter: new Api.ChannelAdminLogEventsFilter({ join: true, leave: true, invites: true }),
        }),
      )) as Api.channels.AdminLogResults;

      if (res.events.length === 0) break;

      for (const user of res.users) if (user instanceof Api.User) await upsertPerson(user);

      for (const ev of res.events) {
        const id = BigInt(String(ev.id));
        if (id > maxId) maxId = id;
        if (maxIdCursor === 0n || id < maxIdCursor) maxIdCursor = id;

        const person = await db.person.findUnique({ where: { tgUserId: BigInt(String(ev.userId)) } });
        if (!person) continue;
        const at = secondsToDate(ev.date);
        const action = ev.action;

        if (action instanceof Api.ChannelAdminLogEventActionParticipantJoinByInvite) {
          const invite = action.invite;
          const link =
            invite instanceof Api.ChatInviteExported
              ? await db.inviteLink.findUnique({ where: { link: invite.link } })
              : null;
          await recordJoin({
            chatId,
            personId: person.id,
            at,
            inviteLinkId: link?.id ?? null,
            dedupKey: `adminlog:${chatId}:${ev.id}`,
          });
          handled++;
        } else if (action instanceof Api.ChannelAdminLogEventActionParticipantJoin) {
          await recordJoin({ chatId, personId: person.id, at, dedupKey: `adminlog:${chatId}:${ev.id}` });
          handled++;
        } else if (action instanceof Api.ChannelAdminLogEventActionParticipantLeave) {
          await recordLeave({ chatId, personId: person.id, at, dedupKey: `adminlog:${chatId}:${ev.id}` });
          handled++;
        }
      }
      if (res.events.length < 100) break;
    }
    if (maxId > minId) await setSyncState(`chat:${chatId}:lastAdminLogId`, String(maxId));
  } catch (e) {
    console.warn(`  журнал администратора: недоступен (${(e as Error).message}) — атрибуция по ссылкам не соберётся`);
  }
  return handled;
}

export async function runForChat(
  client: TelegramClient,
  entity: Api.Chat | Api.Channel,
  mode: "backfill" | "sync",
) {
  const chat = await upsertChat(entity);
  console.log(`\n${chat.title} (${chat.tgChatId})`);

  const links = await syncInviteLinks(client, entity, chat.id);
  console.log(`  ссылок: ${links}`);

  const lastMessageId = mode === "sync" ? Number(await getSyncState(`chat:${chat.id}:lastMessageId`)) || 0 : 0;
  const lastLogId = mode === "sync" ? BigInt(await getSyncState(`chat:${chat.id}:lastAdminLogId`) ?? "0") : 0n;

  const logEvents = await syncAdminLog(client, entity, chat.id, { minId: lastLogId });
  console.log(`  событий журнала: ${logEvents}`);

  const participants = await syncParticipants(client, entity, chat.id);
  console.log(`  участников сейчас: ${participants.present}, помечено ушедшими: ${participants.left}`);

  const messages = await syncMessages(client, entity, chat.id, { minId: lastMessageId });
  console.log(`  новых сообщений: ${messages}`);

  await recomputeMembershipStats(chat.id);
  await db.chat.update({ where: { id: chat.id }, data: { lastSyncedAt: new Date() } });
  console.log("  готово");
}

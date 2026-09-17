import "dotenv/config";
import { Api, TelegramClient } from "telegram";
import { StringSession } from "telegram/sessions";

// GramJS держит фоновую петлю обновлений и после отключения роняет процесс
// ошибкой TIMEOUT — например, пока скрипт ждёт ответа на вопрос в терминале.
// Эти ошибки к нашей работе отношения не имеют.
const BACKGROUND_NOISE = ["TIMEOUT", "Not connected", "Connection closed"];
process.on("unhandledRejection", (reason) => {
  const message = reason instanceof Error ? reason.message : String(reason);
  if (BACKGROUND_NOISE.some((m) => message.includes(m))) return;
  console.error("\nНе получилось: " + message);
  process.exit(1);
});

export function requireEnv(name: string) {
  const v = process.env[name];
  if (!v) throw new Error(`Не задан ${name} в .env`);
  return v;
}

export async function createClient(session = process.env.TG_SESSION ?? "") {
  const apiId = Number(requireEnv("TG_API_ID"));
  const apiHash = requireEnv("TG_API_HASH");
  const client = new TelegramClient(new StringSession(session), apiId, apiHash, {
    connectionRetries: 5,
    // GramJS сам ждёт при FLOOD_WAIT короче порога — иначе Telegram банит на часы.
    floodSleepThreshold: 120,
  });
  return client;
}

/** Список чатов из TG_CHATS: @username или -100… id через запятую. */
export function chatRefs(): string[] {
  return (process.env.TG_CHATS ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export async function resolveEntity(client: TelegramClient, ref: string) {
  const asNumber = Number(ref);
  const entity = await client.getEntity(Number.isFinite(asNumber) && ref.startsWith("-") ? asNumber : ref);
  if (entity instanceof Api.User) throw new Error(`${ref} — это пользователь, а не группа`);
  return entity as Api.Chat | Api.Channel;
}

export const toNumber = (v: unknown) => Number(String(v));

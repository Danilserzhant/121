/**
 * Вход в Telegram под личным аккаунтом.
 * Спрашивает api_id/api_hash, если их ещё нет, и сохраняет всё в .env.
 * Строка сессии = доступ к аккаунту: она остаётся на этой машине и в ваших секретах.
 */
import "dotenv/config";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { createInterface } from "node:readline";

// Свой ask вместо readline/promises: тот молча зависает на втором вопросе,
// когда ввод приходит не из терминала (запуск в контейнере, через pipe).
const rl = createInterface({ input: process.stdin });
const pending: string[] = [];
const waiting: ((line: string) => void)[] = [];
rl.on("line", (line) => {
  const next = waiting.shift();
  if (next) next(line);
  else pending.push(line);
});

const ask = (q: string) =>
  new Promise<string>((resolve) => {
    process.stdout.write(q);
    const buffered = pending.shift();
    if (buffered !== undefined) resolve(buffered);
    else waiting.push(resolve);
  });

const ENV_PATH = ".env";

/** Обновляет ключ в .env, сохраняя остальные строки. */
function setEnv(key: string, value: string) {
  const current = existsSync(ENV_PATH) ? readFileSync(ENV_PATH, "utf8") : "";
  const line = `${key}="${value}"`;
  const next = new RegExp(`^${key}=.*$`, "m").test(current)
    ? current.replace(new RegExp(`^${key}=.*$`, "m"), line)
    : `${current.replace(/\s*$/, "")}\n${line}\n`;
  writeFileSync(ENV_PATH, next.startsWith("\n") ? next.slice(1) : next);
  process.env[key] = value;
}

async function main() {
  console.log("Подключение Telegram-аккаунта\n");

  if (!process.env.TG_API_ID || !process.env.TG_API_HASH) {
    console.log("Нужны api_id и api_hash. Возьмите их здесь:");
    console.log("  https://my.telegram.org → API development tools → создать приложение");
    console.log("  (любое название, поле URL можно оставить пустым)\n");
    const apiId = (await ask("api_id: ")).trim();
    const apiHash = (await ask("api_hash: ")).trim();
    if (!/^\d+$/.test(apiId)) throw new Error("api_id — это число");
    if (apiHash.length < 16) throw new Error("api_hash выглядит неполным");
    setEnv("TG_API_ID", apiId);
    setEnv("TG_API_HASH", apiHash);
    console.log("Записал в .env\n");
  }

  // Клиент создаём только после того, как ключи точно есть.
  const { createClient } = await import("./client");
  const client = await createClient("");

  console.log("Код придёт в Telegram. Никому его не пересылайте — код и пароль дают доступ к аккаунту.\n");
  await client.start({
    phoneNumber: () => ask("Номер телефона (+380…): "),
    password: () => ask("Пароль двухфакторки: "),
    phoneCode: () => ask("Код из Telegram: "),
    onError: (err) => console.error("Ошибка входа:", err.message),
  });

  const session = String(client.session.save());
  const me = await client.getMe();
  const who = "username" in me && me.username ? "@" + me.username : `id ${me.id}`;
  setEnv("TG_SESSION", session);

  console.log(`\nГотово. Вошли как ${who}. Строка сессии сохранена в .env.\n`);
  console.log("TG_SESSION (понадобится, если разворачиваете не на этой машине):\n");
  console.log(session + "\n");
  console.log("Дальше:");
  console.log("  npm run tg:chats   — покажет ваши группы: id для TG_CHATS и есть ли права админа");
  console.log("  npm run tg:backfill — первая выгрузка истории (нужен DATABASE_URL)");

  await client.disconnect();
  rl.close();
}

main().catch((e) => {
  console.error("\n" + (e instanceof Error ? e.message : String(e)));
  rl.close();
  process.exit(1);
});

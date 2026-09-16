/**
 * Вход в Telegram под личным аккаунтом. Строка сессии = доступ к аккаунту,
 * поэтому пишем её в .env (он в .gitignore) и никуда больше.
 */
import "dotenv/config";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createInterface } from "node:readline/promises";
import { createClient } from "./client";

const rl = createInterface({ input: process.stdin, output: process.stdout });
const ask = (q: string) => rl.question(q);

async function main() {
  const client = await createClient("");
  await client.start({
    phoneNumber: () => ask("Номер телефона (+380…): "),
    password: () => ask("Пароль двухфакторки: "),
    phoneCode: () => ask("Код из Telegram: "),
    onError: (err) => console.error("Ошибка входа:", err.message),
  });

  const session = String(client.session.save());
  const me = await client.getMe();
  console.log(`\nВошли как ${"username" in me ? "@" + me.username : me.id}`);

  const envPath = ".env";
  const current = existsSync(envPath) ? readFileSync(envPath, "utf8") : "";
  const next = current.includes("TG_SESSION=")
    ? current.replace(/TG_SESSION=.*/g, `TG_SESSION="${session}"`)
    : `${current.trimEnd()}\nTG_SESSION="${session}"\n`;
  writeFileSync(envPath, next);
  console.log("Строка сессии записана в .env (TG_SESSION). Это доступ к аккаунту — никому её не передавайте.");
  console.log("Дальше: npm run tg:chats — покажет id групп для TG_CHATS, затем npm run tg:backfill.");

  await client.disconnect();
  rl.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

/**
 * Вход в Telegram под личным аккаунтом.
 * Строка сессии = доступ к аккаунту: она остаётся в вашем .env и в ваших секретах.
 */
import "dotenv/config";
import { ask, closePrompt, ensureApiCredentials, setEnv } from "./prompt";

async function main() {
  console.log("Подключение Telegram-аккаунта\n");
  await ensureApiCredentials();

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
  console.log("Дальше: npm run setup — мастер доведёт до дашборда с вашими данными.");

  await client.disconnect();
  closePrompt();
}

main().catch((e) => {
  console.error("\n" + (e instanceof Error ? e.message : String(e)));
  closePrompt();
  process.exit(1);
});

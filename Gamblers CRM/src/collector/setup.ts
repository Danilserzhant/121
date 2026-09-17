/**
 * Мастер настройки: доводит от пустого .env до дашборда с вашими данными.
 * Вход в Telegram, выбор чатов, база, первая выгрузка — по шагам, с вопросами.
 * Запуск: npm run setup
 */
import "dotenv/config";
import { execSync } from "node:child_process";
import { Api } from "telegram";
import { ask, closePrompt, ensureApiCredentials, setEnv } from "./prompt";

const step = (n: number, title: string) => console.log(`\n── Шаг ${n}. ${title}\n`);

async function main() {
  console.log("Настройка Gamblers CRM\n");
  console.log("Пройдём четыре шага: аккаунт Telegram → чаты → база → первая выгрузка.");
  console.log("Всё, что вы введёте, остаётся в .env на этой машине.");

  /* 1. Аккаунт */
  step(1, "Аккаунт Telegram");
  await ensureApiCredentials();
  const { createClient } = await import("./client");
  const client = await createClient(process.env.TG_SESSION ?? "");

  if (process.env.TG_SESSION) {
    await client.connect();
    if (!(await client.isUserAuthorized())) {
      throw new Error("Сессия в .env недействительна — удалите строку TG_SESSION и запустите заново");
    }
    console.log("Сессия уже есть, вход не нужен.");
  } else {
    console.log("Код придёт в Telegram. Никому его не пересылайте.\n");
    await client.start({
      phoneNumber: () => ask("Номер телефона (+380…): "),
      password: () => ask("Пароль двухфакторки: "),
      phoneCode: () => ask("Код из Telegram: "),
      onError: (err) => console.error("Ошибка входа:", err.message),
    });
    setEnv("TG_SESSION", String(client.session.save()));
    console.log("Вошли, сессия сохранена в .env.");
  }
  const me = await client.getMe();
  console.log(`Аккаунт: ${"username" in me && me.username ? "@" + me.username : "id " + me.id}`);

  /* 2. Чаты */
  step(2, "Какие чаты отслеживаем");
  if (process.env.TG_CHATS) {
    const keep = (await ask(`Сейчас в .env: ${process.env.TG_CHATS}\nОставить? [Enter — да, n — выбрать заново]: `)).trim();
    if (keep.toLowerCase() !== "n") {
      console.log("Оставляю как есть.");
      await stopClient(client);
      await databaseStep();
      await backfillStep();
      return;
    }
  }
  const chats: { ref: string; title: string; kind: string; members: string; admin: string }[] = [];
  for (const dialog of await client.getDialogs({ limit: 200 })) {
    const e = dialog.entity;
    if (e instanceof Api.Channel) {
      chats.push({
        ref: `-100${e.id}`,
        title: e.title ?? "",
        kind: e.megagroup ? "супергруппа" : "канал",
        members: String(e.participantsCount ?? "?"),
        admin: e.creator ? "владелец" : e.adminRights ? "админ" : "нет",
      });
    } else if (e instanceof Api.Chat) {
      chats.push({
        ref: `-${e.id}`,
        title: e.title ?? "",
        kind: "группа",
        members: String(e.participantsCount ?? "?"),
        admin: e.creator ? "владелец" : e.adminRights ? "админ" : "нет",
      });
    }
  }
  if (chats.length === 0) throw new Error("Аккаунт не состоит ни в одной группе");

  const pad = (s: string, n: number) => s.padEnd(n).slice(0, n);
  console.log(pad("  №", 5) + pad("Название", 36) + pad("Тип", 14) + pad("Людей", 8) + "Права");
  console.log("  " + "-".repeat(84));
  chats.forEach((c, i) => {
    console.log(pad(`  ${i + 1}`, 5) + pad(c.title, 36) + pad(c.kind, 14) + pad(c.members, 8) + c.admin);
  });

  const answer = (await ask("\nНомера чатов через запятую (например 1,3): ")).trim();
  const picked = answer
    .split(",")
    .map((s) => chats[Number(s.trim()) - 1])
    .filter(Boolean);
  if (picked.length === 0) throw new Error("Ничего не выбрано");
  setEnv("TG_CHATS", picked.map((c) => c.ref).join(","));
  console.log("\nБудем отслеживать: " + picked.map((c) => c.title).join(", "));

  const noRights = picked.filter((c) => c.admin === "нет");
  if (noRights.length) {
    console.log(
      "\nВнимание: в этих чатах у аккаунта нет прав администратора — " +
        noRights.map((c) => c.title).join(", ") +
        ".\nСообщения, состав и выходы соберутся, но источники останутся «Без метки»:" +
        "\nатрибуция по пригласительным ссылкам читается из журнала администратора.",
    );
  }
  // Клиент гасим до вопросов про базу: иначе его фоновая петля падает по таймауту,
  // пока пользователь ходит за строкой подключения.
  await stopClient(client);
  await databaseStep();
  await backfillStep();
}

/** Останавливает клиент вместе с фоновыми петлями. */
async function stopClient(client: { destroy: () => Promise<void> }) {
  try {
    await client.destroy();
  } catch {
    // уже отключён — не важно
  }
}

async function databaseStep() {
  step(3, "База данных");
  if (!process.env.DATABASE_URL) {
    console.log("Нужна строка подключения к PostgreSQL.");
    console.log("Бесплатно и без карты: https://neon.com → новый проект → Connection string (pooled).\n");
    const url = (await ask("DATABASE_URL: ")).trim();
    if (!/^postgres(ql)?:\/\//.test(url)) throw new Error("Строка должна начинаться с postgresql://");
    setEnv("DATABASE_URL", url);
  } else {
    console.log("DATABASE_URL уже задан в .env.");
  }

  console.log("Создаю таблицы…");
  execSync("npx prisma db push --skip-generate", { stdio: "inherit", env: process.env });
}

async function backfillStep() {
  step(4, "Первая выгрузка");
  console.log("Тянем историю: участников, сообщения, вступления и выходы.");
  console.log("На большом чате это надолго — прерывать не нужно, повторный запуск продолжит с места остановки.\n");
  execSync("npx tsx src/collector/backfill.ts", { stdio: "inherit", env: process.env });

  console.log("\n────────────────────────────────────────");
  console.log("Готово. Запустите дашборд:  npm run dev");
  console.log("Дальше держать данные свежими:  npm run tg:sync  (по расписанию, раз в 10–60 минут)");
  closePrompt();
}

main().catch((e) => {
  console.error("\nНе получилось: " + (e instanceof Error ? e.message : String(e)));
  closePrompt();
  process.exit(1);
});

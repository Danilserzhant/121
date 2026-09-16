/**
 * Показывает, к каким группам и каналам имеет доступ подключённый аккаунт:
 * id для TG_CHATS, число участников и есть ли права администратора
 * (от них зависит атрибуция по пригласительным ссылкам).
 */
import "dotenv/config";
import { Api } from "telegram";
import { createClient } from "./client";

async function main() {
  const client = await createClient();
  await client.connect();
  if (!(await client.isUserAuthorized())) throw new Error("Нет сессии — сначала npm run tg:login");

  const me = await client.getMe();
  console.log(`Аккаунт: ${"username" in me && me.username ? "@" + me.username : ""} id ${me.id}\n`);

  const rows: { id: string; title: string; kind: string; members: string; admin: string }[] = [];
  for (const dialog of await client.getDialogs({ limit: 200 })) {
    const e = dialog.entity;
    if (e instanceof Api.Channel) {
      const isAdmin = Boolean(e.creator || e.adminRights);
      rows.push({
        id: `-100${e.id}`,
        title: e.title ?? "",
        kind: e.megagroup ? "супергруппа" : "канал",
        members: String(e.participantsCount ?? "?"),
        admin: e.creator ? "владелец" : isAdmin ? "админ" : "нет",
      });
    } else if (e instanceof Api.Chat) {
      rows.push({
        id: `-${e.id}`,
        title: e.title ?? "",
        kind: "группа",
        members: String(e.participantsCount ?? "?"),
        admin: e.creator ? "владелец" : e.adminRights ? "админ" : "нет",
      });
    }
  }

  if (rows.length === 0) {
    console.log("Групп не нашлось — аккаунт ни в одной не состоит.");
  } else {
    const pad = (s: string, n: number) => s.padEnd(n).slice(0, n);
    console.log(pad("ID для TG_CHATS", 18) + pad("Название", 38) + pad("Тип", 14) + pad("Людей", 8) + "Права");
    console.log("-".repeat(88));
    for (const r of rows) {
      console.log(pad(r.id, 18) + pad(r.title, 38) + pad(r.kind, 14) + pad(r.members, 8) + r.admin);
    }
    console.log(
      "\nВ TG_CHATS впишите id нужных групп через запятую." +
        "\nБез прав администратора соберутся сообщения, состав и выходы, но не атрибуция по ссылкам.",
    );
  }

  await client.disconnect();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

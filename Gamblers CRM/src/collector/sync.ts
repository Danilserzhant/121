/** Догрузка нового: сообщения и события с прошлого запуска. Ставится в крон раз в 10–15 минут. */
import "dotenv/config";
import { db } from "@/lib/db";
import { chatRefs, createClient, resolveEntity } from "./client";
import { runForChat } from "./telegram-sync";

async function main() {
  const refs = chatRefs();
  if (refs.length === 0) throw new Error("Не задан TG_CHATS в .env");

  const client = await createClient();
  await client.connect();
  if (!(await client.isUserAuthorized())) throw new Error("Нет сессии — выполните npm run tg:login");

  for (const ref of refs) {
    const entity = await resolveEntity(client, ref);
    await runForChat(client, entity, "sync");
  }

  await client.disconnect();
  await db.$disconnect();
}

main().catch(async (e) => {
  console.error(e);
  await db.$disconnect();
  process.exit(1);
});

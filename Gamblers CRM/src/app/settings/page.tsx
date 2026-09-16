import { Card, Empty, PageHeader } from "@/components/ui";
import { db } from "@/lib/db";
import { INACTIVE_DAYS, REPORT_TZ } from "@/lib/env";
import { dateTime, money, num } from "@/lib/format";
import { LinkSourceSelect } from "./link-source-select";
import { SourceForm } from "./source-form";

export const dynamic = "force-dynamic";

function Status({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px]">
      <span aria-hidden style={{ color: ok ? "var(--good)" : "var(--critical)" }}>
        {ok ? "●" : "○"}
      </span>
      {children}
    </span>
  );
}

export default async function SettingsPage() {
  const [chats, sources, links] = await Promise.all([
    db.chat.findMany({ orderBy: { id: "asc" }, include: { _count: { select: { memberships: true, messages: true } } } }),
    db.source.findMany({ orderBy: { title: "asc" }, include: { _count: { select: { memberships: true } } } }),
    db.inviteLink.findMany({ orderBy: { id: "asc" }, include: { chat: true, _count: { select: { memberships: true } } } }),
  ]);

  const hasApi = Boolean(process.env.TG_API_ID && process.env.TG_API_HASH);
  const hasSession = Boolean(process.env.TG_SESSION);
  const chatsConfigured = Boolean(process.env.TG_CHATS);

  return (
    <>
      <PageHeader title="Настройки" subtitle="Подключение Telegram, источники трафика и атрибуция ссылок" />

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Подключение Telegram" hint="личный аккаунт через MTProto — видит историю чата, вступления и выходы">
          <div className="flex flex-col gap-2">
            <Status ok={hasApi}>
              api_id / api_hash {hasApi ? "заданы" : "не заданы — возьмите на my.telegram.org и впишите в .env"}
            </Status>
            <Status ok={hasSession}>
              Сессия аккаунта {hasSession ? "сохранена" : "не создана — выполните npm run tg:login"}
            </Status>
            <Status ok={chatsConfigured}>
              Чаты в TG_CHATS {chatsConfigured ? process.env.TG_CHATS : "не указаны"}
            </Status>
          </div>
          <ol className="mt-4 flex list-decimal flex-col gap-1.5 pl-5 text-[13px]" style={{ color: "var(--text-secondary)" }}>
            <li>Заполните TG_API_ID, TG_API_HASH и TG_CHATS в .env</li>
            <li><code>npm run tg:login</code> — вход по номеру телефона, строка сессии сохранится в .env</li>
            <li><code>npm run tg:backfill</code> — выгрузка истории: участники, сообщения, вступления и выходы</li>
            <li><code>npm run tg:sync</code> — регулярная догрузка (крон раз в 10–15 минут)</li>
          </ol>
          <p className="mt-3 text-[12px]" style={{ color: "var(--text-muted)" }}>
            Точная привязка вступлений к ссылкам доступна, когда аккаунт — администратор группы: тогда читается
            журнал администратора. Без прав администратора вступления берутся из служебных сообщений чата, а
            источник остаётся «Без метки».
          </p>
        </Card>

        <Card title="Отслеживаемые чаты">
          {chats.length === 0 ? (
            <Empty>Чатов нет. Укажите их в TG_CHATS и запустите выгрузку.</Empty>
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th>Чат</th>
                  <th className="n">Людей</th>
                  <th className="n">Сообщений</th>
                  <th className="n">Синхронизация</th>
                </tr>
              </thead>
              <tbody>
                {chats.map((c) => (
                  <tr key={c.id}>
                    <td>
                      {c.title}
                      <span className="ml-2 text-[12px]" style={{ color: "var(--text-muted)" }}>
                        {String(c.tgChatId)}
                      </span>
                    </td>
                    <td className="n">{num(c._count.memberships)}</td>
                    <td className="n">{num(c._count.messages)}</td>
                    <td className="n" style={{ color: "var(--text-secondary)" }}>{dateTime(c.lastSyncedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="mt-3 text-[12px]" style={{ color: "var(--text-muted)" }}>
            Таймзона отчётов: {REPORT_TZ}. Порог отвала: {INACTIVE_DAYS} дней без сообщений.
          </p>
        </Card>
      </div>

      <Card title="Источники трафика" className="mt-3" hint="расход задаётся суммарно по источнику и используется для цены входа">
        <SourceForm />
        <div className="mt-4 overflow-x-auto">
          <table className="data">
            <thead>
              <tr>
                <th>Название</th>
                <th>Slug</th>
                <th>Тип</th>
                <th className="n">Людей</th>
                <th className="n">Расход</th>
              </tr>
            </thead>
            <tbody>
              {sources.length === 0 ? (
                <tr>
                  <td colSpan={5}>
                    <Empty>Источников пока нет.</Empty>
                  </td>
                </tr>
              ) : (
                sources.map((s) => (
                  <tr key={s.id}>
                    <td>{s.title}</td>
                    <td style={{ color: "var(--text-secondary)" }}>{s.slug}</td>
                    <td style={{ color: "var(--text-secondary)" }}>{s.kind}</td>
                    <td className="n">{num(s._count.memberships)}</td>
                    <td className="n">{money(s.spend ? Number(s.spend) : null, s.currency)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Пригласительные ссылки" className="mt-3" hint="одна ссылка на источник — так вступления привязываются к трафику">
        {links.length === 0 ? (
          <Empty>Ссылок нет. Коллектор подтянет их из Telegram при выгрузке.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="data">
              <thead>
                <tr>
                  <th>Ссылка</th>
                  <th>Чат</th>
                  <th className="n">Пришло</th>
                  <th className="n">Счётчик TG</th>
                  <th>Источник</th>
                </tr>
              </thead>
              <tbody>
                {links.map((l) => (
                  <tr key={l.id}>
                    <td className="max-w-[320px] truncate">
                      {l.title ? <span className="mr-2">{l.title}</span> : null}
                      <span style={{ color: "var(--text-muted)" }}>{l.link}</span>
                    </td>
                    <td style={{ color: "var(--text-secondary)" }}>{l.chat.title}</td>
                    <td className="n">{num(l._count.memberships)}</td>
                    <td className="n">{num(l.tgUsage)}</td>
                    <td>
                      <LinkSourceSelect linkId={l.id} sourceId={l.sourceId} sources={sources.map((s) => ({ id: s.id, title: s.title }))} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

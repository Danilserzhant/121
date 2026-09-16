import Link from "next/link";

export function NoChats() {
  return (
    <div className="card p-8 text-center">
      <h2 className="text-[15px] font-medium">Чаты ещё не подключены</h2>
      <p className="mx-auto mt-2 max-w-md text-[13px]" style={{ color: "var(--text-secondary)" }}>
        Подключите Telegram-аккаунт и укажите группы потока — коллектор выгрузит историю, вступления и выходы,
        после чего здесь появятся метрики.
      </p>
      <Link
        href="/settings"
        className="mt-4 inline-block rounded-lg px-4 py-2 text-[13px]"
        style={{ background: "var(--text-primary)", color: "var(--surface)" }}
      >
        Перейти к подключению
      </Link>
    </div>
  );
}

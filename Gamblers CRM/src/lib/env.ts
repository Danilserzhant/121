/** Таймзона отчётов: в ней считаются «дни», часы активности и границы когорт. */
export const REPORT_TZ = process.env.REPORT_TZ || "Europe/Kyiv";

/** Сколько дней молчания считаем отвалом от чата. */
export const INACTIVE_DAYS = Number(process.env.INACTIVE_DAYS || 14);

/** Порог «ядра» — сообщений за окно INACTIVE_DAYS. */
export const CORE_MESSAGES = Number(process.env.CORE_MESSAGES || 10);

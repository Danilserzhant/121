/**
 * Ввод из терминала и запись в .env — общее для мастера настройки и логина.
 * Свой обработчик вместо readline/promises: тот молча зависает на втором вопросе,
 * когда stdin не терминал (контейнер, pipe).
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { createInterface } from "node:readline";

const ENV_PATH = ".env";

const rl = createInterface({ input: process.stdin });
const pending: string[] = [];
const waiting: ((line: string) => void)[] = [];
rl.on("line", (line) => {
  const next = waiting.shift();
  if (next) next(line);
  else pending.push(line);
});

export const ask = (q: string) =>
  new Promise<string>((resolve) => {
    process.stdout.write(q);
    const buffered = pending.shift();
    if (buffered !== undefined) resolve(buffered);
    else waiting.push(resolve);
  });

export const closePrompt = () => rl.close();

/** Обновляет ключ в .env, сохраняя остальные строки, и применяет его к текущему процессу. */
export function setEnv(key: string, value: string) {
  const current = existsSync(ENV_PATH) ? readFileSync(ENV_PATH, "utf8") : "";
  const line = `${key}="${value}"`;
  const re = new RegExp(`^${key}=.*$`, "m");
  const next = re.test(current) ? current.replace(re, line) : `${current.replace(/\s*$/, "")}\n${line}\n`;
  writeFileSync(ENV_PATH, next.startsWith("\n") ? next.slice(1) : next);
  process.env[key] = value;
}

/** Спрашивает api_id и api_hash, если их ещё нет. */
export async function ensureApiCredentials() {
  if (process.env.TG_API_ID && process.env.TG_API_HASH) return;
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

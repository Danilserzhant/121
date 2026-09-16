"use client";

import { useActionState } from "react";
import { createSource } from "./actions";

const KINDS = [
  { value: "blogger", label: "Блогер" },
  { value: "ads", label: "Реклама" },
  { value: "seeding", label: "Посев" },
  { value: "partner", label: "Партнёр" },
  { value: "organic", label: "Органика" },
  { value: "other", label: "Другое" },
];

const field = {
  background: "var(--page)",
  border: "1px solid var(--border)",
  color: "var(--text-primary)",
};

export function SourceForm() {
  const [state, action, pending] = useActionState(createSource, null);

  return (
    <form action={action} className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col gap-1 text-[12px]" style={{ color: "var(--text-muted)" }}>
        Slug
        <input name="slug" required placeholder="blogger-alex" className="rounded-lg px-3 py-1.5 text-[13px] outline-none" style={field} />
      </label>
      <label className="flex flex-col gap-1 text-[12px]" style={{ color: "var(--text-muted)" }}>
        Название
        <input name="title" required placeholder="Блогер Alex" className="rounded-lg px-3 py-1.5 text-[13px] outline-none" style={field} />
      </label>
      <label className="flex flex-col gap-1 text-[12px]" style={{ color: "var(--text-muted)" }}>
        Тип
        <select name="kind" className="rounded-lg px-3 py-1.5 text-[13px] outline-none" style={field}>
          {KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-[12px]" style={{ color: "var(--text-muted)" }}>
        Расход
        <input name="spend" inputMode="decimal" placeholder="1200" className="w-24 rounded-lg px-3 py-1.5 text-[13px] outline-none" style={field} />
      </label>
      <label className="flex flex-col gap-1 text-[12px]" style={{ color: "var(--text-muted)" }}>
        Валюта
        <input name="currency" defaultValue="USD" maxLength={3} className="w-20 rounded-lg px-3 py-1.5 text-[13px] outline-none" style={field} />
      </label>
      <button
        type="submit"
        disabled={pending}
        className="rounded-lg px-4 py-2 text-[13px]"
        style={{ background: "var(--text-primary)", color: "var(--surface)", opacity: pending ? 0.6 : 1 }}
      >
        {pending ? "Сохраняем…" : "Добавить источник"}
      </button>
      {state?.error ? (
        <span className="text-[12px]" style={{ color: "var(--critical)" }}>
          {state.error}
        </span>
      ) : null}
    </form>
  );
}

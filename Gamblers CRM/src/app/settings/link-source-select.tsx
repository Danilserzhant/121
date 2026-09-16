"use client";

import { useRef } from "react";
import { assignLinkSource } from "./actions";

export function LinkSourceSelect({
  linkId,
  sourceId,
  sources,
}: {
  linkId: number;
  sourceId: number | null;
  sources: { id: number; title: string }[];
}) {
  const formRef = useRef<HTMLFormElement>(null);
  return (
    <form ref={formRef} action={assignLinkSource}>
      <input type="hidden" name="linkId" value={linkId} />
      <select
        name="sourceId"
        defaultValue={sourceId ? String(sourceId) : ""}
        onChange={() => formRef.current?.requestSubmit()}
        className="rounded-lg px-2 py-1 text-[13px] outline-none"
        style={{ background: "var(--page)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
      >
        <option value="">Без метки</option>
        {sources.map((s) => (
          <option key={s.id} value={String(s.id)}>
            {s.title}
          </option>
        ))}
      </select>
    </form>
  );
}

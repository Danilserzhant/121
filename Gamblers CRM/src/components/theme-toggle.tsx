"use client";

import { useEffect, useState } from "react";

export function ThemeToggle() {
  const [theme, setTheme] = useState<string | null>(null);

  useEffect(() => {
    setTheme(document.documentElement.getAttribute("data-theme"));
  }, []);

  const apply = (next: string | null) => {
    if (next) {
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("theme", next);
    } else {
      document.documentElement.removeAttribute("data-theme");
      localStorage.removeItem("theme");
    }
    setTheme(next);
  };

  return (
    <div className="flex items-center gap-1">
      {[
        { key: null, label: "Авто" },
        { key: "light", label: "Светлая" },
        { key: "dark", label: "Тёмная" },
      ].map((o) => (
        <button
          key={o.label}
          type="button"
          onClick={() => apply(o.key)}
          className="chip"
          data-active={theme === o.key}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

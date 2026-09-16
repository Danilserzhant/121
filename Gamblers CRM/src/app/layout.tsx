import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { ThemeToggle } from "@/components/theme-toggle";

export const metadata: Metadata = {
  title: "Gamblers CRM",
  description: "Аналитика трафика и удержания аудитории потока по трейдингу",
};

const NAV = [
  { href: "/", label: "Обзор" },
  { href: "/sources", label: "Источники" },
  { href: "/retention", label: "Удержание" },
  { href: "/engagement", label: "Активность" },
  { href: "/members", label: "Люди" },
  { href: "/settings", label: "Настройки" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem('theme');if(t)document.documentElement.setAttribute('data-theme',t)}catch(e){}`,
          }}
        />
      </head>
      <body>
        <div className="mx-auto flex min-h-screen max-w-[1400px] flex-col">
          <header className="flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-4 sm:px-6">
            <Link href="/" className="text-[15px] font-semibold tracking-tight">
              Gamblers<span style={{ color: "var(--text-muted)" }}> CRM</span>
            </Link>
            <nav className="flex flex-wrap items-center gap-1">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded-lg px-3 py-1.5 text-[13px] transition-colors hover:bg-[var(--hover)]"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            <div className="ml-auto">
              <ThemeToggle />
            </div>
          </header>
          <main className="flex-1 px-4 pb-16 sm:px-6">{children}</main>
        </div>
      </body>
    </html>
  );
}

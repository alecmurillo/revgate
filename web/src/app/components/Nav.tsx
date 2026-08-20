"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/", label: "Home" },
  { href: "/lint", label: "Lint" },
  { href: "/redteam", label: "Redteam" },
  { href: "/diff", label: "Diff" },
  { href: "/rules", label: "Rules" },
  { href: "/scenarios", label: "Scenarios" },
  { href: "/provenance", label: "Provenance" },
  { href: "/faq", label: "FAQ" },
  { href: "/why", label: "Why" },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <nav className="flex-shrink-0 border-b border-[var(--border)] bg-[var(--bg)]/82 backdrop-blur-md sticky top-0 z-40">
      <div className="max-w-[1180px] mx-auto px-4 flex items-center h-12 gap-1 overflow-x-auto">
        <Link href="/" className="flex items-center gap-2 font-bold text-[var(--head)] text-sm tracking-tight mr-3 flex-shrink-0">
          <span className="w-2 h-2 rounded-full bg-[var(--brand)] shadow-[0_0_8px_var(--brand)] animate-pulse-dot" />
          revgate
        </Link>
        {TABS.map((tab) => {
          const active = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={`px-2.5 py-1 rounded-sm text-xs uppercase tracking-wider font-bold transition-colors flex-shrink-0 ${
                active
                  ? "text-[var(--brand)] bg-[var(--brand-soft)]/40"
                  : "text-[var(--subtle)] hover:text-[var(--head)]"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
        <a
          href="https://github.com/alecmurillo/revgate"
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto text-xs uppercase tracking-wider text-[var(--body)] hover:text-[var(--head)] transition-colors flex-shrink-0"
        >
          GitHub ↗
        </a>
      </div>
    </nav>
  );
}

"use client";

import { useState, useEffect } from "react";
import Nav from "../components/Nav";

interface Rule { id: string; name: string; severity: string; summary: string; origin: string; }

const SEV_COLOR: Record<string, string> = { P0: "var(--p0)", P1: "var(--p1)", P2: "var(--p2)" };
const SEV_DOT: Record<string, string> = { P0: "bg-[var(--p0)]", P1: "bg-[var(--p1)]", P2: "bg-[var(--p2)]" };

export default function RulesPage() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/rules").then(r => r.json()).then(d => { setRules(d); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      <Nav />
      <main className="flex-1 max-w-[1180px] w-full mx-auto px-6 py-4 relative z-10">
        <div className="mb-4">
          <p className="text-xs font-medium tracking-[0.16em] uppercase text-[var(--subtle)] mb-1">
            <b className="text-[var(--brand)]">Rules</b> — 22 gates
          </p>
          <h1 className="text-xl font-bold text-[var(--head)]">Every gate and the mistake it prevents</h1>
        </div>
        {loading ? (
          <p className="text-sm text-[var(--subtle)]">Loading...</p>
        ) : (
          <div className="space-y-1">
            {rules.map((r) => (
              <div key={r.id} className="rounded-sm border bg-[var(--card)] px-3 py-2 flex items-start gap-3 hover:bg-[var(--card-2)] transition-colors">
                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1.5 ${SEV_DOT[r.severity] || "bg-zinc-500"}`} />
                <span className="text-xs font-mono font-bold flex-shrink-0 mt-0.5" style={{ color: SEV_COLOR[r.severity] || "var(--subtle)" }}>{r.id}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-[var(--head)]">{r.summary}</p>
                  <p className="text-xs text-[var(--body)] mt-0.5">{r.origin}</p>
                </div>
                <span className="text-xs font-bold px-1.5 py-0.5 rounded-sm flex-shrink-0" style={{ color: SEV_COLOR[r.severity] || "var(--subtle)", background: "var(--bg)" }}>{r.severity}</span>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

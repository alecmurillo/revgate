"use client";

import { useState, useMemo } from "react";
import Nav from "../components/Nav";
import { Badge } from "../components/Badge";
import rulesData from "../data/rules.json";

interface Rule { id: string; name: string; severity: string; summary: string; origin: string; }

const SEV: Record<string, { color: string; dot: string; label: string }> = {
  P0: { color: "var(--p0)", dot: "bg-[var(--p0)]", label: "P0 — Blocks the send" },
  P1: { color: "var(--p1)", dot: "bg-[var(--p1)]", label: "P1 — Advisory" },
  P2: { color: "var(--p2)", dot: "bg-[var(--p2)]", label: "P2 — Worth reviewing" },
};
const SEV_ORDER = ["P0", "P1", "P2"];

export default function RulesPage() {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set(["P0", "P1", "P2"]));

  const grouped = useMemo(() => {
    const map: Record<string, Rule[]> = { P0: [], P1: [], P2: [] };
    for (const r of rulesData as Rule[]) (map[r.severity] || []).push(r);
    return map;
  }, []);

  const toggle = (sev: string) => {
    setCollapsed((prev) => { const n = new Set(prev); n.has(sev) ? n.delete(sev) : n.add(sev); return n; });
  };

  return (
    <div className="min-h-screen flex flex-col">
      <Nav />
      <main className="flex-1 max-w-[1180px] w-full mx-auto px-6 py-4 relative z-10">
        <div className="mb-4">
          <div className="flex items-center gap-2 mb-1">
            <p className="text-xs font-medium tracking-[0.16em] uppercase text-[var(--subtle)]">
              <b className="text-[var(--brand)]">Rules</b> — 22 gates
            </p>
            <Badge type="reference" />
          </div>
          <h1 className="text-xl font-bold text-[var(--head)]">Every gate and the mistake it prevents</h1>
        </div>
        <div className="space-y-3">
          {SEV_ORDER.map((sev) => {
            const items = grouped[sev] || [];
            if (!items.length) return null;
            const config = SEV[sev];
            const isCollapsed = collapsed.has(sev);
            return (
              <div key={sev}>
                <button
                  onClick={() => toggle(sev)}
                  className="w-full flex items-center gap-2.5 px-3 py-2 rounded-sm border bg-[var(--card)] hover:bg-[var(--card-2)] transition-colors"
                  style={{ borderColor: `var(--${sev.toLowerCase()}-border)` }}
                >
                  <span className={`w-2 h-2 rounded-full ${config.dot}`} />
                  <span className="text-sm font-bold" style={{ color: config.color }}>{config.label}</span>
                  <span className="text-xs font-bold px-1.5 py-0.5 rounded-sm" style={{ color: config.color, background: "var(--bg)" }}>
                    {items.length}
                  </span>
                  <svg
                    className={`w-3.5 h-3.5 text-[var(--subtle)] ml-auto transition-transform ${isCollapsed ? "" : "rotate-180"}`}
                    fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                  </svg>
                </button>
                {!isCollapsed && (
                  <div className="space-y-1 mt-1 animate-fade-in">
                    {items.map((r) => (
                      <div key={r.id} className="rounded-sm border border-[var(--border)] bg-[var(--card)] px-3 py-2 flex items-start gap-3 hover:bg-[var(--card-2)] transition-colors">
                        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1.5 ${config.dot}`} />
                        <span className="text-xs font-mono font-bold flex-shrink-0 mt-0.5" style={{ color: config.color }}>{r.id}</span>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-bold text-[var(--head)]">{r.summary}</p>
                          <p className="text-xs text-[var(--body)] mt-0.5">{r.origin}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </main>
    </div>
  );
}

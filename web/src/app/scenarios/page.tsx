"use client";

import { useState } from "react";
import Nav from "../components/Nav";
import scenariosData from "../data/scenarios.json";

interface Scenario {
  id: string; title: string; priority: string; tags: string[];
  turns: string[]; assertions: { must_not_match: string[]; must_match_any: string[]; must_match_all: string[]; semantic: string };
}

const SEV_COLOR: Record<string, string> = { P0: "var(--p0)", P1: "var(--p1)", P2: "var(--p2)" };
const SEV_DOT: Record<string, string> = { P0: "bg-[var(--p0)]", P1: "bg-[var(--p1)]", P2: "bg-[var(--p2)]" };

export default function ScenariosPage() {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setExpanded((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  };

  return (
    <div className="min-h-screen flex flex-col">
      <Nav />
      <main className="flex-1 max-w-[1180px] w-full mx-auto px-6 py-4 relative z-10">
        <div className="mb-4">
          <p className="text-xs font-medium tracking-[0.16em] uppercase text-[var(--subtle)] mb-1">
            <b className="text-[var(--brand)]">Scenarios</b> — 27 adversarial tests
          </p>
          <h1 className="text-xl font-bold text-[var(--head)]">Every scenario and what it probes</h1>
        </div>
        <div className="space-y-1">
          {(scenariosData as Scenario[]).map((s) => {
            const isOpen = expanded.has(s.id);
            return (
              <div key={s.id} className="rounded-sm border bg-[var(--card)] overflow-hidden hover:bg-[var(--card-2)] transition-colors"
                style={{ borderColor: s.priority === "PASS" ? "var(--pass-border)" : "var(--border)" }}>
                <button onClick={() => toggle(s.id)} className="w-full flex items-center gap-2.5 px-3 py-2 text-left">
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${s.priority === "PASS" ? "bg-[var(--pass)]" : (SEV_DOT[s.priority] || "bg-zinc-500")}`} />
                  <span className="text-xs font-mono font-bold flex-shrink-0" style={{ color: s.priority === "PASS" ? "var(--pass)" : (SEV_COLOR[s.priority] || "var(--subtle)") }}>{s.id}</span>
                  <span className="text-sm text-[var(--head)] truncate flex-1">{s.title}</span>
                  {s.priority === "PASS" && <span className="text-xs px-1.5 py-0.5 rounded-sm bg-[var(--pass-bg)] text-[var(--pass)] font-bold">control</span>}
                  {s.tags?.length > 0 && <span className="text-xs text-[var(--subtle)] hidden md:inline">{s.tags.join(" · ")}</span>}
                  <svg className={`w-3.5 h-3.5 text-[var(--subtle)] flex-shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                  </svg>
                </button>
                {isOpen && (
                  <div className="border-t border-[var(--border)] bg-[var(--bg)] px-3 py-2 animate-fade-in">
                    <p className="text-xs text-[var(--subtle)] uppercase tracking-wider mb-1">Turns</p>
                    {s.turns?.map((t, i) => <p key={i} className="text-xs text-[var(--body)] py-0.5">→ {t}</p>)}
                    {s.assertions?.semantic && <p className="text-xs text-[var(--brand)] mt-2"><b>Semantic:</b> {s.assertions.semantic}</p>}
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

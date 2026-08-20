"use client";

import { useState, useMemo, useRef, useCallback } from "react";
import Nav from "../components/Nav";
import { Badge } from "../components/Badge";
import type { LintResult, Severity, Finding } from "../types";

const SEV: Record<Severity, { color: string; bg: string; border: string; dot: string }> = {
  P0: { color: "var(--p0)", bg: "var(--p0-bg)", border: "var(--p0-border)", dot: "bg-[var(--p0)]" },
  P1: { color: "var(--p1)", bg: "var(--p1-bg)", border: "var(--p1-border)", dot: "bg-[var(--p1)]" },
  P2: { color: "var(--p2)", bg: "var(--p2-bg)", border: "var(--p2-border)", dot: "bg-[var(--p2)]" },
};
const VERDICT: Record<string, { color: string; bg: string; border: string; icon: string }> = {
  PASS: { color: "var(--pass)", bg: "var(--pass-bg)", border: "var(--pass-border)", icon: "✓" },
  ADVISORY: { color: "var(--p1)", bg: "var(--p1-bg)", border: "var(--p1-border)", icon: "!" },
  BLOCKED: { color: "var(--p0)", bg: "var(--p0-bg)", border: "var(--p0-border)", icon: "✕" },
};
interface RuleGroup { rule: string; severity: Severity; title: string; remedy: string; origin: string; count: number; findings: Finding[]; }

export default function DiffPage() {
  const [oldFile, setOldFile] = useState<File | null>(null);
  const [newFile, setNewFile] = useState<File | null>(null);
  const [result, setResult] = useState<LintResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [today] = useState(() => new Date().toISOString().slice(0, 10));
  const [activeFilters, setActiveFilters] = useState<Set<Severity>>(new Set(["P0", "P1", "P2"]));
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const oldInputRef = useRef<HTMLInputElement>(null);
  const newInputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback((f: File, which: "old" | "new") => {
    if (!f.name.endsWith(".csv")) { setError("Please upload CSV files"); return; }
    setError(null);
    if (which === "old") setOldFile(f); else setNewFile(f);
    setResult(null);
  }, []);

  const runDiff = async () => {
    if (!oldFile || !newFile) return;
    setLoading(true); setError(null); setResult(null); setExpandedGroups(new Set());
    try {
      const oldCsv = await oldFile.text();
      const newCsv = await newFile.text();
      const res = await fetch("/api/diff", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ oldCsv, newCsv, today }),
      });
      const data = await res.json();
      if (!res.ok) setError(data.error || "Failed to run diff");
      else setResult(data as LintResult);
    } catch (err) { setError(err instanceof Error ? err.message : "Network error"); }
    finally { setLoading(false); }
  };

  const toggleFilter = (sev: Severity) => {
    setActiveFilters((prev) => { const n = new Set(prev); n.has(sev) ? n.delete(sev) : n.add(sev); return n; });
  };
  const toggleGroup = (rule: string) => {
    setExpandedGroups((prev) => { const n = new Set(prev); n.has(rule) ? n.delete(rule) : n.add(rule); return n; });
  };

  const grouped = useMemo<RuleGroup[]>(() => {
    if (!result) return [];
    const map = new Map<string, RuleGroup>();
    for (const f of result.findings) {
      if (!activeFilters.has(f.severity)) continue;
      const ex = map.get(f.rule);
      if (ex) { ex.count++; ex.findings.push(f); }
      else map.set(f.rule, { rule: f.rule, severity: f.severity, title: f.title, remedy: f.remedy, origin: f.origin, count: 1, findings: [f] });
    }
    return Array.from(map.values()).sort((a, b) => { const o: Severity[] = ["P0", "P1", "P2"]; return o.indexOf(a.severity) - o.indexOf(b.severity); });
  }, [result, activeFilters]);

  return (
    <div className="min-h-screen flex flex-col">
      <Nav />
      <main className="flex-1 max-w-[1180px] w-full mx-auto px-6 py-4 relative z-10">
        {!result && !loading && (
          <>
            <div className="mb-6">
              <div className="flex items-center gap-2 mb-1">
                <p className="text-xs font-medium tracking-[0.16em] uppercase text-[var(--subtle)]">
                  <b className="text-[var(--brand)]">Diff</b> — compare two lists
                </p>
                <Badge type="prod" />
              </div>
              <h1 className="text-xl font-bold text-[var(--head)]">Compare two exports and re-gate what changed</h1>
              <p className="text-xs text-[var(--subtle)] mt-1">Upload your own CSVs — gates run against your real data.</p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              {(["old", "new"] as const).map((which) => {
                const file = which === "old" ? oldFile : newFile;
                const ref = which === "old" ? oldInputRef : newInputRef;
                return (
                  <div key={which} onClick={() => ref.current?.click()}
                    className="border-2 border-dashed rounded-sm p-8 cursor-pointer transition-all border-[var(--border)] hover:border-[var(--border-medium)] hover:bg-[var(--card)] text-center">
                    <input ref={ref} type="file" accept=".csv" className="hidden"
                      onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f, which); }} />
                    <p className="text-xs uppercase tracking-wider text-[var(--subtle)] mb-2">{which === "old" ? "Old list" : "New list"}</p>
                    <p className="text-sm font-bold text-[var(--head)]">{file ? file.name : "Drop CSV or click"}</p>
                    {file && <p className="text-xs text-[var(--subtle)] mt-1">{(file.size / 1024).toFixed(1)} KB</p>}
                  </div>
                );
              })}
            </div>
            {oldFile && newFile && (
              <div className="mt-4 flex items-center justify-center gap-3 animate-fade-in">
                <button onClick={runDiff} disabled={loading}
                  className="px-6 py-2.5 rounded-sm font-bold text-sm uppercase tracking-wider bg-[var(--brand)] hover:bg-[var(--brand-strong)] text-[var(--bg)] transition-colors">
                  Compare & re-gate
                </button>
              </div>
            )}
            {error && <div className="mt-3 p-3 rounded-sm border border-[var(--p0-border)] bg-[var(--p0-bg)] text-sm text-red-400">{error}</div>}
            <div className="mt-6 flex items-center justify-center gap-5 text-xs text-[var(--subtle)]">
              <span>Try the fixtures:</span>
              <button onClick={() => { fetch("/leads-clean.csv").then(r => r.text()).then(t => setOldFile(new File([t], "leads-clean.csv", { type: "text/csv" }))).catch(() => {}); }}
                className="text-[var(--brand)] hover:text-[var(--brand-strong)] font-bold">old = clean</button>
              <button onClick={() => { fetch("/leads-dirty.csv").then(r => r.text()).then(t => setNewFile(new File([t], "leads-dirty.csv", { type: "text/csv" }))).catch(() => {}); }}
                className="text-red-400 hover:text-red-300 font-bold">new = dirty</button>
            </div>
          </>
        )}

        {loading && (
          <div className="flex flex-col items-center justify-center py-20 gap-4">
            <div className="relative w-12 h-12">
              <div className="absolute inset-0 rounded-full border-2 border-[var(--border)]" />
              <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-[var(--brand)] animate-spin" />
            </div>
            <p className="text-xs text-[var(--subtle)]">Comparing and re-gating...</p>
          </div>
        )}

        {result && !loading && (
          <div className="animate-fade-in">
            <div className="flex items-center gap-4 mb-3 flex-wrap">
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-sm border"
                style={{ background: VERDICT[result.verdict].bg, borderColor: VERDICT[result.verdict].border }}>
                <span className="text-lg font-bold" style={{ color: VERDICT[result.verdict].color }}>{VERDICT[result.verdict].icon}</span>
                <span className="text-sm font-bold" style={{ color: VERDICT[result.verdict].color }}>{result.verdict}</span>
              </div>
              <div className="flex items-center gap-3">
                {(["P0", "P1", "P2"] as Severity[]).map((sev) => {
                  const c = SEV[sev]; const count = result.counts[sev]; const active = activeFilters.has(sev);
                  return (
                    <button key={sev} onClick={() => toggleFilter(sev)}
                      className={`flex items-center gap-1.5 px-2 py-1 rounded-sm text-xs font-bold border transition-all ${active ? "" : "border-[var(--border)] opacity-40 hover:opacity-70"}`}
                      style={active ? { background: c.bg, borderColor: c.border, color: c.color } : undefined}>
                      <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />{sev} {count}
                    </button>
                  );
                })}
              </div>
              <div className="flex items-center gap-3 text-xs text-[var(--subtle)]">
                {result.stats.added != null && <span><b className="text-[var(--head)]">{result.stats.added}</b> added</span>}
                {result.stats.removed != null && <span><b className="text-[var(--head)]">{result.stats.removed}</b> removed</span>}
                {result.stats.changed != null && <span><b className="text-[var(--head)]">{result.stats.changed}</b> changed</span>}
                {result.stats["re-gated"] != null && <span><b className="text-[var(--head)]">{result.stats["re-gated"]}</b> re-gated</span>}
              </div>
              <button onClick={() => { setResult(null); setOldFile(null); setNewFile(null); }}
                className="ml-auto text-xs text-[var(--subtle)] hover:text-[var(--head)] transition-colors uppercase tracking-wider">← New</button>
            </div>
            {grouped.length > 0 && (
              <div className="space-y-1">
                {grouped.map((g) => {
                  const c = SEV[g.severity]; const expanded = expandedGroups.has(g.rule);
                  return (
                    <div key={g.rule} className="rounded-sm border bg-[var(--card)] overflow-hidden transition-colors hover:bg-[var(--card-2)]"
                      style={{ borderColor: c.border }}>
                      <button onClick={() => toggleGroup(g.rule)} className="w-full flex items-center gap-2.5 px-3 py-2 text-left">
                        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${c.dot}`} />
                        <span className="text-xs font-mono font-bold flex-shrink-0" style={{ color: c.color }}>{g.rule}</span>
                        <span className="text-sm text-[var(--head)] truncate flex-1">{g.title}</span>
                        <span className="text-xs font-bold px-1.5 py-0.5 rounded-sm flex-shrink-0" style={{ background: c.bg, color: c.color }}>{g.count}</span>
                        <svg className={`w-3.5 h-3.5 text-[var(--subtle)] flex-shrink-0 transition-transform ${expanded ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                        </svg>
                      </button>
                      {expanded && (
                        <div className="border-t border-[var(--border)] bg-[var(--bg)] animate-fade-in">
                          <div className="px-3 py-2 text-xs text-[var(--body)] border-b border-[var(--border-subtle)]">
                            <span className="text-[var(--brand)] font-bold">Fix:</span> {g.remedy}
                          </div>
                          <table className="w-full text-xs">
                            <tbody>
                              {g.findings.map((f, i) => (
                                <tr key={i} className="border-b border-[var(--border-subtle)] last:border-b-0">
                                  <td className="px-3 py-1.5 text-[var(--head)] font-bold w-12">{f.row || "—"}</td>
                                  <td className="px-3 py-1.5 text-[var(--body)]">{f.detail}</td>
                                  <td className="px-3 py-1.5 text-[var(--subtle)] font-mono whitespace-nowrap">{f.key || "—"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

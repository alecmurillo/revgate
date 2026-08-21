"use client";

import { useState, useCallback, useRef, useMemo } from "react";
import type { LintResult, Severity, Finding } from "../types";
import Nav from "../components/Nav";
import { Badge } from "../components/Badge";

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

interface RuleGroup {
  rule: string;
  severity: Severity;
  title: string;
  remedy: string;
  origin: string;
  count: number;
  findings: Finding[];
}

export default function LintPage() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<LintResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [today] = useState(() => new Date().toISOString().slice(0, 10));
  const inputRef = useRef<HTMLInputElement>(null);
  const [activeFilters, setActiveFilters] = useState<Set<Severity>>(new Set(["P0", "P1", "P2"]));
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  const MAX_CSV_SIZE = 4_000_000; // 4MB — Vercel Hobby body limit is 4.5MB

  const handleFile = useCallback((f: File) => {
    if (!f.name.endsWith(".csv")) { setError("Please upload a CSV file"); return; }
    if (f.size > MAX_CSV_SIZE) { setError(`File is ${(f.size / 1_000_000).toFixed(1)}MB. Vercel's free tier limit is 4.5MB — try a smaller file or use the CLI: revgate lint yourfile.csv`); return; }
    setError(null); setFile(f); setResult(null);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files[0]; if (f) handleFile(f);
  }, [handleFile]);

  const runLint = useCallback(async () => {
    if (!file) return;
    setLoading(true); setError(null); setResult(null); setExpandedGroups(new Set());
    try {
      const csvText = await file.text();
      const res = await fetch("/api/lint", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csv: csvText, today }),
      });
      if (!res.ok) {
        const text = await res.text();
        try { setError(JSON.parse(text).error || text.slice(0, 200)); }
        catch { setError(`Server error (${res.status}): ${text.slice(0, 200)}`); }
      } else {
        try { setResult(await res.json() as LintResult); }
        catch { setError("Failed to parse server response. Try again or use the CLI: revgate lint yourfile.csv"); }
      }
    } catch (err) { setError(err instanceof Error ? err.message : "Network error"); }
    finally { setLoading(false); }
  }, [file, today]);

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
    return Array.from(map.values()).sort((a, b) => {
      const o: Severity[] = ["P0", "P1", "P2"]; return o.indexOf(a.severity) - o.indexOf(b.severity);
    });
  }, [result, activeFilters]);

  const hasResults = result !== null;

  return (
    <div className="min-h-screen flex flex-col">
      <Nav />

      <main className="flex-1 max-w-[1180px] w-full mx-auto px-6 py-4 relative z-10">
        {/* Upload state */}
        {!hasResults && !loading && (
          <>
            <div className="mb-6">
              <div className="flex items-center gap-2 mb-1">
                <p className="text-xs font-medium tracking-[0.16em] uppercase text-[var(--subtle)]">
                  <b className="text-[var(--brand)]">Lint</b> — upload a CSV
                </p>
                <Badge type="prod" />
              </div>
              <h1 className="text-xl font-bold text-[var(--head)]">Run 22 gates against a lead list</h1>
              <p className="text-xs text-[var(--subtle)] mt-1">Upload your own CSV — the 22 gates run against your real data.</p>
            </div>
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={handleDrop}
              onClick={() => inputRef.current?.click()}
              className={`relative border-2 border-dashed rounded-sm p-12 cursor-pointer transition-all duration-200 ${
                dragging ? "border-[var(--brand)] bg-[var(--brand-soft)]" : "border-[var(--border)] hover:border-[var(--border-medium)] hover:bg-[var(--card)]"
              }`}
            >
              <input ref={inputRef} type="file" accept=".csv" className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
              />
              <div className="flex flex-col items-center gap-3 text-center">
                <div className="w-12 h-12 rounded-full bg-[var(--card)] flex items-center justify-center">
                  <svg className="w-5 h-5 text-[var(--subtle)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                  </svg>
                </div>
                <div>
                  <p className="text-base font-bold text-[var(--head)]">{file ? file.name : "Drop a CSV here or click to browse"}</p>
                  {!file && <p className="text-xs text-[var(--subtle)] mt-1">company, domain, email, phone, state, trigger, copy</p>}
                </div>
                {file && <p className="text-xs text-[var(--subtle)]">{(file.size / 1024).toFixed(1)} KB</p>}
              </div>
            </div>
            {file && (
              <div className="mt-4 flex items-center justify-center gap-3 animate-fade-in">
                <button onClick={runLint} disabled={loading}
                  className={`px-6 py-2.5 rounded-sm font-bold text-sm uppercase tracking-wider transition-all ${
                    loading ? "bg-[var(--card)] text-[var(--subtle)] cursor-not-allowed" : "bg-[var(--brand)] hover:bg-[var(--brand-strong)] text-[var(--bg)]"
                  }`}>
                  {loading ? "Running..." : "Run 22 gates"}
                </button>
                <button onClick={() => { setFile(null); setError(null); }}
                  className="px-3 py-2.5 rounded-sm text-xs text-[var(--subtle)] hover:text-[var(--head)] transition-colors">Clear</button>
              </div>
            )}
            {error && <div className="mt-3 p-3 rounded-sm border border-[var(--p0-border)] bg-[var(--p0-bg)] text-sm text-red-400 animate-fade-in">{error}</div>}
            {!file && (
              <div className="mt-6 flex flex-col items-center gap-3">
                <p className="text-xs text-[var(--subtle)] uppercase tracking-wider">Or click a sample to load it instantly:</p>
                <div className="flex items-center gap-3">
                  <button onClick={() => fetch("/leads-dirty.csv").then(r => r.text()).then(t => handleFile(new File([t], "leads-dirty.csv", { type: "text/csv" }))).catch(() => setError("Could not load sample"))}
                    className="flex items-center gap-2 px-4 py-2.5 rounded-sm border border-[var(--p0-border)] bg-[var(--p0-bg)] text-red-400 hover:bg-red-500/15 hover:border-red-500/50 font-bold text-sm transition-all cursor-pointer">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                    leads-dirty.csv
                    <span className="text-xs text-[var(--subtle)] font-normal">28 rows, 15 P0</span>
                  </button>
                  <button onClick={() => fetch("/leads-clean.csv").then(r => r.text()).then(t => handleFile(new File([t], "leads-clean.csv", { type: "text/csv" }))).catch(() => setError("Could not load sample"))}
                    className="flex items-center gap-2 px-4 py-2.5 rounded-sm border border-[var(--pass-border)] bg-[var(--pass-bg)] text-[var(--brand)] hover:bg-[var(--brand)]/15 hover:border-[var(--brand)]/50 font-bold text-sm transition-all cursor-pointer">
                    <span className="w-1.5 h-1.5 rounded-full bg-[var(--brand)]" />
                    leads-clean.csv
                    <span className="text-xs text-[var(--subtle)] font-normal">28 rows, 0 P0</span>
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-24 gap-4">
            <div className="relative w-12 h-12">
              <div className="absolute inset-0 rounded-full border-2 border-[var(--border)]" />
              <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-[var(--brand)] animate-spin" />
            </div>
            <p className="text-xs text-[var(--subtle)]">Running 22 gates against {file?.name}...</p>
          </div>
        )}

        {/* Results — compact, fits without scrolling */}
        {hasResults && result && !loading && (
          <div className="animate-fade-in">
            {/* Compact header: verdict + counts + stats + filter in one bar */}
            <div className="flex items-center gap-4 mb-3 flex-wrap">
              {/* Verdict pill */}
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-sm border"
                style={{ background: VERDICT[result.verdict].bg, borderColor: VERDICT[result.verdict].border }}>
                <span className="text-lg font-bold" style={{ color: VERDICT[result.verdict].color }}>
                  {VERDICT[result.verdict].icon}
                </span>
                <span className="text-sm font-bold" style={{ color: VERDICT[result.verdict].color }}>
                  {result.verdict}
                </span>
              </div>
              {/* Severity counts */}
              <div className="flex items-center gap-3">
                {(["P0", "P1", "P2"] as Severity[]).map((sev) => {
                  const c = SEV[sev]; const count = result.counts[sev]; const active = activeFilters.has(sev);
                  return (
                    <button key={sev} onClick={() => toggleFilter(sev)}
                      className={`flex items-center gap-1.5 px-2 py-1 rounded-sm text-xs font-bold border transition-all ${
                        active ? "" : "border-[var(--border)] opacity-40 hover:opacity-70"
                      }`}
                      style={active ? { background: c.bg, borderColor: c.border, color: c.color } : undefined}>
                      <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
                      {sev} {count}
                    </button>
                  );
                })}
              </div>
              {/* Stats inline */}
              <div className="flex items-center gap-3 text-xs text-[var(--subtle)]">
                <span><b className="text-[var(--head)]">{result.stats.rows}</b> rows</span>
                <span><b className="text-[var(--head)]">{result.stats["gates run"]}</b>/22 gates</span>
                {result.skipped.length > 0 && <span><b className="text-[var(--p1)]">{result.skipped.length}</b> skipped</span>}
              </div>
              <button onClick={() => { setResult(null); setFile(null); }}
                className="ml-auto text-xs text-[var(--subtle)] hover:text-[var(--head)] transition-colors uppercase tracking-wider">← New</button>
            </div>

            {/* Grouped findings — compact rows */}
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
                        <span className="text-xs font-bold px-1.5 py-0.5 rounded-sm flex-shrink-0" style={{ background: c.bg, color: c.color }}>
                          {g.count}
                        </span>
                        <svg className={`w-3.5 h-3.5 text-[var(--subtle)] flex-shrink-0 transition-transform ${expanded ? "rotate-180" : ""}`}
                          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
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

            {/* No findings match filter */}
            {grouped.length === 0 && result.findings.length > 0 && (
              <div className="text-center py-6 text-xs text-[var(--subtle)]">No findings match the active filters.</div>
            )}

            {/* Clean result */}
            {result.findings.length === 0 && result.skipped.length === 0 && (
              <div className="flex flex-col items-center gap-3 py-12">
                <div className="w-12 h-12 rounded-full bg-[var(--pass-bg)] border border-[var(--pass-border)] flex items-center justify-center">
                  <svg className="w-6 h-6 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                  </svg>
                </div>
                <p className="text-base font-bold text-[var(--head)]">All 22 gates passed</p>
                <button onClick={() => { setResult(null); setFile(null); }}
                  className="text-xs text-[var(--subtle)] hover:text-[var(--head)] transition-colors">← Check another file</button>
              </div>
            )}

            {/* Skipped gates */}
            {result.skipped.length > 0 && (
              <div className="mt-3 space-y-1">
                <p className="text-xs text-[var(--subtle)] uppercase tracking-wider mb-1">
                  Skipped ({result.skipped.length}) — a gate that could not run is never a gate that passed
                </p>
                {result.skipped.map((s, i) => (
                  <div key={i} className="rounded-sm border bg-[var(--card)] px-3 py-1.5 flex items-center gap-2.5"
                    style={{ borderColor: s.blocking ? "var(--p0-border)" : "var(--border)" }}>
                    <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${s.blocking ? "bg-red-500" : "bg-zinc-500"}`} />
                    <span className="text-xs font-mono font-bold" style={{ color: s.blocking ? "var(--p0)" : "var(--subtle)" }}>{s.rule}</span>
                    {s.blocking && <span className="text-xs px-1 py-0.5 rounded-sm bg-[var(--p0-bg)] text-red-400 font-bold">blocking</span>}
                    <span className="text-xs text-[var(--body)] truncate">{s.reason}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </main>

      <footer className="border-t border-[var(--border-subtle)] py-3 relative z-10">
        <div className="max-w-[1180px] mx-auto px-6 text-center">
          <p className="text-xs text-[var(--subtle)] uppercase tracking-wider">revgate · 22 gates · exit 0 clean · exit 2 blocked</p>
        </div>
      </footer>
    </div>
  );
}

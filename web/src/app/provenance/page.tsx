"use client";

import Nav from "../components/Nav";
import provenanceData from "../data/provenance.json";

interface ProvenanceResult {
  verdict: string; exit_code: number;
  stats: { claims: number; verified: number; surfaces: number };
  notes: string[];
  findings: { rule: string; severity: string; title: string; detail: string }[];
}

const result = provenanceData as ProvenanceResult;

export default function ProvenancePage() {
  return (
    <div className="min-h-screen flex flex-col">
      <Nav />
      <main className="flex-1 max-w-[1180px] w-full mx-auto px-6 py-4 relative z-10">
        <div className="mb-4">
          <p className="text-xs font-medium tracking-[0.16em] uppercase text-[var(--subtle)] mb-1">
            <b className="text-[var(--brand)]">Provenance</b> — machine-verified claims
          </p>
          <h1 className="text-xl font-bold text-[var(--head)]">Every Factory surface, verified</h1>
        </div>
        <div className="animate-fade-in space-y-4">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-sm border"
              style={{ background: "var(--pass-bg)", borderColor: "var(--pass-border)" }}>
              <span className="text-lg font-bold text-[var(--pass)]">✓</span>
              <span className="text-sm font-bold text-[var(--pass)]">{result.verdict}</span>
            </div>
            <div className="flex items-center gap-3 text-xs text-[var(--subtle)]">
              <span><b className="text-[var(--head)]">{result.stats.claims}</b> claims</span>
              <span><b className="text-[var(--head)]">{result.stats.verified}</b> verified</span>
              <span><b className="text-[var(--head)]">{result.stats.surfaces}</b> surfaces</span>
            </div>
          </div>
          {result.notes?.length > 0 && (
            <div className="space-y-1">
              {result.notes.map((n, i) => (
                <div key={i} className="rounded-sm border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-xs text-[var(--body)] leading-relaxed">
                  {n}
                </div>
              ))}
            </div>
          )}
          {result.findings?.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs text-[var(--subtle)] uppercase tracking-wider">Unverified claims</p>
              {result.findings.map((f, i) => (
                <div key={i} className="rounded-sm border border-[var(--p0-border)] bg-[var(--card)] px-3 py-2 text-xs">
                  <span className="font-mono font-bold text-[var(--p0)]">{f.rule}</span>
                  <span className="text-[var(--head)] ml-2">{f.title}</span>
                  <p className="text-[var(--body)] mt-0.5">{f.detail}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

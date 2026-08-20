import Link from "next/link";
import Nav from "./components/Nav";
import { Badge } from "./components/Badge";

export default function Home() {
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <Nav />
      <main className="flex-1 max-w-[1180px] w-full mx-auto px-6 py-3 relative z-10 flex flex-col overflow-hidden">
        {/* Hero — compact */}
        <div className="flex-shrink-0">
          <p className="text-xs font-medium tracking-[0.16em] uppercase text-[var(--subtle)] mb-2">
            <b className="text-[var(--brand)]">01</b> — A GTM engineering tool
          </p>
          <h1 className="text-2xl md:text-3xl leading-tight tracking-tight max-w-[24ch]">
            Dedupe and gate every lead list before it ships
          </h1>
          <p className="text-sm text-[var(--body)] max-w-[58ch] leading-relaxed mt-2">
            A QA layer for go-to-market engineering. Catches duplicate accounts,
            suppression collisions, DNC hits, restricted jurisdictions, and stale
            enrichment before a single email goes out. One P0 blocks the send.
          </p>
          <div className="flex flex-wrap gap-3 items-center mt-3">
            <Link href="/lint"
              className="inline-flex items-center gap-2 font-bold text-sm uppercase tracking-wider text-[var(--bg)] bg-[var(--brand)] hover:bg-[var(--brand-strong)] px-5 py-2 rounded-sm transition-colors">
              Try the linter →
            </Link>
            <a href="https://github.com/alecmurillo/revgate" target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-2 font-bold text-xs uppercase tracking-wider text-[var(--body)] border border-[var(--border)] px-3 py-2 rounded-sm hover:text-[var(--head)] hover:border-[var(--border-medium)] transition-colors">
              View source
            </a>
            <div className="flex gap-4 ml-1 text-xs text-[var(--subtle)]">
              <span><b className="text-[var(--head)]">22</b> gates</span>
              <span><b className="text-[var(--head)]">27</b> scenarios</span>
              <span><b className="text-[var(--head)]">0</b> deps</span>
              <span><b className="text-[var(--head)]">30+</b> droid sessions</span>
            </div>
          </div>
        </div>

        {/* Two-column: features + droids */}
        <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-3 mt-4 min-h-0">
          {/* Features */}
          <div className="flex flex-col min-h-0">
            <p className="text-xs font-medium tracking-[0.16em] uppercase text-[var(--subtle)] mb-1.5 flex-shrink-0">
              <b className="text-[var(--brand)]">02</b> — What it does
            </p>
            <div className="grid grid-cols-2 gap-px bg-[var(--border)] border border-[var(--border)] rounded-sm flex-1 overflow-y-auto min-h-0">
              <MiniFeature title="Dedupe" desc="Duplicate accounts by domain, duplicate phones, suppression collisions, DNC hits." link="/lint" badge="prod" />
              <MiniFeature title="Gate" desc="Restricted states, merge fields, stale data, headcount ceilings, wrong seniority." badge="prod" />
              <MiniFeature title="Red-team" desc="Runs against a fake demo agent. Self-test of the battery, not a real agent." badge="demo" />
              <MiniFeature title="HTTP API" desc="Clay, HubSpot, Apollo adapters. CLI only — not in the web UI." badge="prod" />
              <MiniFeature title="Diff" desc="Compare two exports, re-gate only the rows that changed." link="/diff" badge="prod" />
              <MiniFeature title="Provenance" desc="12 Factory claims, 12 machine-verified at build time." badge="verified" />
            </div>
          </div>

          {/* Droids */}
          <div className="flex flex-col min-h-0">
            <p className="text-xs font-medium tracking-[0.16em] uppercase text-[var(--subtle)] mb-1.5 flex-shrink-0">
              <b className="text-[var(--brand)]">03</b> — What the droids do
            </p>
            <div className="border border-[var(--border)] rounded-sm bg-[var(--card)] flex-1 flex flex-col min-h-0">
              <p className="text-xs text-[var(--body)] leading-relaxed p-2.5 border-b border-[var(--border)] flex-shrink-0">
                The 22 gates run with just Python — no account, no network. When you
                want deeper analysis, <code className="text-[var(--brand)] font-mono">--judge droid</code> spins
                up parallel AI sessions that review each finding group, find root causes
                across rules, and cross-check each other's work.
              </p>
              <div className="flex-1 overflow-y-auto min-h-0">
                <DroidPhase phase="0" title="Planning" desc="Group findings by rule. No agent." />
                <DroidPhase phase="1" title="Pattern gates" desc="22 deterministic gates. The baseline." />
                <DroidPhase phase="2" title="Parallel review" desc="One droid per rule group, in parallel." />
                <DroidPhase phase="2.5" title="Root cause analysis" desc="One droid sees ALL findings. Finds systemic patterns no gate can." highlight />
                <DroidPhase phase="3" title="Cross-validation" desc="One droid checks the others' work." />
                <DroidPhase phase="4" title="Final report" desc="Milestones, session IDs, provenance." last />
              </div>
            </div>
          </div>
        </div>

        {/* Invariant */}
        <div className="flex-shrink-0 mt-3 pt-2 border-t border-[var(--border)]">
          <p className="text-sm text-[var(--head)]">
            <span className="text-[var(--brand)] font-bold">The invariant:</span>{" "}
            a check that could not run is never a check that passed.
          </p>
        </div>
      </main>
    </div>
  );
}

function MiniFeature({ title, desc, link, badge }: { title: string; desc: string; link?: string; badge?: "prod" | "demo" | "reference" | "verified" }) {
  return (
    <div className="bg-[var(--card)] p-2.5 hover:bg-[var(--card-2)] transition-colors flex flex-col">
      <div className="flex items-center gap-1.5 mb-0.5">
        <h3 className="text-sm font-bold text-[var(--head)]">{title}</h3>
        {badge && <Badge type={badge} />}
      </div>
      <p className="text-xs text-[var(--body)] leading-relaxed flex-1">{desc}</p>
      {link && (
        <Link href={link} className="text-xs text-[var(--brand)] hover:text-[var(--brand-strong)] font-bold mt-1">
          Upload a CSV →
        </Link>
      )}
    </div>
  );
}

function DroidPhase({ phase, title, desc, highlight, last }: { phase: string; title: string; desc: string; highlight?: boolean; last?: boolean }) {
  return (
    <div className={`flex gap-3 px-3 py-2 ${highlight ? "bg-[var(--brand-soft)]/40" : ""} ${!last ? "border-b border-[var(--border)]" : ""}`}>
      <span className={`text-xs font-bold tracking-wider pt-0.5 flex-shrink-0 ${highlight ? "text-[var(--brand-strong)]" : "text-[var(--brand)]"}`}>
        {phase}
      </span>
      <div className="flex-1 min-w-0">
        <h3 className="text-xs font-bold text-[var(--head)]">
          {title}
          {highlight && <span className="ml-1.5 text-[var(--brand)] font-normal">— irreplaceable</span>}
        </h3>
        <p className="text-xs text-[var(--body)] leading-relaxed mt-0.5">{desc}</p>
      </div>
    </div>
  );
}

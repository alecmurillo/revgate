"use client";

import { useState } from "react";
import Nav from "../components/Nav";

interface FAQItem {
  q: string;
  a: string;
}

const FAQS: FAQItem[] = [
  {
    q: "What are the 22 gates?",
    a: "Each gate checks one rule against one column. They catch duplicate accounts by domain, duplicate phone numbers, suppression collisions, DNC hits, restricted jurisdictions, unrendered merge fields, stale enrichment, headcount ceilings, missing recipients, wrong seniority, copy length, multiple CTAs, and more. Gates are sorted by severity: P0 (blocks the send), P1 (advisory), P2 (worth reviewing).",
  },
  {
    q: "What are triggers?",
    a: "A trigger is the event that justifies the outreach. \"Series A announced\" is a trigger. \"Growing fast\" is not — it asserts nothing a recipient can verify. L005 checks that every row has a real trigger, that it's not a placeholder, and that the same trigger doesn't repeat across 90%+ of the list (which means the segmentation is too broad).",
  },
  {
    q: "What are the 27 scenarios?",
    a: "Adversarial scenarios that probe a customer-facing AI agent for commercial failure modes: identity disclosure (handing account details to anyone who asks), unauthorized commitments (inventing discounts, ROI guarantees), competitor claims (fabricating legal exposure), compliance claims (confirming certifications without a source), refund terms (inventing specific terms under pressure), opt-out violations (one more pitch after \"take me off your list\"), and prompt injection. 21 should fail, 6 are pass controls.",
  },
  {
    q: "What do the droids do?",
    a: "The 22 gates run with just Python — no account, no network. When you want deeper analysis, --judge droid spins up parallel AI sessions that review each finding group, find root causes across rules, and cross-check each other's work. Six phases: planning, pattern gates, parallel review (one droid per rule group), root cause analysis (one droid sees everything — irreplaceable), cross-validation (one droid checks the others), final report.",
  },
  {
    q: "What is fail-closed?",
    a: "A check that could not run is never a check that passed. If the suppression export is missing, the DNC list is empty, or the judge is unavailable, the gate records a blocking skip and the run is BLOCKED. The gate was supposed to hold and did not, which is worse than never having had it, because the run looks checked.",
  },
  {
    q: "What is the exit code contract?",
    a: "0 = clean. 1 = advisory (only with --strict). 2 = blocked. 3 = usage error. The exit code goes straight into CI or a pre-send gate. Code 2 comes from severity, never from volume — one P0 blocks, four hundred P2s do not.",
  },
  {
    q: "What is provenance?",
    a: "Every Factory surface the README claims is machine-verified. 12 claims, 12 verified. The claims are checked, not asserted. \"Verified present\" means the file exists and carries the expected fields — not that the surface has been exercised in a live run.",
  },
  {
    q: "What is the HTTP API?",
    a: "POST /v1/lint accepts Clay, HubSpot, Apollo, or generic JSON. Returns writeback fields (revgate_status, revgate_severity, revgate_rules, revgate_summary) that map straight back into your tool's columns. Fail-closed at the wire: a malformed payload returns BLOCKED, never PASS.",
  },
  {
    q: "What is diff?",
    a: "Compare an old export against a new one. Match rows by domain, email, or company. Report accounts added, removed, and changed. Re-gate only the rows that moved. Same exit code contract.",
  },
  {
    q: "Does this need a Factory account?",
    a: "No. Everything except --judge droid and audit --judge droid works with just Python 3.11+. No credentials, no API keys, no network. The droid-powered features need a Factory account and the Droid CLI installed.",
  },
];

export default function FAQPage() {
  const [open, setOpen] = useState<number | null>(0);

  const toggle = (i: number) => setOpen((prev) => (prev === i ? null : i));

  return (
    <div className="min-h-screen flex flex-col">
      <Nav />

      <main className="flex-1 max-w-[820px] w-full mx-auto px-6 py-10">
        <p className="text-xs font-medium tracking-[0.16em] uppercase text-[var(--subtle)] mb-3">
          <b className="text-[var(--brand)]">FAQ</b> — Questions about revgate
        </p>
        <h1 className="text-[clamp(28px,4vw,40px)] leading-[1.1] tracking-tight">
          How revgate works, in plain terms
        </h1>
        <p className="text-base text-[var(--body)] max-w-[64ch] leading-relaxed mt-4">
          The contract, the gates, the droids, and the exit codes. If a question
          isn't here, the README and the source cover the rest.
        </p>

        <div className="mt-8 border border-[var(--border)] rounded-sm bg-[var(--card)] overflow-hidden">
          {FAQS.map((item, i) => {
            const isOpen = open === i;
            return (
              <div
                key={i}
                className={i < FAQS.length - 1 ? "border-b border-[var(--border)]" : ""}
              >
                <button
                  type="button"
                  onClick={() => toggle(i)}
                  aria-expanded={isOpen}
                  className="w-full flex items-start gap-4 px-4 py-4 text-left hover:bg-[var(--card-2)] transition-colors group"
                >
                  <span className="text-xs font-bold tracking-wider text-[var(--brand)] pt-1 flex-shrink-0 tabular-nums">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="flex-1 text-sm font-bold text-[var(--head)] leading-snug">
                    {item.q}
                  </span>
                  <span
                    className={`text-[var(--subtle)] pt-1 flex-shrink-0 transition-transform duration-200 ${
                      isOpen ? "rotate-45" : ""
                    }`}
                    aria-hidden="true"
                  >
                    +
                  </span>
                </button>
                {isOpen && (
                  <div className="px-4 pb-4 pl-14 animate-fade-in">
                    <p className="text-sm text-[var(--body)] leading-relaxed">
                      {item.a}
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div className="mt-6 pt-4 border-t border-[var(--border)]">
          <p className="text-sm text-[var(--head)]">
            <span className="text-[var(--brand)] font-bold">The invariant:</span>{" "}
            a check that could not run is never a check that passed.
          </p>
        </div>
      </main>
    </div>
  );
}

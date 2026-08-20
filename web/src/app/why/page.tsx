import Nav from "../components/Nav";

interface PainPoint {
  num: string;
  title: string;
  desc: string;
}

const PAINS: PainPoint[] = [
  {
    num: "01",
    title: "Two reps on one account",
    desc: "Duplicate accounts slip through because the CRM dedupes by email, not by domain. Two rows with different emails but the same domain become two reps calling the same company. The prospect gets two emails from the same company with different messaging.",
  },
  {
    num: "02",
    title: "The DNC number that shouldn't have been dialed",
    desc: "Enrichment tools append phone numbers. Some of those numbers are on the do-not-call list. The sending platform doesn't check. The dialer dials it. That's a $50K violation per call. Nobody caught it because the DNC check was nobody's job.",
  },
  {
    num: "03",
    title: "The merge field that shipped literally",
    desc: "{{first_name}} survived the render and went out in the email. The prospect sees \"Hi {{first_name}}\" — which tells them this is a mass send, not a personal note. The render pipeline didn't validate, the sender didn't check, and the operator didn't notice until the reply rate cratered.",
  },
  {
    num: "04",
    title: "The jurisdiction you forgot to check",
    desc: "Some jurisdictions have state-level calling restrictions that go beyond federal DNC. Whether they apply to your motion depends on what you're selling, who you're calling, and how — B2B calls are often exempt from consumer telemarketing rules. Your CRM doesn't know about any of this. Your enrichment tool doesn't either. The call gets made, the complaint gets filed, and nobody knew the rule existed. revgate doesn't decide which states are restricted for you — you configure that with counsel, and the gate enforces your decision.",
  },
  {
    num: "05",
    title: "The AI agent that made things up",
    desc: "A customer-facing AI agent, under pressure, confirmed a certification the company doesn't hold, invented a discount the rep can't honor, and promised a refund terms that don't exist. The agent wasn't tested before it shipped because nobody built the adversarial scenarios to test it with.",
  },
  {
    num: "06",
    title: "The stale enrichment that became a compliance problem",
    desc: "The phone number was verified 9 months ago. It's been reassigned. The new owner is on the DNC list. The enrichment tool still says \"verified.\" The dialer calls it. The compliance team finds out when the complaint arrives.",
  },
];

export default function WhyPage() {
  return (
    <div className="min-h-screen flex flex-col">
      <Nav />

      <main className="flex-1 max-w-[820px] w-full mx-auto px-6 py-10">
        <p className="text-xs font-medium tracking-[0.16em] uppercase text-[var(--subtle)] mb-3">
          <b className="text-[var(--brand)]">Why</b>
        </p>
        <h1 className="text-[clamp(28px,4vw,42px)] leading-[1.1] tracking-tight max-w-[22ch]">
          The QA layer missing from every GTM stack
        </h1>
        <p className="text-base text-[var(--body)] max-w-[64ch] leading-relaxed mt-5">
          Every go-to-market tool generates data. None of them gate it. The CRM
          exports a list. The enrichment tool adds phone numbers. The sequencing
          platform sends the emails. Nobody checks the list before it ships.
        </p>

        <div className="mt-10 flex flex-col">
          {PAINS.map((p, i) => (
            <div
              key={p.num}
              className={
                "flex gap-5 py-6 " +
                (i < PAINS.length - 1
                  ? "border-b border-[var(--border)]"
                  : "")
              }
            >
              <span className="text-2xl font-bold text-[var(--brand)] tracking-tight flex-shrink-0 tabular-nums leading-tight">
                {p.num}
              </span>
              <div className="flex-1 min-w-0">
                <h2 className="text-lg font-bold text-[var(--head)] tracking-tight leading-snug">
                  {p.title}
                </h2>
                <p className="text-sm text-[var(--body)] leading-relaxed mt-2 max-w-[62ch]">
                  {p.desc}
                </p>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-10 pt-6 border-t border-[var(--border)]">
          <p className="text-base text-[var(--body)] leading-relaxed max-w-[64ch]">
            revgate is the gate between data generation and outbound execution.
            It doesn't source data, it doesn't send emails, and it doesn't make
            calls. It stops bad sends from happening. One P0 finding blocks the
            run. The exit code goes straight into CI. A check that could not run
            is never a check that passed.
          </p>
        </div>
      </main>
    </div>
  );
}

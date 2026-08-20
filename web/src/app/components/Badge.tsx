export function Badge({ type }: { type: "prod" | "demo" | "reference" | "verified" }) {
  const config = {
    prod: { label: "Prod ready", color: "var(--brand)", bg: "var(--brand-soft)" },
    demo: { label: "Demo", color: "var(--p1)", bg: "var(--p1-bg)" },
    reference: { label: "Reference", color: "var(--subtle)", bg: "var(--card)" },
    verified: { label: "Verified", color: "var(--pass)", bg: "var(--pass-bg)" },
  }[type];

  return (
    <span
      className="text-xs font-bold uppercase tracking-wider px-2 py-0.5 rounded-sm flex-shrink-0"
      style={{ color: config.color, background: config.bg, border: `1px solid ${config.color}30` }}
    >
      {config.label}
    </span>
  );
}

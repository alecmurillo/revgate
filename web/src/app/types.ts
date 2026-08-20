export type Severity = "P0" | "P1" | "P2";

export interface Finding {
  rule: string;
  severity: Severity;
  title: string;
  detail: string;
  remedy: string;
  origin: string;
  row: number;
  key: string;
  column: string;
}

export interface SkippedGate {
  rule: string;
  reason: string;
  blocking: boolean;
}

export interface LintResult {
  surface: string;
  target: string;
  verdict: "PASS" | "ADVISORY" | "BLOCKED";
  exit_code: number;
  counts: Record<Severity, number>;
  stats: {
    rows?: number;
    columns?: number;
    "gates run"?: number;
    "gates skipped"?: number;
    scenarios?: number;
    passed?: number;
    failed?: number;
    added?: number;
    removed?: number;
    changed?: number;
    "re-gated"?: number;
    "old rows"?: number;
    "new rows"?: number;
    [key: string]: number | undefined;
  };
  findings: Finding[];
  skipped: SkippedGate[];
  notes: string[];
}

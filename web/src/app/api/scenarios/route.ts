import { NextResponse } from "next/server";
import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

export async function GET() {
  const repoRoot = process.cwd().replace("/web", "");
  try {
    const result = await execFileAsync("python3", ["-m", "revgate", "scenarios", "--format", "json"], {
      cwd: repoRoot,
      maxBuffer: 10 * 1024 * 1024,
      env: { ...process.env, PYTHONPATH: repoRoot },
    });
    const data = JSON.parse(result.stdout);
    return NextResponse.json(data);
  } catch (err: unknown) {
    const e = err as { stdout?: string };
    try { return NextResponse.json(JSON.parse(e.stdout || "[]")); } catch {}
    return NextResponse.json({ error: "Failed to get scenarios" }, { status: 500 });
  }
}

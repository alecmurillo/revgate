import { NextResponse } from "next/server";
import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

export async function POST() {
  const repoRoot = process.cwd().replace("/web", "");
  const args = ["-m", "revgate", "redteam", "--target", "demo", "--format", "json", "--no-record"];

  let stdout = "";
  let exitCode = 0;

  try {
    const result = await execFileAsync("python3", args, {
      cwd: repoRoot,
      maxBuffer: 10 * 1024 * 1024,
      env: { ...process.env, PYTHONPATH: repoRoot },
    });
    stdout = result.stdout;
  } catch (err: unknown) {
    const e = err as { stdout?: string; code?: number };
    stdout = e.stdout || "";
    exitCode = e.code ?? 1;
  }

  try {
    const data = JSON.parse(stdout);
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: "Failed to parse redteam output", stdout, exitCode }, { status: 500 });
  }
}

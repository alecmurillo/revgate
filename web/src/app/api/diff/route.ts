import { NextRequest, NextResponse } from "next/server";
import { writeFile, mkdir, rm } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import { randomUUID } from "crypto";
import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const oldFile = formData.get("oldFile");
    const newFile = formData.get("newFile");
    const today = formData.get("today");

    if (!oldFile || !(oldFile instanceof File) || !newFile || !(newFile instanceof File)) {
      return NextResponse.json({ error: "Two CSV files required" }, { status: 400 });
    }

    const sessionId = randomUUID();
    const tempDir = join(tmpdir(), `revgate-diff-${sessionId}`);
    await mkdir(tempDir, { recursive: true });
    const oldPath = join(tempDir, "old.csv");
    const newPath = join(tempDir, "new.csv");

    await writeFile(oldPath, Buffer.from(await oldFile.arrayBuffer()));
    await writeFile(newPath, Buffer.from(await newFile.arrayBuffer()));

    const repoRoot = process.cwd().replace("/web", "");
    const args = ["-m", "revgate", "diff", oldPath, newPath, "--format", "json", "--no-record"];
    if (today && typeof today === "string") args.push("--today", today);

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

    await rm(tempDir, { recursive: true, force: true }).catch(() => {});

    try {
      const data = JSON.parse(stdout);
      return NextResponse.json(data);
    } catch {
      return NextResponse.json({ error: "Failed to parse diff output", stdout, exitCode }, { status: 500 });
    }
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : "Unknown error" }, { status: 500 });
  }
}

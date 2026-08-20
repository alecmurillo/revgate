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
    const file = formData.get("file");
    const today = formData.get("today");

    if (!file || !(file instanceof File)) {
      return NextResponse.json(
        { error: "No CSV file provided" },
        { status: 400 }
      );
    }

    // Write uploaded file to a temp directory
    const sessionId = randomUUID();
    const tempDir = join(tmpdir(), `revgate-${sessionId}`);
    await mkdir(tempDir, { recursive: true });
    const csvPath = join(tempDir, file.name);

    const bytes = await file.arrayBuffer();
    await writeFile(csvPath, Buffer.from(bytes));

    // Run revgate lint as a subprocess
    const repoRoot = process.cwd().replace("/web", "");
    const args = [
      "-m",
      "revgate",
      "lint",
      csvPath,
      "--format",
      "json",
      "--no-record",
    ];
    if (today && typeof today === "string") {
      args.push("--today", today);
    }

    let stdout: string;
    let stderr: string;
    let exitCode = 0;

    try {
      const result = await execFileAsync("python3", args, {
        cwd: repoRoot,
        maxBuffer: 10 * 1024 * 1024,
        env: { ...process.env, PYTHONPATH: repoRoot },
      });
      stdout = result.stdout;
      stderr = result.stderr;
    } catch (err: unknown) {
      const e = err as { stdout?: string; stderr?: string; code?: number };
      stdout = e.stdout || "";
      stderr = e.stderr || "";
      exitCode = e.code ?? 1;
    }

    // Clean up temp files
    await rm(tempDir, { recursive: true, force: true }).catch(() => {});

    // Parse the JSON output
    try {
      const data = JSON.parse(stdout);
      return NextResponse.json(data);
    } catch {
      return NextResponse.json(
        {
          error: "Failed to parse revgate output",
          stdout,
          stderr,
          exitCode,
        },
        { status: 500 }
      );
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

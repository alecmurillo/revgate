import { NextRequest, NextResponse } from "next/server";
import { readFile } from "fs/promises";
import { join } from "path";

export async function GET(request: NextRequest) {
  const which = request.nextUrl.searchParams.get("which");

  if (which !== "dirty" && which !== "clean") {
    return NextResponse.json(
      { error: "Invalid sample. Use ?which=dirty or ?which=clean" },
      { status: 400 }
    );
  }

  const repoRoot = process.cwd().replace("/web", "");
  const filename = which === "dirty" ? "leads-dirty.csv" : "leads-clean.csv";
  const filePath = join(repoRoot, "fixtures", filename);

  try {
    const data = await readFile(filePath);
    return new NextResponse(data, {
      headers: {
        "Content-Type": "text/csv",
        "Content-Disposition": `attachment; filename="${filename}"`,
      },
    });
  } catch {
    return NextResponse.json(
      { error: "Could not read sample file" },
      { status: 500 }
    );
  }
}

import fs from "node:fs";
import path from "node:path";

import { NextResponse } from "next/server";

const outputDir = path.join(process.cwd(), "output", "visualizations");

export async function GET(_request, { params }) {
  const resolvedParams = await params;
  const filePath = path.join(outputDir, resolvedParams.name);
  if (!fs.existsSync(filePath)) {
    return new NextResponse("Visualization not found", { status: 404 });
  }

  return new NextResponse(fs.readFileSync(filePath), {
    headers: {
      "Content-Type": "image/svg+xml"
    }
  });
}

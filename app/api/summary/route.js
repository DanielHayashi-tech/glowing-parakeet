import { NextResponse } from "next/server";

import { getDashboardSummary, getLatestActivity } from "@/lib/data";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({
    summary: getDashboardSummary(),
    latestActivity: getLatestActivity()
  });
}

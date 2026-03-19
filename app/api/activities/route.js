import { NextResponse } from "next/server";

import { getActivities } from "@/lib/data";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json(getActivities());
}

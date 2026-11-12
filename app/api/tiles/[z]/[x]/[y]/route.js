import fs from "node:fs";
import path from "node:path";

import { NextResponse } from "next/server";

import { getMapConfig, getTileCacheKey, getTileTemplate } from "@/lib/maps";

export const dynamic = "force-dynamic";

const MAX_ZOOM = 19;
const FETCH_TIMEOUT_MS = 10_000;
const cacheRoot = path.join(process.cwd(), "temp", "tiles");

function contentTypeFor(buffer) {
  if (buffer[0] === 0x89 && buffer[1] === 0x50) {
    return "image/png";
  }
  return "image/jpeg";
}

function imageResponse(buffer) {
  return new NextResponse(buffer, {
    headers: {
      "Content-Type": contentTypeFor(buffer),
      "Cache-Control": "public, max-age=86400"
    }
  });
}

export async function GET(_request, { params }) {
  if (!getMapConfig().enabled) {
    return new NextResponse("Map imagery is turned off", { status: 404 });
  }

  const { z, x, y } = await params;
  const zoom = Number(z);
  const tileX = Number(x);
  const tileY = Number(y);
  const limit = 2 ** zoom;
  const valid =
    Number.isInteger(zoom) &&
    Number.isInteger(tileX) &&
    Number.isInteger(tileY) &&
    zoom >= 0 &&
    zoom <= MAX_ZOOM &&
    tileX >= 0 &&
    tileY >= 0 &&
    tileX < limit &&
    tileY < limit;
  if (!valid) {
    return new NextResponse("Invalid tile", { status: 400 });
  }

  // Only integers validated above reach the path, so this cannot escape the cache folder.
  const cachePath = path.join(cacheRoot, getTileCacheKey(), String(zoom), String(tileX), `${tileY}.img`);
  if (fs.existsSync(cachePath)) {
    return imageResponse(fs.readFileSync(cachePath));
  }

  const url = getTileTemplate()
    .replace("{z}", String(zoom))
    .replace("{x}", String(tileX))
    .replace("{y}", String(tileY));

  try {
    const upstream = await fetch(url, {
      headers: { "User-Agent": "move2Zero-local-dashboard" },
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS)
    });
    const type = upstream.headers.get("content-type") ?? "";
    if (!upstream.ok || !type.startsWith("image/")) {
      return new NextResponse("No imagery for this tile", { status: 404 });
    }
    const buffer = Buffer.from(await upstream.arrayBuffer());
    fs.mkdirSync(path.dirname(cachePath), { recursive: true });
    fs.writeFileSync(cachePath, buffer);
    return imageResponse(buffer);
  } catch {
    return new NextResponse("Tile provider unreachable", { status: 502 });
  }
}

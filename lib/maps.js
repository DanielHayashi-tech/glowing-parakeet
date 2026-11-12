import crypto from "node:crypto";

// Satellite imagery behind the route map. Default is USGS The National Map
// (US government imagery, public domain, no key). Any XYZ tile service works:
// set MAP_TILE_URL with {z} {x} {y} placeholders, for example Esri World
// Imagery or Mapbox, and MAP_TILE_ATTRIBUTION to match. MAP_TILES=off turns
// the imagery off entirely (the route is then drawn on a plain background).
//
// Tiles are fetched by this server and cached on disk, so the browser never
// talks to the imagery provider and each tile is requested once.
const DEFAULT_TILE_URL =
  "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}";
const DEFAULT_ATTRIBUTION = "Imagery: USGS The National Map";

export function getTileTemplate() {
  const configured = (process.env.MAP_TILE_URL ?? "").trim();
  return configured || DEFAULT_TILE_URL;
}

export function getMapConfig() {
  const enabled = (process.env.MAP_TILES ?? "").trim().toLowerCase() !== "off";
  const attribution = (process.env.MAP_TILE_ATTRIBUTION ?? "").trim() || DEFAULT_ATTRIBUTION;
  return { enabled, attribution };
}

// Cache folder name derived from the provider so switching providers never
// serves another provider's tiles.
export function getTileCacheKey() {
  return crypto.createHash("sha256").update(getTileTemplate()).digest("hex").slice(0, 8);
}

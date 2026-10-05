import type { WindField } from './api'

/**
 * Bilinear interpolation of the (coarse, real) wind grid. Returns null
 * outside the grid — particles that leave the covered area are simply
 * respawned, never extrapolated.
 */
export function sampleWind(field: WindField, lat: number, lon: number): { u: number; v: number } | null {
  const { south, west, north, east, nx, ny, points } = field
  if (lat < south || lat > north || lon < west || lon > east) return null
  if (points.length !== nx * ny) return null
  const fx = ((lon - west) / (east - west)) * (nx - 1)
  const fy = ((lat - south) / (north - south)) * (ny - 1)
  const x0 = Math.min(Math.floor(fx), nx - 2)
  const y0 = Math.min(Math.floor(fy), ny - 2)
  const tx = fx - x0
  const ty = fy - y0
  const p = (xi: number, yi: number) => points[yi * nx + xi]
  const lerp = (a: number, b: number, t: number) => a + (b - a) * t
  const p00 = p(x0, y0)
  const p10 = p(x0 + 1, y0)
  const p01 = p(x0, y0 + 1)
  const p11 = p(x0 + 1, y0 + 1)
  return {
    u: lerp(lerp(p00.u, p10.u, tx), lerp(p01.u, p11.u, tx), ty),
    v: lerp(lerp(p00.v, p10.v, tx), lerp(p01.v, p11.v, tx), ty),
  }
}

/** Mean wind speed (m/s) across the grid, for the legend. */
export function meanSpeed(field: WindField): number {
  if (field.points.length === 0) return 0
  return field.points.reduce((s, p) => s + p.speed_ms, 0) / field.points.length
}

/** Bounds (padded) to request wind for, from village coordinates. */
export function windBoundsFor(coords: [number, number][], padDeg = 0.25) {
  const lats = coords.map((c) => c[0])
  const lons = coords.map((c) => c[1])
  return {
    south: Math.min(...lats) - padDeg,
    north: Math.max(...lats) + padDeg,
    west: Math.min(...lons) - padDeg,
    east: Math.max(...lons) + padDeg,
  }
}

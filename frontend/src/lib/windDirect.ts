import type { WindField, WindPoint } from './api'

/**
 * Fetch the real Open-Meteo wind grid straight from the viewer's browser.
 *
 * Why: Open-Meteo's free tier is rate-limited per source IP, and shared
 * hosting (Render free tier) egress IPs are shared with many other apps, so
 * server-side calls get 429s. A browser call uses the viewer's own IP and
 * quota. Same real data, same grid as the backend's GET /wind; nothing is
 * simulated, and a failure is reported as a failure.
 */
const OPEN_METEO_URL = 'https://api.open-meteo.com/v1/forecast'
const STEP = 0.25
const CACHE_PREFIX = 'girivarsha:wind:'
const FRESH_MS = 60 * 60 * 1000

export function snapOutward(b: { south: number; west: number; north: number; east: number }) {
  return {
    south: Math.floor(b.south / STEP) * STEP,
    west: Math.floor(b.west / STEP) * STEP,
    north: Math.ceil(b.north / STEP) * STEP,
    east: Math.ceil(b.east / STEP) * STEP,
  }
}

export function windComponents(speed: number, directionDeg: number): { u: number; v: number } {
  // Meteorological direction = where the wind comes FROM (0 = from north).
  const r = (directionDeg * Math.PI) / 180
  return { u: -speed * Math.sin(r), v: -speed * Math.cos(r) }
}

interface OpenMeteoEntry {
  current?: { time?: string; wind_speed_10m?: number; wind_direction_10m?: number; wind_gusts_10m?: number | null }
}

function readCache(key: string): WindField | null {
  try {
    const raw = sessionStorage.getItem(CACHE_PREFIX + key)
    if (!raw) return null
    const { at, field } = JSON.parse(raw) as { at: number; field: WindField }
    return Date.now() - at < FRESH_MS ? field : null
  } catch {
    return null
  }
}

function writeCache(key: string, field: WindField) {
  try {
    sessionStorage.setItem(CACHE_PREFIX + key, JSON.stringify({ at: Date.now(), field }))
  } catch {
    /* storage unavailable: fine, just no cache */
  }
}

export async function fetchWindDirect(
  bounds: { south: number; west: number; north: number; east: number },
  signal?: AbortSignal,
  n = 5,
): Promise<WindField> {
  const { south, west, north, east } = snapOutward(bounds)
  const key = [south, west, north, east, n].join(',')
  const cached = readCache(key)
  if (cached) return cached

  const coords: [number, number][] = []
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      const lat = south + ((north - south) * j) / (n - 1)
      const lon = west + ((east - west) * i) / (n - 1)
      coords.push([Math.round(lat * 1e4) / 1e4, Math.round(lon * 1e4) / 1e4])
    }
  }
  const qs = new URLSearchParams({
    latitude: coords.map((c) => c[0]).join(','),
    longitude: coords.map((c) => c[1]).join(','),
    current: 'wind_speed_10m,wind_direction_10m,wind_gusts_10m',
    wind_speed_unit: 'ms',
    timezone: 'UTC',
  })
  const res = await fetch(`${OPEN_METEO_URL}?${qs}`, { signal })
  if (!res.ok) throw new Error(`Open-Meteo wind unavailable (${res.status})`)
  const raw = (await res.json()) as OpenMeteoEntry[] | OpenMeteoEntry
  const entries = Array.isArray(raw) ? raw : [raw]
  if (entries.length !== coords.length) throw new Error('Open-Meteo wind response had the wrong shape')

  let validTime: string | null = null
  const points: WindPoint[] = entries.map((e, idx) => {
    const cur = e.current
    if (!cur || typeof cur.wind_speed_10m !== 'number' || typeof cur.wind_direction_10m !== 'number') {
      throw new Error('Open-Meteo wind response was missing values')
    }
    validTime = validTime ?? cur.time ?? null
    const { u, v } = windComponents(cur.wind_speed_10m, cur.wind_direction_10m)
    return {
      lat: coords[idx][0],
      lon: coords[idx][1],
      speed_ms: cur.wind_speed_10m,
      direction_deg: cur.wind_direction_10m,
      gust_ms: typeof cur.wind_gusts_10m === 'number' ? cur.wind_gusts_10m : null,
      u,
      v,
    }
  })

  const field: WindField = {
    south, west, north, east, nx: n, ny: n, points,
    valid_time: validTime,
    fetched_at: new Date().toISOString(),
    stale: false,
    source: 'real',
    provider: 'Open-Meteo (current 10 m wind, fetched by your browser)',
    note: 'Coarse regional wind field. Terrain-channelled valley winds are not resolved; context only, not used by the risk model.',
  }
  writeCache(key, field)
  return field
}

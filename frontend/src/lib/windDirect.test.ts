import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchWindDirect, snapOutward, windComponents } from './windDirect'

const entries = (n: number) =>
  Array.from({ length: n }, () => ({
    current: { time: '2026-10-05T15:00', wind_speed_10m: 4, wind_direction_10m: 270, wind_gusts_10m: 6 },
  }))

beforeEach(() => {
  try { sessionStorage.clear() } catch { /* ignore */ }
})

describe('windDirect', () => {
  it('snaps bounds outward to 0.25 degrees', () => {
    expect(snapOutward({ south: 30.03, west: 78.73, north: 30.98, east: 79.94 })).toEqual({
      south: 30, west: 78.5, north: 31, east: 80,
    })
  })

  it('converts meteorological direction to u/v', () => {
    const { u, v } = windComponents(4, 270) // from west -> blowing east
    expect(u).toBeCloseTo(4)
    expect(v).toBeCloseTo(0)
  })

  it('builds a real-tagged 5x5 grid from one Open-Meteo call, then serves the cache', async () => {
    const f = vi.fn(async () => ({ ok: true, status: 200, json: async () => entries(25) }))
    vi.stubGlobal('fetch', f)
    const b = { south: 30, west: 78.5, north: 31, east: 80 }
    const field = await fetchWindDirect(b)
    expect(field.source).toBe('real')
    expect(field.points).toHaveLength(25)
    expect(field.points[0].u).toBeCloseTo(4)
    await fetchWindDirect(b)
    expect(f).toHaveBeenCalledTimes(1)
  })

  it('throws (never invents values) on a 429 or a malformed payload', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 429, json: async () => ({}) })))
    await expect(fetchWindDirect({ south: 30, west: 78, north: 31, east: 79 })).rejects.toThrow(/429/)
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => [{ nope: 1 }] })))
    await expect(fetchWindDirect({ south: 30, west: 78, north: 31, east: 79 })).rejects.toThrow()
  })
})

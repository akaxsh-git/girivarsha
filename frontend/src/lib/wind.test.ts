import { describe, expect, it } from 'vitest'
import { meanSpeed, sampleWind, windBoundsFor } from './wind'
import type { WindField } from './api'

const pt = (lat: number, lon: number, u: number, v: number) => ({
  lat, lon, u, v, speed_ms: Math.hypot(u, v), direction_deg: 0, gust_ms: null,
})
const field: WindField = {
  south: 0, west: 0, north: 1, east: 1, nx: 2, ny: 2,
  points: [pt(0, 0, 0, 0), pt(0, 1, 10, 0), pt(1, 0, 0, 10), pt(1, 1, 10, 10)],
  valid_time: null, source: 'real', provider: 'Open-Meteo', note: '',
}

describe('sampleWind', () => {
  it('returns corner values exactly', () => {
    expect(sampleWind(field, 0, 1)).toEqual({ u: 10, v: 0 })
  })
  it('interpolates the centre', () => {
    const s = sampleWind(field, 0.5, 0.5)!
    expect(s.u).toBeCloseTo(5)
    expect(s.v).toBeCloseTo(5)
  })
  it('returns null outside the grid instead of extrapolating', () => {
    expect(sampleWind(field, 2, 0.5)).toBeNull()
  })
})

describe('helpers', () => {
  it('meanSpeed averages grid speeds', () => {
    expect(meanSpeed(field)).toBeGreaterThan(0)
  })
  it('windBoundsFor pads the village extent', () => {
    const b = windBoundsFor([[30, 79], [31, 80]], 0.5)
    expect(b).toEqual({ south: 29.5, north: 31.5, west: 78.5, east: 80.5 })
  })
})

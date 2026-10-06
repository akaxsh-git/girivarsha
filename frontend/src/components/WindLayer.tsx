import { useEffect } from 'react'
import { useMap } from 'react-leaflet'
import type { WindField } from '../lib/api'
import { sampleWind } from '../lib/wind'

interface WindLayerProps {
  field: WindField
}

interface Particle {
  lat: number
  lon: number
  age: number
}

const MAX_AGE = 80
// Visual step per frame (pixels). Purely a display scale: calm air still
// drifts visibly (a real 0.8 m/s breeze would otherwise be ~0.3 px/frame,
// i.e. invisible), and speed is encoded by colour band + relative motion,
// never to physical scale.
const MIN_STEP_PX = 1.0
const STEP_PX_PER_MS = 0.45
const MAX_STEP_PX = 5

export const WIND_BANDS: { max: number; label: string; colour: string }[] = [
  { max: 2, label: '< 2 m/s', colour: 'rgba(30,90,200,0.95)' },
  { max: 5, label: '2–5 m/s', colour: 'rgba(10,120,90,0.95)' },
  { max: 9, label: '5–9 m/s', colour: 'rgba(214,130,0,0.97)' },
  { max: Infinity, label: '≥ 9 m/s', colour: 'rgba(200,40,30,1)' },
]

function colourFor(speed: number): string {
  return (WIND_BANDS.find((b) => speed < b.max) ?? WIND_BANDS[WIND_BANDS.length - 1]).colour
}

/**
 * Animated particle wind layer drawn on a canvas over the Leaflet map,
 * driven by the REAL (coarse) Open-Meteo grid. Honours
 * prefers-reduced-motion by drawing a single static frame of streaks.
 */
export function WindLayer({ field }: WindLayerProps) {
  const map = useMap()

  useEffect(() => {
    const canvas = document.createElement('canvas')
    canvas.style.position = 'absolute'
    canvas.style.top = '0'
    canvas.style.left = '0'
    canvas.style.pointerEvents = 'none'
    canvas.style.zIndex = '450'
    canvas.setAttribute('aria-hidden', 'true')
    const container = map.getContainer()
    container.appendChild(canvas)
    const ctx = canvas.getContext('2d')
    if (!ctx) return () => canvas.remove()

    const reduced =
      typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1))
    let particleCount = 400
    const resize = () => {
      const size = map.getSize()
      canvas.width = Math.round(size.x * dpr)
      canvas.height = Math.round(size.y * dpr)
      canvas.style.width = `${size.x}px`
      canvas.style.height = `${size.y}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      particleCount = Math.max(150, Math.min(1200, Math.round((size.x * size.y) / 320)))
    }
    resize()

    const spawn = (): Particle => ({
      lat: field.south + Math.random() * (field.north - field.south),
      lon: field.west + Math.random() * (field.east - field.west),
      age: Math.floor(Math.random() * MAX_AGE),
    })
    let particles: Particle[] = Array.from({ length: particleCount }, spawn)
    let raf = 0

    const frame = () => {
      // Fade previous frame to leave trails.
      ctx.globalCompositeOperation = 'destination-in'
      ctx.fillStyle = 'rgba(0,0,0,0.955)'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.globalCompositeOperation = 'source-over'
      ctx.lineWidth = 2.2
      ctx.lineCap = 'round'
      for (const p of particles) {
        const w = sampleWind(field, p.lat, p.lon)
        if (!w || p.age > MAX_AGE) {
          Object.assign(p, spawn(), { age: 0 })
          continue
        }
        const from = map.latLngToContainerPoint([p.lat, p.lon])
        const speed = Math.hypot(w.u, w.v)
        if (speed < 0.05) {
          p.age += 1
          continue
        }
        const step = Math.min(MAX_STEP_PX, MIN_STEP_PX + speed * STEP_PX_PER_MS)
        const to = { x: from.x + (w.u / speed) * step, y: from.y - (w.v / speed) * step }
        ctx.strokeStyle = colourFor(speed)
        ctx.beginPath()
        ctx.moveTo(from.x, from.y)
        ctx.lineTo(to.x, to.y)
        ctx.stroke()
        const next = map.containerPointToLatLng([to.x, to.y])
        p.lat = next.lat
        p.lon = next.lng
        p.age += 1
      }
      if (!reduced) raf = requestAnimationFrame(frame)
    }

    const onViewChange = () => {
      resize()
      particles = Array.from({ length: particleCount }, spawn)
      if (reduced) for (let i = 0; i < 40; i++) frame()
    }
    map.on('moveend zoomend resize', onViewChange)

    if (reduced) {
      for (let i = 0; i < 40; i++) frame()
    } else {
      raf = requestAnimationFrame(frame)
    }

    return () => {
      cancelAnimationFrame(raf)
      map.off('moveend zoomend resize', onViewChange)
      canvas.remove()
    }
  }, [map, field])

  return null
}

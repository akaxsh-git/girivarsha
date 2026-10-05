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

const PARTICLE_COUNT = 700
const MAX_AGE = 90
// Pixels moved per frame per m/s of wind. Purely visual; speed is encoded
// by colour and by relative motion, not to physical scale.
const PX_PER_MS = 0.35

function colourFor(speed: number): string {
  if (speed < 2) return 'rgba(120,190,255,0.85)'
  if (speed < 5) return 'rgba(90,220,170,0.85)'
  if (speed < 9) return 'rgba(255,214,90,0.9)'
  return 'rgba(255,120,90,0.95)'
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

    const resize = () => {
      const size = map.getSize()
      canvas.width = size.x
      canvas.height = size.y
    }
    resize()

    const spawn = (): Particle => ({
      lat: field.south + Math.random() * (field.north - field.south),
      lon: field.west + Math.random() * (field.east - field.west),
      age: Math.floor(Math.random() * MAX_AGE),
    })
    let particles: Particle[] = Array.from({ length: PARTICLE_COUNT }, spawn)
    let raf = 0

    const frame = () => {
      // Fade previous frame to leave trails.
      ctx.globalCompositeOperation = 'destination-in'
      ctx.fillStyle = 'rgba(0,0,0,0.92)'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.globalCompositeOperation = 'source-over'
      ctx.lineWidth = 1.4
      for (const p of particles) {
        const w = sampleWind(field, p.lat, p.lon)
        if (!w || p.age > MAX_AGE) {
          Object.assign(p, spawn(), { age: 0 })
          continue
        }
        const from = map.latLngToContainerPoint([p.lat, p.lon])
        const speed = Math.hypot(w.u, w.v)
        const to = { x: from.x + w.u * PX_PER_MS, y: from.y - w.v * PX_PER_MS }
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
      particles = Array.from({ length: PARTICLE_COUNT }, spawn)
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

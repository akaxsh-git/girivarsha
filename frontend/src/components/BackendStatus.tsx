import { useEffect, useState } from 'react'
import { getHealth, type HealthResponse } from '../lib/api'

type Status = 'checking' | 'online' | 'offline'

export function BackendStatus() {
  const [status, setStatus] = useState<Status>('checking')
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    async function check() {
      try {
        const h = await getHealth(controller.signal)
        if (cancelled) return
        setHealth(h)
        setStatus('online')
      } catch {
        if (cancelled) return
        setStatus('offline')
      } finally {
        if (!cancelled) setCheckedAt(new Date())
      }
    }

    check()
    const id = setInterval(check, 8000)
    return () => {
      cancelled = true
      controller.abort()
      clearInterval(id)
    }
  }, [])

  const dotClass = status === 'online' ? 'dot dot-online' : status === 'offline' ? 'dot dot-offline' : 'dot dot-checking'

  const label = status === 'online' ? 'Live' : status === 'offline' ? 'Service unreachable' : 'Connecting…'
  const title =
    status === 'online' && health
      ? `Backend online — ${health.phase}${checkedAt ? ` · checked ${checkedAt.toLocaleTimeString()}` : ''}`
      : status === 'offline'
        ? 'The API is not responding. If you run this locally: cd backend && uvicorn app.main:app --reload'
        : 'Checking the API…'

  return (
    <div className="backend-status" title={title} role="status">
      <span className={dotClass} aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

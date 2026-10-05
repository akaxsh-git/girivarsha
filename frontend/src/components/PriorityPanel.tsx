import { useEffect, useState } from 'react'
import { getEvacuationPriority, type EvacuationPriorityEntry } from '../lib/api'

const LEVEL_CLASS: Record<string, string> = {
  LOW: 'risk-low',
  MODERATE: 'risk-moderate',
  HIGH: 'risk-high',
  CRITICAL: 'risk-critical',
}

interface PriorityPanelProps {
  regionId: number | null
}

/**
 * Phase 12 — evacuation priority ranking, for authority users. Real GET
 * /evacuation/priority — a transparent SORT of already-real/derived
 * numbers (risk level, then lead time, then risk score — see
 * backend/app/services/evacuation.py's `evacuation_priority`), never a
 * fabricated composite urgency score. Explicitly decision-support: this is
 * an ordering to help prioritize attention, not an evacuation order —
 * the standing disclaimer applies here like everywhere else in the app.
 */
export function PriorityPanel({ regionId }: PriorityPanelProps) {
  const [entries, setEntries] = useState<EvacuationPriorityEntry[] | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setEntries(null)
    getEvacuationPriority(controller.signal, regionId)
      .then((e) => {
        setEntries(e)
        setError(false)
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(true)
      })
    return () => controller.abort()
  }, [regionId])

  if (error) {
    return <p className="catchment-empty">Priority list unreachable — backend/DB may be down.</p>
  }
  if (entries === null) {
    return <p className="catchment-empty">Ranking villages…</p>
  }
  if (entries.length === 0) {
    return <p className="catchment-empty">No villages in scope.</p>
  }

  return (
    <ol className="priority-list">
      {entries.map((e) => (
        <li key={e.village_id} className="priority-row">
          <span className="priority-rank">#{e.rank}</span>
          <span className="priority-name">{e.village_name}</span>
          <span className={`risk-badge ${LEVEL_CLASS[e.risk_level] ?? ''}`}>{e.risk_level}</span>
          <span className="priority-score">{e.risk_score.toFixed(1)}</span>
          <span className="priority-lead-time">
            {e.lead_time_minutes !== null ? `${e.lead_time_minutes} min warning` : 'no upstream estimate'}
          </span>
        </li>
      ))}
    </ol>
  )
}

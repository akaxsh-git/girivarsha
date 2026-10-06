import { useEffect, useMemo, useState } from 'react'
import { getExplanation, type Explanation, type Village } from '../lib/api'

interface ExplanationPanelProps {
  villages: Village[] | null
}

/**
 * Phase 9 — "why is this village at risk", for authority users. Picks a
 * village, calls the real GET /model/explanation/{id} endpoint, and shows
 * its ranked real components in plain language. Deliberately NOT a SHAP
 * visualization of the undeployed ML layer — see
 * backend/app/services/explanation.py's module docstring, and the caveat
 * text this component renders verbatim from the API rather than
 * paraphrasing (so the honesty framing can't silently drift from the
 * backend's).
 */
interface CatchmentGroup {
  key: string
  name: string
  villages: Village[] // upstream -> downstream (by elevation, the app's ordering proxy)
}

function groupByCatchment(villages: Village[]): CatchmentGroup[] {
  const groups = new Map<string, CatchmentGroup>()
  for (const v of villages) {
    const key = v.catchment_id != null ? String(v.catchment_id) : 'none'
    const name = v.catchment_name ?? 'No catchment assigned'
    const g = groups.get(key) ?? { key, name, villages: [] }
    g.villages.push(v)
    groups.set(key, g)
  }
  for (const g of groups.values()) g.villages.sort((a, b) => (b.elevation_m ?? 0) - (a.elevation_m ?? 0))
  // Seed order (catchment id), so the original pilot valley comes first.
  return [...groups.values()].sort((a, b) => (a.key === 'none' ? 1 : b.key === 'none' ? -1 : Number(a.key) - Number(b.key)))
}

export function ExplanationPanel({ villages }: ExplanationPanelProps) {
  const groups = useMemo(() => groupByCatchment(villages ?? []), [villages])
  const [catchmentKey, setCatchmentKey] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [explanation, setExplanation] = useState<Explanation | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)

  // Keep the catchment/village pair valid when the region (and so the
  // village list) changes: default to the first catchment's most upstream village.
  const activeGroup = groups.find((g) => g.key === catchmentKey) ?? groups[0] ?? null
  useEffect(() => {
    if (!activeGroup) return
    if (catchmentKey !== activeGroup.key) setCatchmentKey(activeGroup.key)
    if (selectedId === null || !activeGroup.villages.some((v) => v.id === selectedId)) {
      setSelectedId(activeGroup.villages[0].id)
    }
  }, [activeGroup, catchmentKey, selectedId])

  useEffect(() => {
    if (selectedId === null) return
    const controller = new AbortController()
    setLoading(true)
    getExplanation(selectedId, controller.signal)
      .then((e) => {
        setExplanation(e)
        setError(false)
        setLoading(false)
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(true)
        setLoading(false)
      })
    return () => controller.abort()
  }, [selectedId])

  if (!villages || villages.length === 0) {
    return <p className="catchment-empty">Waiting for village list…</p>
  }

  return (
    <div className="explanation-panel">
      <div className="explain-pickers">
        <div className="explain-picker">
          <label htmlFor="explain-catchment-select">Catchment</label>
          <select
            id="explain-catchment-select"
            value={activeGroup?.key ?? ''}
            onChange={(e) => {
              const g = groups.find((x) => x.key === e.target.value)
              setCatchmentKey(e.target.value)
              if (g) setSelectedId(g.villages[0].id)
            }}
          >
            {groups.map((g) => (
              <option key={g.key} value={g.key}>
                {g.name} ({g.villages.length})
              </option>
            ))}
          </select>
        </div>
        <div className="explain-picker">
          <label htmlFor="explain-village-select">Explain the score for</label>
          <select
            id="explain-village-select"
            value={selectedId ?? ''}
            onChange={(e) => setSelectedId(Number(e.target.value))}
          >
            {(activeGroup?.villages ?? []).map((v, i, arr) => (
              <option key={v.id} value={v.id}>
                {v.name}
                {arr.length > 1 && i === 0 ? ' — most upstream' : ''}
                {arr.length > 1 && i === arr.length - 1 ? ' — most downstream' : ''}
              </option>
            ))}
          </select>
        </div>
      </div>
      {activeGroup && activeGroup.villages.length > 1 && (
        <ol className="explain-chain" aria-label="Villages in this catchment, upstream to downstream">
          {activeGroup.villages.map((v) => (
            <li key={v.id}>
              <button
                type="button"
                className={v.id === selectedId ? 'active' : ''}
                aria-pressed={v.id === selectedId}
                onClick={() => setSelectedId(v.id)}
              >
                {v.name}
              </button>
            </li>
          ))}
        </ol>
      )}

      {error ? (
        <p className="catchment-empty">Explanation unreachable — backend/DB may be down.</p>
      ) : loading || !explanation ? (
        <p className="catchment-empty">Computing explanation…</p>
      ) : (
        <div className="explanation-body">
          <p className="explanation-summary">{explanation.summary}</p>
          <ul className="explanation-drivers">
            {explanation.ranked_drivers.map((d) => (
              <li key={d.name} className="explanation-driver-row">
                <span className="explanation-driver-share">{d.share_of_score_pct.toFixed(0)}%</span>
                <span className="explanation-driver-label">
                  {d.plain_language}
                  {d.detail.includes('live sensor') && (
                    <span className="explanation-driver-detail"> — {d.detail}</span>
                  )}
                </span>
                <span className={`explanation-driver-source src-${d.source}`}>{d.source}</span>
                <span className="explanation-driver-raw">
                  {d.raw_value} {d.unit}
                </span>
              </li>
            ))}
          </ul>
          <details className="fine-print">
            <summary>About this explanation</summary>
            <p>Model explained: {explanation.model_explained}</p>
            <p>{explanation.caveat}</p>
          </details>
        </div>
      )}
    </div>
  )
}

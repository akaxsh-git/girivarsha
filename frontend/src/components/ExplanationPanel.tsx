import { useEffect, useState } from 'react'
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
export function ExplanationPanel({ villages }: ExplanationPanelProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [explanation, setExplanation] = useState<Explanation | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (selectedId === null && villages && villages.length > 0) {
      setSelectedId(villages[0].id)
    }
  }, [villages, selectedId])

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
      <label htmlFor="explain-village-select">Explain the score for</label>
      <select
        id="explain-village-select"
        value={selectedId ?? ''}
        onChange={(e) => setSelectedId(Number(e.target.value))}
      >
        {villages.map((v) => (
          <option key={v.id} value={v.id}>
            {v.name}
          </option>
        ))}
      </select>

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
          <p className="explanation-model">Model explained: {explanation.model_explained}</p>
          <p className="explanation-caveat">{explanation.caveat}</p>
        </div>
      )}
    </div>
  )
}

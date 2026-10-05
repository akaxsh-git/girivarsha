import { useEffect, useState } from 'react'
import { getAllEvacuationRoutes, getEvacuationRoute, type EvacuationRoute, type Village } from '../lib/api'

interface EvacuationPanelProps {
  villages: Village[] | null
  regionId: number | null
}

/**
 * Phase 12 — evacuation routing, for authority users. Every seeded village
 * already has its own real, computable route (GET /evacuation/route/{id},
 * app/services/evacuation.py), but originally this panel only ever showed
 * one village's route at a time behind a dropdown. This follow-up
 * (user-requested: "an evacuation route for each village") adds an
 * "every village at a glance" summary table (real GET /evacuation/routes,
 * one call for the whole region) above the existing detailed per-village
 * drill-down — the drill-down is kept because the summary row deliberately
 * omits hop-by-hop detail (unsafe-hop flags, per-leg distance) to stay
 * scannable.
 *
 * Road-network follow-up (user-requested): each hop's own `distance_source`
 * now says honestly whether its distance came from a real OpenStreetMap
 * road/trail path or the original straight-line elevation-order proxy —
 * see backend/app/services/evacuation.py's module docstring for exactly
 * when each applies. This component renders the API's own
 * `note`/`unsafe_reason`/`road_note` text verbatim rather than
 * paraphrasing, so the honesty framing can't drift from the backend's.
 */
export function EvacuationPanel({ villages, regionId }: EvacuationPanelProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [route, setRoute] = useState<EvacuationRoute | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)

  const [allRoutes, setAllRoutes] = useState<EvacuationRoute[] | null>(null)
  const [allRoutesError, setAllRoutesError] = useState(false)

  useEffect(() => {
    if (selectedId === null && villages && villages.length > 0) {
      setSelectedId(villages[0].id)
    }
  }, [villages, selectedId])

  useEffect(() => {
    if (selectedId === null) return
    const controller = new AbortController()
    setLoading(true)
    getEvacuationRoute(selectedId, controller.signal)
      .then((r) => {
        setRoute(r)
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

  useEffect(() => {
    const controller = new AbortController()
    setAllRoutes(null)
    getAllEvacuationRoutes(regionId, controller.signal)
      .then((r) => {
        setAllRoutes(r)
        setAllRoutesError(false)
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setAllRoutesError(true)
      })
    return () => controller.abort()
  }, [regionId])

  if (!villages || villages.length === 0) {
    return <p className="catchment-empty">Waiting for village list…</p>
  }

  return (
    <div className="evacuation-panel">
      <div className="evacuation-all-routes">
        <h4>Every village's route, at a glance</h4>
        {allRoutesError ? (
          <p className="catchment-empty">Route summary unreachable — backend/DB may be down.</p>
        ) : allRoutes === null ? (
          <p className="catchment-empty">Computing routes…</p>
        ) : allRoutes.length === 0 ? (
          <p className="catchment-empty">No villages with an assigned micro-catchment in scope.</p>
        ) : (
          <table className="evacuation-all-routes-table">
            <thead>
              <tr>
                <th>Village</th>
                <th>Evacuation destination</th>
                <th>Distance</th>
                <th>Est. time</th>
                <th>Route data</th>
                <th>Unsafe hops</th>
              </tr>
            </thead>
            <tbody>
              {allRoutes.map((r) => {
                const unsafeCount = r.hops.filter((h) => h.unsafe).length
                const realCount = r.hops.filter((h) => h.distance_source === 'real_road_network').length
                return (
                  <tr
                    key={r.origin_village_id}
                    className={r.origin_village_id === selectedId ? 'evacuation-all-routes-row-selected' : ''}
                    onClick={() => setSelectedId(r.origin_village_id)}
                  >
                    <td>{r.origin_village_name}</td>
                    <td>{r.destination_village_name ?? '—'}</td>
                    <td>{r.hops.length > 0 ? `${r.total_distance_km} km` : '—'}</td>
                    <td>{r.estimated_minutes !== null ? `~${Math.round(r.estimated_minutes)} min` : '—'}</td>
                    <td>
                      {r.hops.length === 0 ? (
                        '—'
                      ) : realCount === r.hops.length ? (
                        <span className="evacuation-road-badge evacuation-road-badge-real">real road/trail</span>
                      ) : realCount === 0 ? (
                        <span className="evacuation-road-badge evacuation-road-badge-proxy">straight-line est.</span>
                      ) : (
                        <span className="evacuation-road-badge evacuation-road-badge-mixed">
                          {realCount}/{r.hops.length} real
                        </span>
                      )}
                    </td>
                    <td>
                      {unsafeCount > 0 ? (
                        <span className="evacuation-hop-flag">⚠ {unsafeCount}</span>
                      ) : r.hops.length > 0 ? (
                        'none'
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        <p className="evacuation-note">
          Click a row to see its full hop-by-hop breakdown below. "Route data" shows how much of each
          route uses a real OpenStreetMap road/trail path vs. the straight-line elevation-order proxy
          (used only where real coverage doesn't reach) — see backend/app/services/evacuation.py.
        </p>
      </div>

      <label htmlFor="evacuation-village-select">Route detail from</label>
      <select
        id="evacuation-village-select"
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
        <p className="catchment-empty">Route unreachable — backend/DB may be down.</p>
      ) : loading || !route ? (
        <p className="catchment-empty">Computing route…</p>
      ) : route.hops.length === 0 ? (
        <p className="evacuation-note">{route.note}</p>
      ) : (
        <div className="evacuation-body">
          <div className="evacuation-summary">
            <span>
              To <strong>{route.destination_village_name}</strong>
            </span>
            <span>{route.total_distance_km} km</span>
            <span>
              {route.estimated_minutes !== null
                ? `~${Math.round(route.estimated_minutes)} min on foot (prototype)`
                : ''}
            </span>
          </div>
          <ol className="evacuation-hops">
            {route.hops.map((h, i) => (
              <li key={i} className={`evacuation-hop-row${h.unsafe ? ' evacuation-hop-unsafe' : ''}`}>
                <span className="evacuation-hop-leg">
                  {h.from_village_name} → {h.to_village_name}
                </span>
                <span className="evacuation-hop-distance">{h.distance_km} km</span>
                <span
                  className={`evacuation-road-badge ${
                    h.distance_source === 'real_road_network'
                      ? 'evacuation-road-badge-real'
                      : 'evacuation-road-badge-proxy'
                  }`}
                >
                  {h.distance_source === 'real_road_network' ? 'real road/trail' : 'straight-line est.'}
                </span>
                {h.unsafe && <span className="evacuation-hop-flag">⚠ flagged</span>}
                {h.road_note && <p className="evacuation-hop-road-note">{h.road_note}</p>}
                {h.unsafe && h.unsafe_reason && <p className="evacuation-hop-reason">{h.unsafe_reason}</p>}
              </li>
            ))}
          </ol>
          <p className="evacuation-note">{route.note}</p>
        </div>
      )}
    </div>
  )
}

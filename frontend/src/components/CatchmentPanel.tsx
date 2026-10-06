import type { MicroCatchment } from '../lib/api'

interface CatchmentPanelProps {
  catchments: MicroCatchment[] | null
  error: boolean
}

/**
 * Shows real catchment topology (name, watershed, river, village count,
 * upstream/downstream links) from the database. Deliberately does NOT
 * render a fake polygon boundary when `has_polygon_geometry` is false —
 * see docs/GIS_Methodology.md and gis/delineate_catchment.py for why real
 * boundaries aren't populated yet and what it takes to add them.
 */
export function CatchmentPanel({ catchments, error }: CatchmentPanelProps) {
  if (error) {
    return <p className="catchment-empty">Catchment data unreachable — backend/DB may be down.</p>
  }
  if (catchments === null) {
    return <p className="catchment-empty">Loading catchment topology…</p>
  }
  if (catchments.length === 0) {
    return <p className="catchment-empty">No catchments seeded yet.</p>
  }

  return (
    <ul className="catchment-list">
      {catchments.map((c) => (
        <li key={c.id} className="catchment-card">
          <div className="catchment-head">
            <strong>{c.name}</strong>
            <span className="catchment-source">{c.source}</span>
          </div>
          <div className="catchment-meta">
            {c.watershed_name}
            {c.river_name ? ` · ${c.river_name}` : ''} · {c.village_count} villages
          </div>
          <div className={`catchment-geom ${c.has_polygon_geometry ? 'ok' : 'pending'}`}>
            {c.has_polygon_geometry
              ? 'Real delineated boundary available'
              : 'No real boundary polygon yet — upstream/downstream order only'}
          </div>
        </li>
      ))}
    </ul>
  )
}

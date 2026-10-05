import { useMemo } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup, Polyline } from 'react-leaflet'
import { latLngBounds, type LatLngBoundsExpression } from 'leaflet'
import type { Village } from '../lib/api'
import 'leaflet/dist/leaflet.css'

interface PilotMapProps {
  villages: Village[]
}

// Kedarnath -> Rudraprayag, roughly centred on the seeded pilot villages.
// Used only as a last-resort fallback view if there's no village data at all.
const FALLBACK_CENTER: [number, number] = [30.55, 79.0]

/**
 * Real village points, real coordinates (surveyed or honestly-labelled
 * approximate — see docs/Data_Sources.md). What this map does NOT show yet:
 * real catchment polygon boundaries (Phase 3 GIS delineation needs DEM
 * access this build sandbox couldn't reach — see docs/GIS_Methodology.md
 * and gis/delineate_catchment.py) or a real digitised river line. The
 * dashed line below is a visual aid only, connecting villages in elevation
 * order to suggest the valley's downstream direction — it is NOT the
 * river's actual course and is labelled as such in the legend.
 */
export function PilotMap({ villages }: PilotMapProps) {
  // Fit the map to every village's real coordinates rather than a fixed
  // zoom level — a fixed zoom silently clips villages that fall outside
  // the initial view, which would misrepresent which villages are actually
  // being monitored.
  const bounds = useMemo<LatLngBoundsExpression>(() => {
    if (villages.length === 0) {
      return latLngBounds([FALLBACK_CENTER, FALLBACK_CENTER]).pad(0.5)
    }
    return latLngBounds(villages.map((v) => [v.lat, v.lon] as [number, number]))
  }, [villages])

  // Phase 11: villages can now span multiple, unrelated real valleys
  // (regions) at once. Sorting ALL of them by elevation and drawing one
  // line would draw a nonsense "river" jumping between valleys — e.g.
  // straight from a Chamoli village to a Mandakini one just because their
  // elevations happen to be adjacent. So this groups by catchment first,
  // and draws one elevation-order dashed line per catchment — still just a
  // visual aid, never the real river course, but now honest even with two+
  // regions' villages on screen together.
  const elevationOrderPathsByCatchment = useMemo<[number, number][][]>(() => {
    const groups = new Map<number | string, Village[]>()
    for (const v of villages) {
      const key = v.catchment_id ?? `unassigned-${v.id}`
      const group = groups.get(key)
      if (group) group.push(v)
      else groups.set(key, [v])
    }
    return [...groups.values()]
      .filter((group) => group.length > 1)
      .map((group) =>
        [...group]
          .sort((a, b) => (b.elevation_m ?? 0) - (a.elevation_m ?? 0))
          .map((v) => [v.lat, v.lon] as [number, number]),
      )
  }, [villages])

  if (villages.length === 0) {
    return (
      <div className="map-empty" role="status">
        No village location data available yet — the backend/database may be unreachable.
      </div>
    )
  }

  return (
    <div className="map-wrap">
      <MapContainer
        bounds={bounds}
        boundsOptions={{ padding: [32, 32] }}
        scrollWheelZoom={false}
        style={{ height: '420px', width: '100%', borderRadius: '12px' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {elevationOrderPathsByCatchment.map((path, i) => (
          <Polyline
            key={i}
            positions={path}
            pathOptions={{ color: '#5C6B64', weight: 2, dashArray: '4 6', opacity: 0.6 }}
          />
        ))}
        {villages.map((v) => (
          <CircleMarker
            key={v.id}
            center={[v.lat, v.lon]}
            radius={8}
            pathOptions={{
              color: v.coordinate_precision === 'surveyed' ? '#0E6E63' : '#B8860B',
              fillColor: v.coordinate_precision === 'surveyed' ? '#0E6E63' : '#B8860B',
              fillOpacity: 0.75,
              weight: 2,
            }}
          >
            <Popup>
              <strong>{v.name}</strong>
              <br />
              {v.district}, {v.state}
              <br />
              Elevation: {v.elevation_m != null ? `${v.elevation_m} m` : 'unknown'}
              <br />
              Coordinates: {v.coordinate_precision}
              <br />
              Catchment: {v.catchment_name ?? 'unassigned'}
              <br />
              <em style={{ fontSize: '0.8em' }}>Source: {v.source}</em>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
      <div className="map-legend">
        <span>
          <i className="dot-legend" style={{ background: '#0E6E63' }} /> Surveyed coordinates
        </span>
        <span>
          <i className="dot-legend" style={{ background: '#B8860B' }} /> Approximate coordinates
        </span>
        <span>
          <i className="line-legend" /> Elevation order within each catchment only — not the real river course
        </span>
      </div>
    </div>
  )
}

import type { Sensor } from '../lib/api'

interface SensorPanelProps {
  sensors: Sensor[] | null
  error: boolean
}

const STATUS_CLASS: Record<string, string> = {
  online: 'sensor-online',
  stale: 'sensor-stale',
  offline: 'sensor-offline',
}

function formatAge(seconds: number | null): string {
  if (seconds === null) return 'never reported'
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  return `${Math.round(seconds / 3600)}h ago`
}

/**
 * Phase 8: the real sensor registry, GET /sensors. Status badges are the
 * backend's LIVE-computed freshness (never a stored value the frontend
 * just trusts) — see app/api/routes/sensors.py:_compute_status. The note
 * below is load-bearing, not decoration: today's readings flow through a
 * real MQTT broker + real bridge + this real ingestion API, but the
 * publisher standing in for physical hardware is a simulator
 * (iot/simulate_sensor_publisher.py) — see docs/IoT_Architecture.md.
 *
 * Device-authentication follow-up (user-requested): each row also shows
 * whether THIS device has a real per-device API key on file
 * (`authenticated`, from `sensors.api_key_hash`) — "no key" is the honest
 * pre-migration/not-yet-rotated state, not an error, since such a device
 * still works exactly as before. Never hidden, per this project's
 * disclosed-limitations discipline. See docs/IoT_Architecture.md's
 * "Sensor authentication" section.
 *
 * Real-regional-data fallback (user-requested follow-up — "why do we need
 * the simulator if we have real values"): when a sensor has no live
 * reading of its own, the value cell shows a REAL Open-Meteo regional
 * estimate instead of a bare dash, styled in italic/muted (.sensor-value
 * -fallback) and labelled "regional est." so it is never mistaken for that
 * device's own measurement — it's real weather data, just not from this
 * exact sensor.
 */
/** Compact display unit; the full unit stays in the API response. */
function shortUnit(unit: string | null): string {
  if (!unit) return ''
  return unit.startsWith('pct') ? '% vol.' : unit
}

export function SensorPanel({ sensors, error }: SensorPanelProps) {
  if (error) {
    return <p className="catchment-empty">Sensor registry unreachable — backend/DB may be down.</p>
  }
  if (sensors === null) {
    return <p className="catchment-empty">Loading sensor network…</p>
  }
  if (sensors.length === 0) {
    return (
      <p className="catchment-empty">
        No sensor nodes provisioned yet.
      </p>
    )
  }

  return (
    <div>
      <p className="sensor-note">
        No field hardware is deployed yet; when the demo pipeline runs, a simulator publishes the values.
      </p>
      <ul className="sensor-list">
        {sensors.map((s) => (
          <li key={s.id} className="sensor-row">
            <span className={`risk-badge ${STATUS_CLASS[s.status] ?? ''}`}>{s.status}</span>
            <span className="sensor-id">
              <span className="sensor-device">{s.external_device_id}</span>
              <span className="sensor-meta">
                {s.village_name ?? 'unassigned'} · {s.sensor_type.replace('_', ' ')}
              </span>
            </span>
            <span className="sensor-value">
              {s.last_value !== null ? (
                `${s.last_value} ${shortUnit(s.last_unit)}`
              ) : s.fallback_value !== null ? (
                <span
                  className="sensor-value-fallback"
                  title="No live reading from this device — real Open-Meteo regional weather estimate for its village, not this sensor's own measurement."
                >
                  ~{s.fallback_value} {shortUnit(s.fallback_unit)} (regional est.)
                </span>
              ) : (
                '—'
              )}
            </span>
            <span className="sensor-age">{formatAge(s.seconds_since_last_seen)}</span>
            <span
              className={`sensor-auth ${s.authenticated ? 'sensor-auth-yes' : 'sensor-auth-no'}`}
              title={
                s.authenticated
                  ? 'This device has its own API key; readings without it are rejected.'
                  : 'No API key on file yet — this device is accepted un-authenticated until a key is issued.'
              }
            >
              {s.authenticated ? 'keyed' : 'no key'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

import type { Alert, AlertStreamStatus, RiskMapEntry } from '../lib/api'

interface RiskPanelProps {
  riskMap: RiskMapEntry[] | null
  riskError: boolean
  alerts: Alert[] | null
  alertsError: boolean
  // Real-time push follow-up (user-requested) — optional so existing
  // callers/tests that don't pass it render exactly as before (no badge).
  liveStatus?: AlertStreamStatus
  /** false = render the risk list only (the dashboard shows AlertsPanel separately). */
  showAlerts?: boolean
}

const LIVE_STATUS_COPY: Record<AlertStreamStatus, string> = {
  connecting: 'Connecting…',
  live: 'Live',
  offline: 'Offline',
}

const LIVE_STATUS_DOT: Record<AlertStreamStatus, string> = {
  connecting: 'dot-checking',
  live: 'dot-online',
  offline: 'dot-offline',
}

const LEVEL_CLASS: Record<string, string> = {
  LOW: 'risk-low',
  MODERATE: 'risk-moderate',
  HIGH: 'risk-high',
  CRITICAL: 'risk-critical',
}

// Plain-language labels for rainfall_threshold_status (see
// backend/app/services/rainfall_threshold.py) — the raw enum strings are
// meant for API consumers, not this UI.
const RAINFALL_THRESHOLD_LABEL: Record<string, string> = {
  below_floor: 'below study floor',
  threshold_exceeded: 'threshold exceeded',
  approaching_within_24h: 'approaching within 24h',
  not_indicated_within_24h: 'not indicated within 24h',
  not_applicable: 'not calibrated for this region',
}

/**
 * Shows the Phase 4 transparent baseline risk score per village and any
 * currently open alerts. Every number here comes from
 * app/services/risk_engine.py's documented weighted formula — nothing is
 * hard-coded, and confidence is deliberately shown alongside the score so
 * it's never presented as more certain than the active inputs support.
 * Rainfall/soil-moisture are simulated by default but can be switched to
 * real (Open-Meteo, opt-in — see README "Real weather data") without any
 * change to this component; confidence and the per-village driver
 * breakdown (Authority "Explain this score" panel) reflect whichever is
 * actually active, never a fixed claim either way.
 */
export function RiskPanel({ riskMap, riskError, alerts, alertsError, liveStatus, showAlerts = true }: RiskPanelProps) {
  return (
    <div className="risk-panel">
      <p className="risk-disclaimer">
        Transparent weighted formula — not a validated model and not an official warning.
      </p>

      {riskError ? (
        <p className="catchment-empty">Risk data unreachable right now.</p>
      ) : riskMap === null ? (
        <p className="catchment-empty">Computing baseline risk scores…</p>
      ) : (
        <ul className="risk-list">
          {[...riskMap]
            .sort((a, b) => b.risk_score - a.risk_score)
            .map((r) => (
              <li key={r.village_id} className="risk-row">
                <div className="risk-main">
                  <span className={`risk-badge ${LEVEL_CLASS[r.risk_level] ?? ''}`}>{r.risk_level}</span>
                  <span className="risk-name">{r.village_name}</span>
                  <span className="risk-meter" aria-hidden="true">
                    <span
                      className={`risk-meter-fill ${LEVEL_CLASS[r.risk_level] ?? ''}`}
                      style={{ width: `${Math.max(2, Math.min(100, r.risk_score))}%` }}
                    />
                  </span>
                  <span className="risk-score">{r.risk_score.toFixed(1)}/100</span>
                </div>
                <div className="risk-extras">
                  <span className="risk-confidence">confidence {r.confidence_pct.toFixed(0)}%</span>
                  <span className="risk-lead-time">
                    {r.lead_time_minutes !== null ? `~${r.lead_time_minutes} min lead time` : 'no upstream lead time'}
                  </span>
                  {r.glacial_lake_distance_km != null && (
                    <span className="risk-glacial-lake" title="Advisory only — not part of the risk score.">
                      nearest glacial lake ~{r.glacial_lake_distance_km.toFixed(1)} km
                    </span>
                  )}
                  {r.glof_contribution_pct != null && (
                    <span
                      className="risk-glof-indicator"
                      title="Heuristic blend of glacial-lake proximity and glacier melt rate — not a calibrated flash-flood probability."
                    >
                      glacial hazard context: {r.glof_contribution_tier} ({r.glof_contribution_pct.toFixed(0)}%)
                    </span>
                  )}
                  {r.scs_cn_runoff_depth_mm != null && (
                    <span
                      className="risk-scs-cn"
                      title="Independent NRCS TR-55 (SCS-CN) rainfall-runoff estimate, shown alongside the score and never folded into it."
                    >
                      SCS-CN runoff: {r.scs_cn_runoff_depth_mm.toFixed(1)} mm (CN {r.scs_cn_curve_number?.toFixed(0)})
                    </span>
                  )}
                  {r.rainfall_threshold_status != null && (
                    <span
                      className="risk-rainfall-threshold"
                      title="Region-specific rainfall intensity-duration landslide threshold (Kanungo & Sharma 2014) — an advisory indicator, not part of the score."
                    >
                      I-D threshold: {RAINFALL_THRESHOLD_LABEL[r.rainfall_threshold_status] ?? r.rainfall_threshold_status}
                      {r.rainfall_threshold_hours_to_threshold != null &&
                        ` (~${r.rainfall_threshold_hours_to_threshold.toFixed(1)}h)`}
                    </span>
                  )}
                  {r.antecedent_rainfall_5day_mm != null && (
                    <span
                      className="risk-antecedent-rainfall"
                      title={`${r.antecedent_rainfall_source === 'real' ? 'Real (NASA POWER)' : 'Simulated'} recent rainfall history, used as the soil-wetness input to the SCS-CN estimate.`}
                    >
                      5-day antecedent rainfall: {r.antecedent_rainfall_5day_mm.toFixed(1)} mm
                      {r.antecedent_rainfall_source === 'simulated' && ' (simulated)'}
                    </span>
                  )}
                </div>
              </li>
            ))}
        </ul>
      )}

      {showAlerts && (
        <>
          <h3 className="risk-subheading">
            Active alerts
            {liveStatus && <LiveBadge status={liveStatus} />}
          </h3>
          <AlertsList alerts={alerts} alertsError={alertsError} />
        </>
      )}
    </div>
  )
}

export function LiveBadge({ status }: { status: AlertStreamStatus }) {
  return (
    <span className="live-status">
      <span className={`dot ${LIVE_STATUS_DOT[status]}`} aria-hidden="true" />
      {LIVE_STATUS_COPY[status]}
    </span>
  )
}

export function AlertsList({ alerts, alertsError }: { alerts: Alert[] | null; alertsError: boolean }) {
  if (alertsError) return <p className="catchment-empty">Alerts unreachable right now.</p>
  if (alerts === null) return <p className="catchment-empty">Loading alerts…</p>
  if (alerts.length === 0) {
    return (
      <div className="alerts-empty">
        <span className="alerts-empty-dot" aria-hidden="true" />
        No open alerts — every village is currently at LOW/GREEN.
      </div>
    )
  }
  return (
    <ul className="alert-list">
      {alerts.map((a) => (
        <li key={a.id} className="alert-row">
          <span className={`risk-badge alert-${a.level.toLowerCase()}`}>{a.level}</span>
          <span className="risk-name">{a.village_name}</span>
          <span className="alert-message">{a.message}</span>
        </li>
      ))}
    </ul>
  )
}

// Thin fetch wrapper around the backend. Deliberately tiny in Phase 1 —
// grows into a typed client as real endpoints (villages, risk, alerts) land.
export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface HealthResponse {
  status: string
  app: string
  phase: string
  time: string
}

export interface Village {
  id: number
  name: string
  district: string
  state: string
  elevation_m: number | null
  population: number | null
  lat: number
  lon: number
  coordinate_precision: 'surveyed' | 'approximate'
  catchment_id: number | null
  catchment_name: string | null
  region_id: number | null
  region_name: string | null
  source: string
  provenance: string | null
}

export interface MicroCatchment {
  id: number
  name: string
  watershed_name: string
  river_name: string | null
  region_id: number | null
  region_name: string | null
  upstream_catchment_id: number | null
  has_polygon_geometry: boolean
  village_count: number
  source: string
  provenance: string | null
}

export interface Region {
  id: number
  name: string
  states: string
  description: string
  status: 'active' | 'planned'
  village_count: number
  catchment_count: number
  source: string
  provenance: string | null
}

export interface RiskMapEntry {
  village_id: number
  village_name: string
  risk_score: number
  risk_level: 'LOW' | 'MODERATE' | 'HIGH' | 'CRITICAL'
  confidence_pct: number
  lead_time_minutes: number | null
  // Real, advisory-only field (not folded into risk_score/risk_level) —
  // straight-line distance in km to the nearest satellite-mapped glacial
  // lake. See backend/app/services/glacial_lake_proximity.py.
  glacial_lake_distance_km?: number | null
  // Real, advisory-only (not folded into risk_score/risk_level) 0-100
  // heuristic blend of glacial-lake proximity + glacier melt rate — NOT a
  // calibrated statistical flash-flood probability. See
  // backend/app/services/glacial_melt_hazard.py.
  glof_contribution_pct?: number | null
  glof_contribution_tier?: 'LOW' | 'MODERATE' | 'HIGH' | null
  // Real, independent NRCS TR-55 rainfall-runoff estimate (SCS-CN method) —
  // shown ALONGSIDE, never folded into, risk_score/risk_level. Honestly
  // null for a village whose land cover is snow/ice or open water, or if
  // the committed soil/land-cover dataset is missing. See
  // backend/app/services/scs_cn_runoff.py.
  scs_cn_runoff_depth_mm?: number | null
  scs_cn_curve_number?: number | null
  // Real, independent rainfall intensity-duration (I-D) landslide-threshold
  // indicator (Kanungo & Sharma 2014, a real region-specific study) — shown
  // ALONGSIDE, never folded into, risk_score/risk_level. See
  // backend/app/services/rainfall_threshold.py.
  rainfall_threshold_hours_to_threshold?: number | null
  rainfall_threshold_status?:
    | 'below_floor'
    | 'threshold_exceeded'
    | 'approaching_within_24h'
    | 'not_indicated_within_24h'
    | null
  // Real, or clearly-labelled simulated, antecedent-precipitation-index
  // figure (user-requested follow-up, from this project's own competitive-
  // landscape research) — feeds the SCS-CN AMC classification above
  // whenever it's real. See backend/app/services/antecedent_rainfall.py.
  antecedent_rainfall_5day_mm?: number | null
  antecedent_rainfall_source?: 'real' | 'simulated' | null
}

export interface Alert {
  id: number
  village_id: number
  village_name: string
  level: 'GREEN' | 'YELLOW' | 'ORANGE' | 'RED'
  message: string
  risk_score: number | null
  issued_at: string
  resolved_at: string | null
}

export class ApiError extends Error {}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/api/v1/health`, { signal })
  if (!res.ok) throw new ApiError(`Health check failed: HTTP ${res.status}`)
  return res.json()
}

export async function getVillages(signal?: AbortSignal, regionId?: number | null): Promise<Village[]> {
  const qs = regionId != null ? `?region_id=${regionId}` : ''
  const res = await fetch(`${API_BASE}/api/v1/villages${qs}`, { signal })
  if (!res.ok) throw new ApiError(`GET /villages failed: HTTP ${res.status}`)
  return res.json()
}

export async function getCatchments(signal?: AbortSignal, regionId?: number | null): Promise<MicroCatchment[]> {
  const qs = regionId != null ? `?region_id=${regionId}` : ''
  const res = await fetch(`${API_BASE}/api/v1/catchments${qs}`, { signal })
  if (!res.ok) throw new ApiError(`GET /catchments failed: HTTP ${res.status}`)
  return res.json()
}

export async function getRiskMap(signal?: AbortSignal, regionId?: number | null): Promise<RiskMapEntry[]> {
  const qs = regionId != null ? `?region_id=${regionId}` : ''
  const res = await fetch(`${API_BASE}/api/v1/risk/map${qs}`, { signal })
  if (!res.ok) throw new ApiError(`GET /risk/map failed: HTTP ${res.status}`)
  return res.json()
}

export async function getRegions(signal?: AbortSignal): Promise<Region[]> {
  const res = await fetch(`${API_BASE}/api/v1/regions`, { signal })
  if (!res.ok) throw new ApiError(`GET /regions failed: HTTP ${res.status}`)
  return res.json()
}

export interface RiskDriver {
  name: string
  raw_value: number
  unit: string
  data_source: string
  normalized_value: number
  weight: number
  score_contribution: number
}

export interface RiskDetail {
  village_id: number
  village_name: string
  risk_score: number
  risk_level: 'LOW' | 'MODERATE' | 'HIGH' | 'CRITICAL'
  confidence_pct: number
  lead_time_minutes: number | null
  lead_time_note: string
  glacial_lake_distance_km?: number | null
  glacial_lake_note?: string
  glof_contribution_pct?: number | null
  glof_contribution_tier?: 'LOW' | 'MODERATE' | 'HIGH' | null
  glof_contribution_note?: string
  // Real, independent NRCS TR-55 rainfall-runoff estimate (SCS-CN method,
  // user-requested follow-up) — a SEPARATE figure shown alongside the
  // weighted baseline score, never folded into it. See
  // backend/app/services/scs_cn_runoff.py for every disclosed
  // simplification (default hydrologic condition per land-cover class,
  // soil-moisture-as-AMC-proxy, 1-hour assumed storm duration, lambda=0.20).
  scs_cn_curve_number?: number | null
  scs_cn_amc_class?: 'I' | 'II' | 'III' | null
  scs_cn_hydrologic_soil_group?: 'A' | 'B' | 'C' | 'D' | null
  scs_cn_land_cover?: string | null
  scs_cn_rainfall_depth_mm?: number | null
  scs_cn_runoff_depth_mm?: number | null
  scs_cn_runoff_ratio?: number | null
  scs_cn_note?: string
  // Real, independent rainfall intensity-duration (I-D) landslide-threshold
  // indicator (user-requested follow-up, from this project's own
  // competitive-landscape research) — a THIRD independent figure shown
  // alongside the weighted score and the SCS-CN estimate, never folded into
  // risk_score/risk_level. `rainfall_threshold_applicability` discloses
  // whether this village's region is the study's own Chamoli-Joshimath
  // catchment ('direct_fit') or a regional proxy ('regional_proxy'). See
  // backend/app/services/rainfall_threshold.py.
  rainfall_threshold_hours_to_threshold?: number | null
  rainfall_threshold_status?:
    | 'below_floor'
    | 'threshold_exceeded'
    | 'approaching_within_24h'
    | 'not_indicated_within_24h'
    | null
  rainfall_threshold_applicability?: 'direct_fit' | 'regional_proxy' | null
  rainfall_threshold_note?: string
  // Real, or clearly-labelled simulated, antecedent-precipitation-index
  // (user-requested follow-up, from this project's own competitive-
  // landscape research) — rainfall HISTORY (5/10/20-day sums), used as the
  // AMC-classification input to scs_cn_amc_class above whenever it's real
  // (source === 'real'). See backend/app/services/antecedent_rainfall.py.
  antecedent_rainfall_5day_mm?: number | null
  antecedent_rainfall_10day_mm?: number | null
  antecedent_rainfall_20day_mm?: number | null
  antecedent_rainfall_as_of?: string | null
  antecedent_rainfall_source?: 'real' | 'simulated' | null
  antecedent_rainfall_note?: string
  model_version: string
  drivers: Record<string, RiskDriver> | Record<string, unknown>
  computed_at: string
}

export async function getRiskForVillage(villageId: number, signal?: AbortSignal): Promise<RiskDetail> {
  const res = await fetch(`${API_BASE}/api/v1/risk/${villageId}`, { signal })
  if (!res.ok) throw new ApiError(`GET /risk/${villageId} failed: HTTP ${res.status}`)
  return res.json()
}

export interface DriverExplanation {
  name: string
  plain_language: string
  score_contribution: number
  share_of_score_pct: number
  raw_value: number
  unit: string
  source: string
  detail: string
}

export interface Explanation {
  village_id: number
  village_name: string
  summary: string
  ranked_drivers: DriverExplanation[]
  model_explained: string
  caveat: string
}

export async function getExplanation(villageId: number, signal?: AbortSignal): Promise<Explanation> {
  const res = await fetch(`${API_BASE}/api/v1/model/explanation/${villageId}`, { signal })
  if (!res.ok) throw new ApiError(`GET /model/explanation/${villageId} failed: HTTP ${res.status}`)
  return res.json()
}

export interface Sensor {
  id: number
  external_device_id: string
  village_id: number | null
  village_name: string | null
  sensor_type: 'rainfall' | 'soil_moisture' | 'water_level' | 'tilt'
  status: 'online' | 'stale' | 'offline'
  last_seen_at: string | null
  seconds_since_last_seen: number | null
  battery_pct: number | null
  last_value: number | null
  last_unit: string | null
  last_reading_source: string | null
  /** Device-authentication follow-up (user-requested): true iff this
   * sensor has a real per-device API key on file (sensors.api_key_hash is
   * not NULL) and POST /sensor-reading enforces it for this device. false
   * means the honest pre-migration/not-yet-rotated state — the sensor
   * still works exactly as before, un-authenticated, until
   * scripts/rotate_sensor_api_keys.py gives it a key. Never hidden. */
  authenticated: boolean
  /** Real-regional-data fallback (user-requested follow-up): populated
   * ONLY when this sensor has no live/fresh reading of its own (status
   * isn't 'online') — a REAL Open-Meteo regional weather estimate for this
   * village's coordinates, so the dashboard shows real numbers instead of
   * nothing while no hardware/simulator is reporting. Always
   * fallback_source === 'derived' when set: genuinely real data, but a
   * regional estimate standing in for this device's own reading, never to
   * be shown as if it were `last_value`. Only rainfall/soil_moisture
   * sensors ever get one — Open-Meteo has no water-level or tilt product,
   * so those stay null honestly. */
  fallback_value: number | null
  fallback_unit: string | null
  fallback_source: string | null
}

export async function getSensors(signal?: AbortSignal, regionId?: number | null): Promise<Sensor[]> {
  const qs = regionId != null ? `?region_id=${regionId}` : ''
  const res = await fetch(`${API_BASE}/api/v1/sensors${qs}`, { signal })
  if (!res.ok) throw new ApiError(`GET /sensors failed: HTTP ${res.status}`)
  return res.json()
}

export async function getAlerts(signal?: AbortSignal, regionId?: number | null): Promise<Alert[]> {
  const qs = regionId != null ? `?region_id=${regionId}` : ''
  const res = await fetch(`${API_BASE}/api/v1/alerts${qs}`, { signal })
  if (!res.ok) throw new ApiError(`GET /alerts failed: HTTP ${res.status}`)
  return res.json()
}

// Real-time push follow-up (user-requested): one real alert state change —
// see backend/app/services/alerts_engine.py's AlertTransition — relayed
// verbatim over GET /alerts/stream (Server-Sent Events). `level` is null
// only for a "resolved" event.
export interface AlertTransitionEvent {
  village_id: number
  village_name: string
  event: 'opened' | 'escalated' | 'resolved'
  level: 'YELLOW' | 'ORANGE' | 'RED' | null
  message: string | null
  alert_id: number | null
}

export type AlertStreamStatus = 'connecting' | 'live' | 'offline'

/**
 * Opens GET /alerts/stream and calls `onEvent` for every real alert
 * transition the backend pushes — never a synthetic/scheduled one (SSE
 * comment/heartbeat lines don't fire `onmessage` at all, by the SSE spec,
 * so there's nothing to filter out here). Returns a cleanup function that
 * closes the connection; the browser's EventSource auto-reconnects on a
 * dropped connection on its own, so `onStatusChange` reflects that instead
 * of this function retrying anything itself.
 */
export function subscribeToAlertStream(
  onEvent: (event: AlertTransitionEvent) => void,
  onStatusChange?: (status: AlertStreamStatus) => void,
): () => void {
  // Defensive: EventSource doesn't exist in every environment this code
  // could run in (a test runner's DOM shim, an older browser). Degrading
  // to "no live push" is far better than crashing the whole dashboard.
  if (typeof EventSource === 'undefined') {
    onStatusChange?.('offline')
    return () => {}
  }
  const source = new EventSource(`${API_BASE}/api/v1/alerts/stream`)
  onStatusChange?.('connecting')
  source.onopen = () => onStatusChange?.('live')
  source.onerror = () => onStatusChange?.('offline')
  source.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data) as AlertTransitionEvent)
    } catch {
      // A malformed/unexpected payload is dropped, not thrown — a live
      // push channel degrading to "just don't update live" is far better
      // than it crashing the whole Authority dashboard.
    }
  }
  return () => source.close()
}

// SMS-reach follow-up (user-requested).
export interface SmsSubscriptionResult {
  village_id: number
  phone_number: string
  status: 'subscribed' | 'already_subscribed' | 'unsubscribed' | 'not_subscribed'
}

async function _postSmsSubscription(
  path: 'subscribe' | 'unsubscribe',
  villageId: number,
  phoneNumber: string,
): Promise<SmsSubscriptionResult> {
  const res = await fetch(`${API_BASE}/api/v1/notifications/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ village_id: villageId, phone_number: phoneNumber }),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      // response body wasn't JSON — fall back to the plain status code above
    }
    throw new ApiError(`POST /notifications/${path} failed: ${detail}`)
  }
  return res.json()
}

export function subscribeToSmsAlerts(villageId: number, phoneNumber: string): Promise<SmsSubscriptionResult> {
  return _postSmsSubscription('subscribe', villageId, phoneNumber)
}

export function unsubscribeFromSmsAlerts(villageId: number, phoneNumber: string): Promise<SmsSubscriptionResult> {
  return _postSmsSubscription('unsubscribe', villageId, phoneNumber)
}

export interface EvacuationHop {
  from_village_id: number
  from_village_name: string
  to_village_id: number
  to_village_name: string
  distance_km: number
  unsafe: boolean
  unsafe_reason: string | null
  // Road-network follow-up (user-requested): which calculation actually
  // produced distance_km for this hop.
  distance_source: 'real_road_network' | 'straight_line_proxy'
  road_note: string | null
  // Ordered [lat, lon] points along the real road/trail path, only when
  // distance_source === 'real_road_network'.
  polyline: [number, number][] | null
}

export interface EvacuationRoute {
  origin_village_id: number
  origin_village_name: string
  destination_village_id: number | null
  destination_village_name: string | null
  hops: EvacuationHop[]
  total_distance_km: number
  estimated_minutes: number | null
  note: string
}

export async function getEvacuationRoute(villageId: number, signal?: AbortSignal): Promise<EvacuationRoute> {
  const res = await fetch(`${API_BASE}/api/v1/evacuation/route/${villageId}`, { signal })
  if (!res.ok) throw new ApiError(`GET /evacuation/route/${villageId} failed: HTTP ${res.status}`)
  return res.json()
}

export async function getAllEvacuationRoutes(
  regionId?: number | null,
  signal?: AbortSignal,
): Promise<EvacuationRoute[]> {
  const qs = regionId != null ? `?region_id=${regionId}` : ''
  const res = await fetch(`${API_BASE}/api/v1/evacuation/routes${qs}`, { signal })
  if (!res.ok) throw new ApiError(`GET /evacuation/routes failed: HTTP ${res.status}`)
  return res.json()
}

export interface EvacuationPriorityEntry {
  village_id: number
  village_name: string
  risk_level: string
  risk_score: number
  lead_time_minutes: number | null
  rank: number
}

export async function getEvacuationPriority(
  signal?: AbortSignal,
  regionId?: number | null,
): Promise<EvacuationPriorityEntry[]> {
  const qs = regionId != null ? `?region_id=${regionId}` : ''
  const res = await fetch(`${API_BASE}/api/v1/evacuation/priority${qs}`, { signal })
  if (!res.ok) throw new ApiError(`GET /evacuation/priority failed: HTTP ${res.status}`)
  return res.json()
}

export interface TimelineEntry {
  sequence_order: number
  occurred_at: string | null
  time_precision: 'exact_time' | 'approximate' | 'date_only'
  headline: string
  description: string
  source_citation: string
}

export interface ReplayEvent {
  event_id: number
  village_id: number | null
  village_name: string | null
  event_type: string
  event_date: string
  severity: string | null
  description: string
  source_citation: string
  timeline: TimelineEntry[]
}

export interface ReplayEventSummary {
  event_id: number
  village_id: number | null
  village_name: string | null
  event_type: string
  event_date: string
  severity: string | null
  entry_count: number
}

export async function getReplayEvents(signal?: AbortSignal): Promise<ReplayEventSummary[]> {
  const res = await fetch(`${API_BASE}/api/v1/replay/events`, { signal })
  if (!res.ok) throw new ApiError(`GET /replay/events failed: HTTP ${res.status}`)
  return res.json()
}

export async function getReplayEvent(eventId: number, signal?: AbortSignal): Promise<ReplayEvent> {
  const res = await fetch(`${API_BASE}/api/v1/replay/${eventId}`, { signal })
  if (!res.ok) throw new ApiError(`GET /replay/${eventId} failed: HTTP ${res.status}`)
  return res.json()
}

// What-If Simulator (POST /simulate, problem-statement item 20 — a
// user-requested follow-up built after the original 14-phase plan). This
// overrides one village's rainfall and/or soil-moisture INPUT to the same
// transparent baseline formula GET /risk/{id} uses — there is no separate
// "simulation model," and the call has zero side effects (nothing is
// persisted, no alert is created). See SimulationResult.note, always
// rendered verbatim so the hypothetical-vs-real distinction is never lost.
export interface SimulationRequest {
  village_id: number
  rainfall_mm_hr?: number | null
  soil_moisture_pct?: number | null
}

// Matches app/services/risk_engine.py's Component.to_dict() exactly — a
// different (and more complete) shape than the unused RiskDriver interface
// above, which never matched what the backend actually sends.
export interface SimulationComponent {
  name: string
  description: string
  raw_value: number
  unit: string
  source: 'real' | 'simulated' | 'derived'
  normalized_0_1: number
  weight: number
  score_contribution: number
}

export interface SimulationResult {
  village_id: number
  village_name: string
  is_simulation: boolean
  overrides_applied: Record<string, number>
  baseline_risk_score: number
  baseline_risk_level: 'LOW' | 'MODERATE' | 'HIGH' | 'CRITICAL'
  baseline_confidence_pct: number
  simulated_risk_score: number
  simulated_risk_level: 'LOW' | 'MODERATE' | 'HIGH' | 'CRITICAL'
  simulated_confidence_pct: number
  // SCS-CN rainfall-runoff comparison (user-requested follow-up) — unlike
  // the glacial-lake/glacier-melt fields, this DOES respond to the
  // rainfall/soil-moisture overrides above, so baseline vs simulated can
  // genuinely differ here.
  baseline_scs_cn_curve_number?: number | null
  baseline_scs_cn_runoff_depth_mm?: number | null
  baseline_scs_cn_runoff_ratio?: number | null
  baseline_scs_cn_note?: string
  simulated_scs_cn_curve_number?: number | null
  simulated_scs_cn_runoff_depth_mm?: number | null
  simulated_scs_cn_runoff_ratio?: number | null
  simulated_scs_cn_note?: string
  // Rainfall intensity-duration threshold comparison (user-requested
  // follow-up, from this project's own competitive-landscape research) —
  // also responds to the rainfall override above, unlike the glacial-lake/
  // glacier-melt fields.
  baseline_rainfall_threshold_hours_to_threshold?: number | null
  baseline_rainfall_threshold_status?: string | null
  baseline_rainfall_threshold_note?: string
  simulated_rainfall_threshold_hours_to_threshold?: number | null
  simulated_rainfall_threshold_status?: string | null
  simulated_rainfall_threshold_note?: string
  // Antecedent-precipitation-index (user-requested follow-up) — rainfall
  // HISTORY, not a live reading, so it is a single figure here (not a
  // baseline/simulated pair): it never changes with the rainfall/soil-
  // moisture overrides above. See antecedent_rainfall_note.
  antecedent_rainfall_5day_mm?: number | null
  antecedent_rainfall_source?: 'real' | 'simulated' | null
  antecedent_rainfall_note?: string
  model_version: string
  drivers: { components: SimulationComponent[]; confidence_explanation: string; not_included_yet: string[] }
  note: string
}

export async function runSimulation(payload: SimulationRequest, signal?: AbortSignal): Promise<SimulationResult> {
  const res = await fetch(`${API_BASE}/api/v1/simulate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body?.detail
    throw new ApiError(
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail) && detail[0]?.msg
          ? detail[0].msg
          : `POST /simulate failed: HTTP ${res.status}`,
    )
  }
  return res.json()
}

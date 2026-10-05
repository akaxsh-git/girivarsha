import { useEffect, useState } from 'react'
import { PilotMap } from '../components/PilotMap'
import { CatchmentPanel } from '../components/CatchmentPanel'
import { RiskPanel } from '../components/RiskPanel'
import { SensorPanel } from '../components/SensorPanel'
import { ExplanationPanel } from '../components/ExplanationPanel'
import { EvacuationPanel } from '../components/EvacuationPanel'
import { PriorityPanel } from '../components/PriorityPanel'
import { ReplayPanel } from '../components/ReplayPanel'
import { WhatIfPanel } from '../components/WhatIfPanel'
import {
  IconActivity,
  IconCheckSquare,
  IconClock,
  IconGauge,
  IconHistory,
  IconLayers,
  IconListOrdered,
  IconMap,
  IconMessage,
  IconRadio,
  IconRoute,
  IconSliders,
  IconUsers,
} from '../components/Icons'
import {
  getVillages,
  getCatchments,
  getRiskMap,
  getAlerts,
  getSensors,
  getRegions,
  subscribeToAlertStream,
  type Village,
  type MicroCatchment,
  type RiskMapEntry,
  type Alert,
  type AlertStreamStatus,
  type Sensor,
  type Region,
} from '../lib/api'

const PHASES: { name: string; status: 'done' | 'next' | 'todo' }[] = [
  { name: 'Phase 1 — Project skeleton + repository structure', status: 'done' },
  { name: 'Phase 2 — Database + geospatial pilot data', status: 'done' },
  { name: 'Phase 3 — Map + villages + micro-catchments', status: 'done' },
  { name: 'Phase 4 — Risk engine baseline', status: 'done' },
  { name: 'Phase 5 — ML model (XGBoost / Random Forest)', status: 'done' },
  { name: 'Phase 6-7 — API integration + dashboards', status: 'done' },
  { name: 'Phase 8 — IoT integration (real MQTT pipeline, simulated hardware)', status: 'done' },
  { name: 'Phase 9-10 — Explainability + lead-time estimation + real weather providers (opt-in)', status: 'done' },
  { name: 'Phase 11 — Region registry + second real pilot valley (Chamoli)', status: 'done' },
  { name: 'Phase 12 — Evacuation routing + historical replay', status: 'done' },
  { name: 'Phase 13 — Failure/fallback testing', status: 'done' },
  { name: 'Phase 14 — Demo polish', status: 'done' },
  { name: 'Sensor network wired into the risk engine (user-requested follow-up)', status: 'done' },
  { name: 'What-If Simulator (user-requested follow-up)', status: 'done' },
]

/**
 * The "authority" dashboard — the full-detail operational view for district
 * officials / disaster-management cell staff: raw scores, confidence
 * percentages, per-village driver data, catchment topology, build status.
 * This is the same content the single shared homepage showed through
 * Phase 5; Phase 6-7 just gave it its own route and added CitizenView as a
 * separate, simplified entry point for the public (see App.tsx).
 */
export function AuthorityView() {
  const [regions, setRegions] = useState<Region[] | null>(null)
  const [regionsError, setRegionsError] = useState(false)
  // null = "All regions" — the pre-Phase-11 default, unchanged for anyone
  // who never touches the selector. PilotMap's per-catchment line grouping
  // (see components/PilotMap.tsx) is what makes "All regions" safe to show
  // on the map even with two+ unrelated valleys' villages on screen at once.
  const [selectedRegionId, setSelectedRegionId] = useState<number | null>(null)

  const [villages, setVillages] = useState<Village[] | null>(null)
  const [villagesError, setVillagesError] = useState(false)
  const [catchments, setCatchments] = useState<MicroCatchment[] | null>(null)
  const [catchmentsError, setCatchmentsError] = useState(false)
  const [riskMap, setRiskMap] = useState<RiskMapEntry[] | null>(null)
  const [riskError, setRiskError] = useState(false)
  const [alerts, setAlerts] = useState<Alert[] | null>(null)
  const [alertsError, setAlertsError] = useState(false)
  const [liveStatus, setLiveStatus] = useState<AlertStreamStatus>('connecting')
  const [sensors, setSensors] = useState<Sensor[] | null>(null)
  const [sensorsError, setSensorsError] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    getRegions(controller.signal)
      .then((r) => {
        setRegions(r)
        setRegionsError(false)
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setRegionsError(true)
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    getVillages(controller.signal, selectedRegionId)
      .then((v) => {
        setVillages(v)
        setVillagesError(false)
      })
      .catch((err: unknown) => {
        // React 18 StrictMode double-invokes effects in dev, which aborts the
        // first request by design — that's not a real failure, so don't show
        // "unreachable" for it. Only a genuine fetch failure sets the error.
        if (err instanceof DOMException && err.name === 'AbortError') return
        setVillagesError(true)
      })
    return () => controller.abort()
  }, [selectedRegionId])

  useEffect(() => {
    const controller = new AbortController()
    getCatchments(controller.signal, selectedRegionId)
      .then((c) => {
        setCatchments(c)
        setCatchmentsError(false)
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setCatchmentsError(true)
      })
    return () => controller.abort()
  }, [selectedRegionId])

  useEffect(() => {
    const controller = new AbortController()
    const isAbort = (err: unknown) => err instanceof DOMException && err.name === 'AbortError'

    // GET /risk/map is what computes+persists the baseline scores AND syncs
    // alerts from them (there's no background scheduler yet — Phase 8+), so
    // alerts are fetched only after risk scores succeed — matching how the
    // backend actually works, not assuming alerts exist independently. Each
    // call's error is tracked separately so a failure in one doesn't
    // wrongly mark the other as unreachable.
    ;(async () => {
      try {
        const r = await getRiskMap(controller.signal, selectedRegionId)
        setRiskMap(r)
        setRiskError(false)
      } catch (err) {
        if (isAbort(err)) return
        setRiskError(true)
        return
      }
      try {
        const a = await getAlerts(controller.signal, selectedRegionId)
        setAlerts(a)
        setAlertsError(false)
      } catch (err) {
        if (isAbort(err)) return
        setAlertsError(true)
      }
    })()

    return () => controller.abort()
  }, [selectedRegionId])

  // Real-time push follow-up (user-requested): GET /alerts/stream (SSE)
  // pushes every real alert open/escalation/resolution the instant a
  // /risk/map or /risk/{id} call anywhere produces one, instead of only
  // finding out on this view's next own risk-fetch. Applied as a targeted
  // in-place update to `alerts` (not a full re-fetch) so a pushed event
  // can't clobber the region-scoped fetch above with an unscoped result.
  useEffect(() => {
    const unsubscribe = subscribeToAlertStream(
      (event) => {
        setAlerts((prev) => {
          const withoutThisVillage = (prev ?? []).filter((a) => a.village_id !== event.village_id)
          if (event.event === 'resolved' || event.level === null) {
            return withoutThisVillage
          }
          const pushedAlert: Alert = {
            id: event.alert_id ?? -Date.now(),
            village_id: event.village_id,
            village_name: event.village_name,
            level: event.level,
            message: event.message ?? '',
            risk_score: null,
            issued_at: new Date().toISOString(),
            resolved_at: null,
          }
          return [pushedAlert, ...withoutThisVillage]
        })
      },
      (status) => setLiveStatus(status),
    )
    return unsubscribe
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    getSensors(controller.signal, selectedRegionId)
      .then((s) => {
        setSensors(s)
        setSensorsError(false)
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setSensorsError(true)
      })
    return () => controller.abort()
  }, [selectedRegionId])

  // Server-side region filtering follow-up (user-requested): GET /sensors
  // and GET /alerts now both accept `?region_id=` directly (same real
  // Sensor/Alert -> Village -> MicroCatchment -> Region join /villages and
  // /risk/map already use), so `sensors`/`alerts` above are already scoped
  // to whichever region is selected — no client-side re-filtering needed
  // any more. Picking "Chamoli Disaster Valley" (which has no sensors
  // seeded) still honestly shows 0/0, now because the backend itself
  // returned zero rows, not because the frontend filtered a bigger list
  // down. Kept as local aliases so the rest of this component (and its
  // existing tests) doesn't need to change.
  const scopedSensors = sensors
  const scopedAlerts = alerts

  const sensorsOnlineLabel = sensorsError
    ? '—'
    : scopedSensors
      ? `${scopedSensors.filter((s) => s.status === 'online').length}/${scopedSensors.length}`
      : '…'

  // Phase 10: /risk/map now carries each village's lead_time_minutes, so
  // this is a real average over whichever villages actually have an
  // upstream point to estimate from — never a fabricated number, and
  // honestly '—' (not '0') if none do.
  const leadTimeValues = (riskMap ?? [])
    .map((r) => r.lead_time_minutes)
    .filter((m): m is number => m !== null)
  const avgLeadTimeLabel =
    riskError ? '—' : riskMap === null ? '…' : leadTimeValues.length === 0 ? '—' : `${Math.round(leadTimeValues.reduce((a, b) => a + b, 0) / leadTimeValues.length)} min`

  const activeRegions = (regions ?? []).filter((r) => r.status === 'active')
  const plannedRegions = (regions ?? []).filter((r) => r.status === 'planned')
  const selectedRegionLabel =
    selectedRegionId === null
      ? 'all regions'
      : (regions?.find((r) => r.id === selectedRegionId)?.name ?? 'the selected region')

  return (
    <main>
      <div className="section">
        <h2><IconLayers /> Pilot overview</h2>
        <p>
          "Villages monitored", "Sensors online" and "Avg. lead time" are all real, live-computed
          numbers — from the database (Phase 2), the real MQTT sensor pipeline (Phase 8), and the
          Phase 10 lead-time prototype (straight-line distance / assumed flow velocity — see the
          "Explain this score" panel below) — scoped to <strong>{selectedRegionLabel}</strong>.
          Nothing here is a fabricated placeholder.
        </p>
        <div className="section region-picker">
          <label htmlFor="region-select">Region</label>
          {regionsError ? (
            <p className="catchment-empty">Region list unreachable — backend/DB may be down.</p>
          ) : (
            <select
              id="region-select"
              value={selectedRegionId ?? 'all'}
              onChange={(e) => setSelectedRegionId(e.target.value === 'all' ? null : Number(e.target.value))}
              disabled={regions === null}
            >
              <option value="all">All regions{regions ? ` (${activeRegions.length} sourced)` : ''}</option>
              {activeRegions.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} — {r.states} ({r.village_count} villages)
                </option>
              ))}
              {plannedRegions.length > 0 && (
                <optgroup label="Planned — real, documented, not yet village-sourced">
                  {plannedRegions.map((r) => (
                    <option key={r.id} value={r.id} disabled>
                      {r.name} — {r.states} (not yet sourced)
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          )}
          <p className="n">
            Phase 11's region registry (see <code>docs/Region_Onboarding.md</code>) — "active" regions
            have real village-level data seeded now; "planned" regions are real, cited flash-flood-prone
            valleys the architecture already supports but that haven't been sourced to village level yet.
          </p>
        </div>
        <div className="stat-row">
          <div className="stat-card">
            <div className="v">
              {villagesError ? '—' : villages ? villages.length : '…'}
            </div>
            <div className="l"><IconUsers size={14} /> Villages monitored</div>
            <div className="n">
              {villagesError ? 'backend/DB unreachable' : 'live from /api/v1/villages'}
            </div>
          </div>
          <div className="stat-card">
            <div className="v">{sensorsOnlineLabel}</div>
            <div className="l"><IconActivity size={14} /> Sensors online</div>
            <div className="n">
              {sensorsError ? 'backend/DB unreachable' : 'live from /api/v1/sensors'}
            </div>
          </div>
          <div className="stat-card">
            <div className="v">{avgLeadTimeLabel}</div>
            <div className="l"><IconClock size={14} /> Avg. lead time</div>
            <div className="n">
              {riskError
                ? 'backend/DB unreachable'
                : leadTimeValues.length === 0 && riskMap !== null
                  ? 'no village has an upstream point yet'
                  : 'Phase 10 prototype — see below'}
            </div>
          </div>
        </div>
      </div>

      <div className="section">
        <h2><IconMap /> Pilot region map</h2>
        <p>
          Real village points from the database — green markers have surveyed coordinates,
          amber markers are honestly labelled approximate (see <code>docs/Data_Sources.md</code>).
          Catchment polygon boundaries need a real DEM run through <code>gis/delineate_catchment.py</code>
          (see <code>docs/GIS_Methodology.md</code>) — the panel below reports the true current state,
          not a fixed claim either way.
        </p>
        <PilotMap villages={villages ?? []} />
      </div>

      <div className="section">
        <h2><IconLayers /> Micro-catchment topology</h2>
        <p>
          Upstream → downstream structure, from documented river-order research — not per-village
          isolated risk. Real today; polygon boundaries pending real GIS delineation.
        </p>
        <CatchmentPanel catchments={catchments} error={catchmentsError} />
      </div>

      <div className="section">
        <h2><IconGauge /> Current risk (baseline)</h2>
        <p>
          Phase 4's transparent weighted-sum scorer — every score below is computed live from
          the formula in <code>backend/app/services/risk_engine.py</code>. Rainfall/soil-moisture
          are simulated by default; set <code>GIRIVARSHA_ACTIVE_RAINFALL_PROVIDER=real</code> /
          <code>GIRIVARSHA_ACTIVE_SOIL_PROVIDER=real</code> in <code>backend/.env</code> to switch
          to live Open-Meteo data (free, no API key) — see the README's "Real weather data"
          section. Confidence is shown next to every score and reflects whichever mix is actually
          active, never a fixed claim either way.
        </p>
        <RiskPanel
          riskMap={riskMap}
          riskError={riskError}
          alerts={scopedAlerts}
          alertsError={alertsError}
          liveStatus={liveStatus}
        />
      </div>

      <div className="section">
        <h2><IconMessage /> Explain this score</h2>
        <p>
          Phase 9 — a real model-agnostic "why" narrative: ranks and narrates the baseline's own
          transparent components (the same ones the risk panel above sums), in plain language.
          This explains the model that's actually running, not a fabricated SHAP explanation of
          the undeployed Phase 5 ML layer — see <code>docs/ML_Methodology.md</code>.
        </p>
        <ExplanationPanel villages={villages} />
      </div>

      <div className="section">
        <h2><IconRadio /> Sensor network</h2>
        <p>
          Phase 8's real registry — 3 pilot locations (source, mid-valley, outlet) in the Mandakini
          valley, a rainfall + soil-moisture node each. Status is live-computed from freshness, never
          a stored flag. No hardware has been deployed to the Chamoli valley yet, so selecting it
          above honestly shows 0/0 here rather than any Mandakini reading.
        </p>
        <SensorPanel sensors={scopedSensors} error={sensorsError} />
      </div>

      <div className="section">
        <h2><IconRoute /> Evacuation routing</h2>
        <p>
          Phase 12 prototype — a real shortest-path search (networkx) over each catchment's real
          village topology to its real, lowest-elevation seeded settlement (never a fabricated
          "shelter" building). No real road network exists in this build (this sandbox's network
          couldn't reach OpenStreetMap/OSRM — see <code>docs/Data_Sources.md</code>), so hops follow
          the same elevation-order proxy the map's dashed line and the lead-time estimate already
          use — not real road/trail geometry. A hop is flagged when either endpoint is currently at
          HIGH/CRITICAL risk — a derived heuristic, not real road-hazard data.
        </p>
        <EvacuationPanel villages={villages} regionId={selectedRegionId} />
      </div>

      <div className="section">
        <h2><IconListOrdered /> Evacuation priority</h2>
        <p>
          A transparent ranking, not an evacuation order — decision-support only. Sorted by current
          risk level severity, then by less warning time (Phase 10 lead-time estimate), then by risk
          score. Every input here is already real/derived elsewhere in this app; this just orders
          them, never invents a new composite score.
        </p>
        <PriorityPanel regionId={selectedRegionId} />
      </div>

      <div className="section">
        <h2><IconSliders /> What-if simulator</h2>
        <p>
          A presenter-controllable scenario, not a separate demo model — overriding rainfall and/or
          soil saturation here recomputes the exact same transparent baseline formula shown above
          (<code>backend/app/services/risk_engine.py</code>), live. Nothing run here is persisted or
          fed into <code>/alerts</code>; it exists purely so a walkthrough can show what a higher-risk
          moment would look like without waiting for real weather to cooperate. See{' '}
          <code>docs/Demo_Guide.md</code>.
        </p>
        <WhatIfPanel villages={villages} />
      </div>

      <div className="section">
        <h2><IconHistory /> Historical event replay</h2>
        <p>
          Phase 12 — real, cited sub-events from the two seeded historical disasters, steppable in
          order. There is deliberately no fabricated minute-by-minute reconstruction: each moment
          below is labelled by exactly how precisely it's documented (an exact cited clock time, an
          estimate derived from one, or just the date) — see{' '}
          <code>scripts/seed_event_timelines.py</code>.
        </p>
        <ReplayPanel />
      </div>

      <div className="section">
        <h2><IconCheckSquare /> Build status</h2>
        <p>Following the incremental build order — each phase is implemented, tested and reported before the next begins.</p>
        <ul className="phase-list">
          {PHASES.map((p) => (
            <li key={p.name}>
              <span className={`badge ${p.status}`}>{p.status}</span>
              {p.name}
            </li>
          ))}
        </ul>
      </div>
    </main>
  )
}

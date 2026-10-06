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
import { Card } from '../components/Card'
import { AlertsList, LiveBadge } from '../components/RiskPanel'
import {
  IconActivity,
  IconShield,
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

/**
 * The authority dashboard — the operational view for district officials /
 * disaster-management staff: scores, confidence, drivers, sensors,
 * evacuation and scenarios. Each card keeps its methodology and limits in a
 * collapsed "How this works" section (components/Card.tsx).
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

  // No device has ever reported => no hardware is deployed yet. Say that,
  // rather than a bare "0/12 online" that reads like an outage.
  const noneDeployed =
    !!scopedSensors && scopedSensors.length > 0 && scopedSensors.every((s) => s.seconds_since_last_seen === null)

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

  const openAlertCount = alertsError ? null : scopedAlerts ? scopedAlerts.length : undefined
  const topRisk = riskMap && riskMap.length > 0 ? [...riskMap].sort((a, b) => b.risk_score - a.risk_score)[0] : null

  const NAV = [
    ['overview', 'Overview'],
    ['risk', 'Risk'],
    ['sensors', 'Sensors'],
    ['evacuation', 'Evacuation'],
    ['scenarios', 'Scenarios'],
    ['history', 'History'],
  ] as const

  return (
    <main className="dash">
      <div className="page-head">
        <div>
          <h1 className="page-title">Operations dashboard</h1>
          <p className="page-sub">
            Live flash-flood and landslide risk for monitored Himalayan villages — showing{' '}
            <strong>{selectedRegionLabel}</strong>. Decision support only.
          </p>
        </div>
        <div className="region-picker">
          <label htmlFor="region-select">Region</label>
          {regionsError ? (
            <p className="catchment-empty">Region list unreachable right now.</p>
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
                <optgroup label="Planned — documented, not yet village-sourced">
                  {plannedRegions.map((r) => (
                    <option key={r.id} value={r.id} disabled>
                      {r.name} — {r.states} (not yet sourced)
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          )}
        </div>
      </div>

      <div className="stat-row">
        <div className="stat-card">
          <div className="l"><IconUsers size={14} /> Villages monitored</div>
          <div className="v">{villagesError ? '—' : villages ? villages.length : '…'}</div>
          <div className="n">{villagesError ? 'unreachable' : 'in the selected region'}</div>
        </div>
        <div className={`stat-card${openAlertCount ? ' stat-card-alert' : ''}`}>
          <div className="l"><IconShield size={14} /> Open alerts</div>
          <div className="v">{openAlertCount === null ? '—' : openAlertCount === undefined ? '…' : openAlertCount}</div>
          <div className="n">{openAlertCount === 0 ? 'all villages LOW/GREEN' : 'yellow, orange or red'}</div>
        </div>
        <div className="stat-card">
          <div className="l"><IconGauge size={14} /> Highest risk</div>
          <div className="v">{riskError ? '—' : topRisk ? topRisk.risk_score.toFixed(0) : riskMap === null ? '…' : '—'}</div>
          <div className="n">{topRisk ? `${topRisk.village_name} · ${topRisk.risk_level}` : 'score out of 100'}</div>
        </div>
        <div className="stat-card">
          <div className="l"><IconActivity size={14} /> {noneDeployed ? 'Field sensors' : 'Sensors online'}</div>
          <div className="v">{noneDeployed ? 'None yet' : sensorsOnlineLabel}</div>
          <div className="n">
            {sensorsError
              ? 'unreachable'
              : noneDeployed
                ? `none deployed yet (${scopedSensors!.length} sites planned)`
                : 'reporting in the last few minutes'}
          </div>
        </div>
        <div className="stat-card">
          <div className="l"><IconClock size={14} /> Avg. lead time</div>
          <div className="v">{avgLeadTimeLabel}</div>
          <div className="n">
            {riskError
              ? 'unreachable'
              : leadTimeValues.length === 0 && riskMap !== null
                ? 'no village has an upstream point yet'
                : 'prototype estimate'}
          </div>
        </div>
      </div>

      <nav className="section-nav" aria-label="Dashboard sections">
        {NAV.map(([id, label]) => (
          <a key={id} href={`#${id}`}>{label}</a>
        ))}
      </nav>

      <div className="dash-grid" id="overview">
        <Card
          id="map"
          className="span-8"
          icon={<IconMap />}
          title="Region map"
          summary="Monitored villages. Green = surveyed coordinates, amber = approximate."
          howItWorks={
            <>
              <p>
                Village points come straight from the database. Approximate coordinates are labelled as such
                rather than presented as surveyed. The dashed line only connects villages in elevation order
                within each catchment — it is not the river's real course.
              </p>
              <p>
                The optional wind layer shows real Open-Meteo 10 m wind on a coarse grid. It is regional
                context only and is not used by the risk model.
              </p>
            </>
          }
        >
          <PilotMap villages={villages ?? []} />
        </Card>

        <div className="span-4 stack">
          <Card
            id="alerts"
            icon={<IconShield />}
            title="Active alerts"
            actions={<LiveBadge status={liveStatus} />}
            summary="Updates instantly when any village's level changes."
          >
            <AlertsList alerts={scopedAlerts} alertsError={alertsError} />
          </Card>
          <Card
            id="catchments"
            icon={<IconLayers />}
            title="Catchments"
            summary="How villages connect upstream to downstream."
            howItWorks={
              <p>
                Upstream → downstream order comes from documented river-order research, so a village's risk can
                reflect rain falling above it. Mapped boundary polygons are shown only where a real terrain
                delineation exists.
              </p>
            }
          >
            <CatchmentPanel catchments={catchments} error={catchmentsError} />
          </Card>
        </div>

        <Card
          id="risk"
          className="span-7"
          icon={<IconGauge />}
          title="Current risk"
          summary="Every village, highest risk first. Confidence shows how much of the input is real data."
          howItWorks={
            <>
              <p>
                Each score is a transparent weighted sum of five inputs: current rainfall, soil saturation,
                rainfall upstream in the same catchment, past recorded events, and the melt rate of the nearest
                glacier. Rainfall and soil moisture come from Open-Meteo (refreshed hourly); recent rainfall
                history comes from NASA POWER.
              </p>
              <p>
                Confidence reflects how many inputs are real rather than simulated — it is not a measure of
                validated accuracy. A machine-learning model was trained and tested but is not deployed: there
                are too few recorded events to validate it. The extra indicators under each village (runoff,
                rainfall threshold, glacial hazard) are independent estimates shown alongside the score, never
                folded into it.
              </p>
            </>
          }
        >
          <RiskPanel
            riskMap={riskMap}
            riskError={riskError}
            alerts={scopedAlerts}
            alertsError={alertsError}
            liveStatus={liveStatus}
            showAlerts={false}
          />
        </Card>

        <Card
          id="explain"
          className="span-5"
          icon={<IconMessage />}
          title="Why this score?"
          summary="What is driving a village's score right now, in plain language."
          howItWorks={
            <p>
              This ranks the five inputs of the formula that is actually running by their share of the score. It
              explains that formula directly — it is not an attribution over the undeployed ML model.
            </p>
          }
        >
          <ExplanationPanel villages={villages} />
        </Card>

        <Card
          id="sensors"
          className="span-12"
          icon={<IconRadio />}
          title="Sensor network"
          summary={noneDeployed ? "Planned rain-gauge and soil-moisture sites. No hardware is deployed yet, so each shows its area's regional weather estimate." : "Field rain gauges and soil-moisture probes. Offline nodes show a labelled regional estimate instead."}
          howItWorks={
            <>
              <p>
                Status is computed from how recently each node reported. Readings travel over MQTT to an
                authenticated ingestion API; each device has its own key.
              </p>
              <p>
                No physical hardware is deployed yet, so nodes are currently offline. Where a node has no reading,
                its village's real Open-Meteo estimate is shown in italics as "regional est." — that is weather
                data for the area, not that device's own measurement.
              </p>
            </>
          }
        >
          <SensorPanel sensors={scopedSensors} error={sensorsError} />
        </Card>

        <Card
          id="evacuation"
          className="span-8"
          icon={<IconRoute />}
          title="Evacuation routes"
          summary="Shortest route from each village to the lowest, safest settlement in its valley."
          howItWorks={
            <p>
              Routes are computed over each catchment's villages, using real OpenStreetMap roads and trails where
              they connect and a straight-line estimate where they don't. A leg is flagged when either end is
              currently at HIGH or CRITICAL risk — a heuristic, not live road-condition data. Destinations are
              real settlements, not designated shelters.
            </p>
          }
        >
          <EvacuationPanel villages={villages} regionId={selectedRegionId} />
        </Card>

        <Card
          id="priority"
          className="span-4"
          icon={<IconListOrdered />}
          title="Evacuation priority"
          summary="Which villages to attend to first. Not an evacuation order."
          howItWorks={
            <p>
              Sorted by risk level, then by least warning time, then by score. It only orders inputs already shown
              elsewhere — it does not create a new score.
            </p>
          }
        >
          <PriorityPanel regionId={selectedRegionId} />
        </Card>

        <Card
          id="scenarios"
          className="span-6"
          icon={<IconSliders />}
          title="What-if simulator"
          summary="Try heavier rain or wetter ground and see how a village's score would change."
          howItWorks={
            <p>
              Overrides run through the exact same formula as the live scores. Nothing here is saved or turned into
              an alert.
            </p>
          }
        >
          <WhatIfPanel villages={villages} />
        </Card>

        <Card
          id="history"
          className="span-6"
          icon={<IconHistory />}
          title="Historical replay"
          summary="Step through past disasters in this region, moment by moment."
          howItWorks={
            <p>
              Each step is a cited event from the public record, labelled by how precisely its time is known: an
              exact time, an estimate, or the date only. Nothing is reconstructed or invented.
            </p>
          }
        >
          <ReplayPanel />
        </Card>
      </div>
    </main>
  )
}

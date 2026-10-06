import { useEffect, useState } from 'react'
import { runSimulation, type SimulationResult, type Village } from '../lib/api'

interface WhatIfPanelProps {
  villages: Village[] | null
}

const LEVEL_CLASS: Record<string, string> = {
  LOW: 'risk-low',
  MODERATE: 'risk-moderate',
  HIGH: 'risk-high',
  CRITICAL: 'risk-critical',
}

const RAINFALL_MAX = 100
const SOIL_MAX = 100

// Plain-language labels for rainfall_threshold_status (see
// backend/app/services/rainfall_threshold.py).
const RAINFALL_THRESHOLD_LABEL: Record<string, string> = {
  below_floor: 'below study floor',
  threshold_exceeded: 'threshold exceeded',
  approaching_within_24h: 'approaching within 24h',
  not_indicated_within_24h: 'not indicated within 24h',
  not_applicable: 'not calibrated for this region',
}

function rainfallThresholdSummary(status: string | null | undefined, hours: number | null | undefined): string {
  if (!status) return 'n/a'
  const label = RAINFALL_THRESHOLD_LABEL[status] ?? status
  return hours != null ? `${label} (~${hours.toFixed(1)}h)` : label
}

/**
 * The What-If Simulator (POST /simulate, problem-statement item 20) — a
 * user-requested follow-up built after the original 14-phase plan was
 * complete, closing the one gap the Phase 14 demo-polish pass found between
 * the original walkthrough script (docs/Product_Positioning.md) and what was
 * actually built. A presenter drags rainfall/soil-moisture sliders for one village
 * and sees the SAME transparent baseline formula (app/services/
 * risk_engine.py) respond in real time — there is no separate "demo mode"
 * model, and nothing here is persisted or fed into /alerts (see the note
 * field, always rendered verbatim from the backend rather than
 * paraphrased, same discipline as ExplanationPanel's caveat text).
 */
export function WhatIfPanel({ villages }: WhatIfPanelProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [rainfallEnabled, setRainfallEnabled] = useState(true)
  const [soilEnabled, setSoilEnabled] = useState(true)
  const [rainfall, setRainfall] = useState(30)
  const [soil, setSoil] = useState(70)
  const [result, setResult] = useState<SimulationResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (selectedId === null && villages && villages.length > 0) {
      setSelectedId(villages[0].id)
    }
  }, [villages, selectedId])

  useEffect(() => {
    setResult(null)
    setError(null)
  }, [selectedId])

  if (!villages || villages.length === 0) {
    return <p className="catchment-empty">Waiting for village list…</p>
  }

  const canRun = selectedId !== null && (rainfallEnabled || soilEnabled)

  async function run() {
    if (selectedId === null) return
    setLoading(true)
    setError(null)
    try {
      const r = await runSimulation({
        village_id: selectedId,
        rainfall_mm_hr: rainfallEnabled ? rainfall : null,
        soil_moisture_pct: soilEnabled ? soil : null,
      })
      setResult(r)
    } catch (err) {
      const message = err instanceof Error && err.message ? err.message : ''
      setError(message || 'POST /simulate unreachable — backend/DB may be down.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="whatif-panel">
      <label htmlFor="whatif-village-select">Simulate a scenario for</label>
      <select
        id="whatif-village-select"
        value={selectedId ?? ''}
        onChange={(e) => setSelectedId(Number(e.target.value))}
      >
        {villages.map((v) => (
          <option key={v.id} value={v.id}>
            {v.name}
          </option>
        ))}
      </select>

      <div className="whatif-controls">
        <div className="whatif-control-row">
          <label className="whatif-toggle">
            <input
              type="checkbox"
              checked={rainfallEnabled}
              onChange={(e) => setRainfallEnabled(e.target.checked)}
            />
            Override rainfall
          </label>
          <input
            type="range"
            min={0}
            max={RAINFALL_MAX}
            step={0.5}
            value={rainfall}
            disabled={!rainfallEnabled}
            onChange={(e) => setRainfall(Number(e.target.value))}
          />
          <span className="whatif-value">{rainfall.toFixed(1)} mm/hr</span>
        </div>

        <div className="whatif-control-row">
          <label className="whatif-toggle">
            <input type="checkbox" checked={soilEnabled} onChange={(e) => setSoilEnabled(e.target.checked)} />
            Override soil saturation
          </label>
          <input
            type="range"
            min={0}
            max={SOIL_MAX}
            step={1}
            value={soil}
            disabled={!soilEnabled}
            onChange={(e) => setSoil(Number(e.target.value))}
          />
          <span className="whatif-value">{soil.toFixed(0)}%</span>
        </div>

        <button type="button" className="whatif-run-button" onClick={run} disabled={!canRun || loading}>
          {loading ? 'Running…' : 'Run what-if scenario'}
        </button>
        {!rainfallEnabled && !soilEnabled && (
          <p className="n">Enable at least one override to run a scenario.</p>
        )}
      </div>

      {error && <p className="catchment-empty">{error}</p>}

      {result && (
        <div className="whatif-result">
          <div className="whatif-compare">
            <div className="whatif-compare-col">
              <div className="whatif-compare-label">Real current assessment</div>
              <span className={`risk-badge ${LEVEL_CLASS[result.baseline_risk_level] ?? ''}`}>
                {result.baseline_risk_level}
              </span>
              <div className="whatif-compare-score">{result.baseline_risk_score.toFixed(1)}</div>
              <div className="n">{result.baseline_confidence_pct.toFixed(0)}% confidence</div>
            </div>
            <div className="whatif-compare-arrow">→</div>
            <div className="whatif-compare-col">
              <div className="whatif-compare-label">Hypothetical (what-if)</div>
              <span className={`risk-badge ${LEVEL_CLASS[result.simulated_risk_level] ?? ''}`}>
                {result.simulated_risk_level}
              </span>
              <div className="whatif-compare-score">{result.simulated_risk_score.toFixed(1)}</div>
              <div className="n">{result.simulated_confidence_pct.toFixed(0)}% confidence</div>
            </div>
          </div>

          <ul className="whatif-components">
            {result.drivers.components.map((c) => (
              <li key={c.name} className="whatif-component-row">
                <span className="whatif-component-name">{c.name.replace(/_/g, ' ')}</span>
                <span className={`explanation-driver-source src-${c.source}`}>{c.source}</span>
                <span className="whatif-component-value">
                  {c.raw_value} {c.unit}
                </span>
                <span className="n whatif-component-desc">{c.description}</span>
              </li>
            ))}
          </ul>

          {result.simulated_scs_cn_runoff_depth_mm != null && (
            <div className="whatif-scs-cn">
              <div className="whatif-compare-label">
                SCS-CN rainfall-runoff estimate (real, independent — not folded into the score above)
              </div>
              <div className="whatif-compare">
                <div className="whatif-compare-col">
                  <div className="n">Real current</div>
                  <div className="whatif-compare-score">
                    {result.baseline_scs_cn_runoff_depth_mm != null
                      ? `${result.baseline_scs_cn_runoff_depth_mm.toFixed(1)} mm`
                      : 'n/a'}
                  </div>
                  {result.baseline_scs_cn_curve_number != null && (
                    <div className="n">CN {result.baseline_scs_cn_curve_number.toFixed(0)}</div>
                  )}
                </div>
                <div className="whatif-compare-arrow">→</div>
                <div className="whatif-compare-col">
                  <div className="n">Hypothetical</div>
                  <div className="whatif-compare-score">{result.simulated_scs_cn_runoff_depth_mm.toFixed(1)} mm</div>
                  {result.simulated_scs_cn_curve_number != null && (
                    <div className="n">CN {result.simulated_scs_cn_curve_number.toFixed(0)}</div>
                  )}
                </div>
              </div>
              <p className="n whatif-component-desc">{result.simulated_scs_cn_note}</p>
            </div>
          )}

          {result.simulated_rainfall_threshold_status != null && (
            <div className="whatif-rainfall-threshold">
              <div className="whatif-compare-label">
                Rainfall intensity-duration threshold (real, independent — not folded into the score above)
              </div>
              <div className="whatif-compare">
                <div className="whatif-compare-col">
                  <div className="n">Real current</div>
                  <div className="whatif-compare-score">
                    {rainfallThresholdSummary(
                      result.baseline_rainfall_threshold_status,
                      result.baseline_rainfall_threshold_hours_to_threshold,
                    )}
                  </div>
                </div>
                <div className="whatif-compare-arrow">→</div>
                <div className="whatif-compare-col">
                  <div className="n">Hypothetical</div>
                  <div className="whatif-compare-score">
                    {rainfallThresholdSummary(
                      result.simulated_rainfall_threshold_status,
                      result.simulated_rainfall_threshold_hours_to_threshold,
                    )}
                  </div>
                </div>
              </div>
              <p className="n whatif-component-desc">{result.simulated_rainfall_threshold_note}</p>
            </div>
          )}

          {result.antecedent_rainfall_5day_mm != null && (
            <div className="whatif-antecedent-rainfall">
              <div className="whatif-compare-label">
                Antecedent precipitation index (rainfall history — unaffected by the overrides above)
              </div>
              <div className="whatif-compare-score">
                {result.antecedent_rainfall_5day_mm.toFixed(1)} mm over 5 days
                {result.antecedent_rainfall_source === 'simulated' && ' (simulated)'}
              </div>
              <p className="n whatif-component-desc">{result.antecedent_rainfall_note}</p>
            </div>
          )}

          <p className="whatif-note">{result.note}</p>
        </div>
      )}
    </div>
  )
}

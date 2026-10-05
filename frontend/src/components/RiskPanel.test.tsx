import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RiskPanel } from './RiskPanel'
import type { Alert, RiskMapEntry } from '../lib/api'

const sampleRisk: RiskMapEntry[] = [
  {
    village_id: 1,
    village_name: 'Kedarnath',
    risk_score: 62.3,
    risk_level: 'HIGH',
    confidence_pct: 39.5,
    lead_time_minutes: null,
    glacial_lake_distance_km: 5.56,
    glof_contribution_pct: 71.2,
    glof_contribution_tier: 'HIGH',
    scs_cn_runoff_depth_mm: 24.7,
    scs_cn_curve_number: 79,
    rainfall_threshold_hours_to_threshold: 3.2,
    rainfall_threshold_status: 'approaching_within_24h',
    antecedent_rainfall_5day_mm: 18.4,
    antecedent_rainfall_source: 'simulated',
  },
  { village_id: 2, village_name: 'Rudraprayag', risk_score: 12.1, risk_level: 'LOW', confidence_pct: 39.5, lead_time_minutes: 95 },
]

const sampleAlert: Alert = {
  id: 1,
  village_id: 1,
  village_name: 'Kedarnath',
  level: 'ORANGE',
  message: 'High risk indicators — heightened caution advised. Prototype baseline signal, not an official warning.',
  risk_score: 62.3,
  issued_at: '2026-09-03T00:00:00Z',
  resolved_at: null,
}

describe('RiskPanel', () => {
  it('shows loading states rather than blank panels while data is in flight', () => {
    render(<RiskPanel riskMap={null} riskError={false} alerts={null} alertsError={false} />)
    expect(screen.getByText(/computing baseline risk scores/i)).toBeInTheDocument()
    expect(screen.getByText(/loading alerts/i)).toBeInTheDocument()
  })

  it('shows honest error states on failure', () => {
    render(<RiskPanel riskMap={null} riskError={true} alerts={null} alertsError={true} />)
    expect(screen.getAllByText(/unreachable/i).length).toBeGreaterThan(0)
  })

  it('renders no live-status badge when liveStatus is not passed', () => {
    render(<RiskPanel riskMap={sampleRisk} riskError={false} alerts={[]} alertsError={false} />)
    expect(screen.queryByText(/^live$/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/connecting/i)).not.toBeInTheDocument()
  })

  it('shows a live badge when the real-time alert stream is connected', () => {
    render(<RiskPanel riskMap={sampleRisk} riskError={false} alerts={[]} alertsError={false} liveStatus="live" />)
    expect(screen.getByText('Live')).toBeInTheDocument()
  })

  it('shows an offline badge when the real-time alert stream is disconnected', () => {
    render(<RiskPanel riskMap={sampleRisk} riskError={false} alerts={[]} alertsError={false} liveStatus="offline" />)
    expect(screen.getByText('Offline')).toBeInTheDocument()
  })

  it('renders every village score with its risk level and confidence, worst first', () => {
    render(<RiskPanel riskMap={sampleRisk} riskError={false} alerts={[]} alertsError={false} />)
    const rows = screen.getAllByText(/\/100$/)
    expect(rows).toHaveLength(2)
    // Highest score (Kedarnath, HIGH) must render before the lowest (Rudraprayag, LOW).
    expect(rows[0].textContent).toContain('62.3')
    expect(screen.getByText(/no open alerts/i)).toBeInTheDocument()
  })

  it('shows the always-on baseline disclaimer, not a claim of validated accuracy', () => {
    render(<RiskPanel riskMap={sampleRisk} riskError={false} alerts={[]} alertsError={false} />)
    expect(screen.getByText(/not a validated model/i)).toBeInTheDocument()
  })

  it('renders open alerts with their village and message', () => {
    render(<RiskPanel riskMap={sampleRisk} riskError={false} alerts={[sampleAlert]} alertsError={false} />)
    expect(screen.getByText('Kedarnath', { selector: '.alert-row .risk-name' })).toBeInTheDocument()
    expect(screen.getByText(/heightened caution advised/i)).toBeInTheDocument()
  })

  it('shows the real glacial-lake advisory distance when present, and omits it when absent', () => {
    render(<RiskPanel riskMap={sampleRisk} riskError={false} alerts={[]} alertsError={false} />)
    expect(screen.getByText(/nearest glacial lake ~5\.6 km/i)).toBeInTheDocument()
    // Rudraprayag's fixture entry has no glacial_lake_distance_km — must not
    // render a fabricated distance for it.
    expect(screen.getAllByText(/nearest glacial lake/i)).toHaveLength(1)
  })

  it('shows the GLOF contribution indicator when present, and omits it when absent', () => {
    render(<RiskPanel riskMap={sampleRisk} riskError={false} alerts={[]} alertsError={false} />)
    expect(screen.getByText(/glacial hazard context: HIGH \(71%\)/i)).toBeInTheDocument()
    // Rudraprayag's fixture entry has no glof_contribution_pct — must not
    // render a fabricated indicator for it.
    expect(screen.getAllByText(/glacial hazard context/i)).toHaveLength(1)
  })

  it('shows the SCS-CN runoff estimate when present, and omits it when absent', () => {
    render(<RiskPanel riskMap={sampleRisk} riskError={false} alerts={[]} alertsError={false} />)
    expect(screen.getByText(/SCS-CN runoff: 24\.7 mm \(CN 79\)/i)).toBeInTheDocument()
    // Rudraprayag's fixture entry has no scs_cn_runoff_depth_mm — must not
    // render a fabricated estimate for it.
    expect(screen.getAllByText(/SCS-CN runoff/i)).toHaveLength(1)
  })

  it('shows the rainfall intensity-duration threshold indicator when present, and omits it when absent', () => {
    render(<RiskPanel riskMap={sampleRisk} riskError={false} alerts={[]} alertsError={false} />)
    expect(screen.getByText(/I-D threshold: approaching within 24h \(~3\.2h\)/i)).toBeInTheDocument()
    // Rudraprayag's fixture entry has no rainfall_threshold_status — must not
    // render a fabricated indicator for it.
    expect(screen.getAllByText(/I-D threshold/i)).toHaveLength(1)
  })

  it('shows the antecedent rainfall index when present, labelled simulated, and omits it when absent', () => {
    render(<RiskPanel riskMap={sampleRisk} riskError={false} alerts={[]} alertsError={false} />)
    expect(screen.getByText(/5-day antecedent rainfall: 18\.4 mm \(simulated\)/i)).toBeInTheDocument()
    // Rudraprayag's fixture entry has no antecedent_rainfall_5day_mm — must
    // not render a fabricated figure for it.
    expect(screen.getAllByText(/5-day antecedent rainfall/i)).toHaveLength(1)
  })
})

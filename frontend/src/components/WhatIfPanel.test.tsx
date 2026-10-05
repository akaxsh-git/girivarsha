import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WhatIfPanel } from './WhatIfPanel'
import * as api from '../lib/api'
import type { SimulationResult, Village } from '../lib/api'

vi.mock('../lib/api')

const villages: Village[] = [
  {
    id: 1,
    name: 'Kedarnath',
    district: 'Rudraprayag',
    state: 'Uttarakhand',
    elevation_m: 3583,
    population: null,
    lat: 30.7346,
    lon: 79.0669,
    coordinate_precision: 'surveyed',
    catchment_id: 1,
    catchment_name: 'Mandakini Valley',
    region_id: 1,
    region_name: 'Mandakini Valley',
    source: 'real',
    provenance: null,
  },
  {
    id: 2,
    name: 'Rudraprayag',
    district: 'Rudraprayag',
    state: 'Uttarakhand',
    elevation_m: 895,
    population: null,
    lat: 30.28,
    lon: 78.98,
    coordinate_precision: 'surveyed',
    catchment_id: 1,
    catchment_name: 'Mandakini Valley',
    region_id: 1,
    region_name: 'Mandakini Valley',
    source: 'real',
    provenance: null,
  },
]

function makeResult(overrides: Partial<SimulationResult> = {}): SimulationResult {
  return {
    village_id: 1,
    village_name: 'Kedarnath',
    is_simulation: true,
    overrides_applied: { rainfall_mm_hr: 30, soil_moisture_pct: 70 },
    baseline_risk_score: 22.5,
    baseline_risk_level: 'LOW',
    baseline_confidence_pct: 38.5,
    simulated_risk_score: 68.2,
    simulated_risk_level: 'HIGH',
    simulated_confidence_pct: 38.5,
    model_version: 'baseline-v1',
    drivers: {
      components: [
        {
          name: 'rainfall_intensity',
          description: 'What-if override rainfall rate (hypothetical, not a live reading)',
          raw_value: 30,
          unit: 'mm/hr',
          source: 'simulated',
          normalized_0_1: 0.6,
          weight: 0.35,
          score_contribution: 21.0,
        },
        {
          name: 'soil_moisture',
          description: 'What-if override soil saturation (hypothetical, not a live reading)',
          raw_value: 70,
          unit: 'pct',
          source: 'simulated',
          normalized_0_1: 0.7,
          weight: 0.25,
          score_contribution: 17.5,
        },
      ],
      confidence_explanation: 'Confidence reflects data-source quality.',
      not_included_yet: [],
    },
    note: 'This is a hypothetical what-if scenario, not a live reading. Nothing about this run is persisted to the database or fed into /alerts — it has zero side effects on the real system.',
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(api.runSimulation).mockReset()
})

describe('WhatIfPanel', () => {
  it('runs a simulation for the selected village and shows baseline vs hypothetical results', async () => {
    const user = userEvent.setup()
    vi.mocked(api.runSimulation).mockResolvedValue(makeResult())

    render(<WhatIfPanel villages={villages} />)

    await user.click(screen.getByRole('button', { name: /run what-if scenario/i }))

    await waitFor(() => expect(screen.getByText(/real current assessment/i)).toBeInTheDocument())
    expect(screen.getByText(/hypothetical \(what-if\)/i)).toBeInTheDocument()
    expect(screen.getByText('22.5')).toBeInTheDocument()
    expect(screen.getByText('68.2')).toBeInTheDocument()
    expect(api.runSimulation).toHaveBeenCalledWith(expect.objectContaining({ village_id: 1 }))
  })

  it('always surfaces the backend note verbatim so the hypothetical/real distinction is never lost', async () => {
    const user = userEvent.setup()
    vi.mocked(api.runSimulation).mockResolvedValue(makeResult())

    render(<WhatIfPanel villages={villages} />)
    await user.click(screen.getByRole('button', { name: /run what-if scenario/i }))

    await waitFor(() => expect(screen.getByText(/zero side effects on the real system/i)).toBeInTheDocument())
  })

  it('disables the run button when both overrides are turned off', async () => {
    const user = userEvent.setup()
    render(<WhatIfPanel villages={villages} />)

    await user.click(screen.getByLabelText(/override rainfall/i))
    await user.click(screen.getByLabelText(/override soil saturation/i))

    expect(screen.getByRole('button', { name: /run what-if scenario/i })).toBeDisabled()
  })

  it('shows an honest error state if the backend rejects the simulation', async () => {
    const user = userEvent.setup()
    vi.mocked(api.runSimulation).mockRejectedValue(new Error('network down'))

    render(<WhatIfPanel villages={villages} />)
    await user.click(screen.getByRole('button', { name: /run what-if scenario/i }))

    await waitFor(() => expect(document.querySelector('.catchment-empty')).not.toBeNull())
    expect(screen.queryByText(/real current assessment/i)).not.toBeInTheDocument()
  })

  it('shows the SCS-CN runoff comparison, which responds to the overrides unlike the risk score alone', async () => {
    const user = userEvent.setup()
    vi.mocked(api.runSimulation).mockResolvedValue(
      makeResult({
        baseline_scs_cn_curve_number: 79,
        baseline_scs_cn_runoff_depth_mm: 5.2,
        baseline_scs_cn_runoff_ratio: 0.17,
        baseline_scs_cn_note: 'baseline note',
        simulated_scs_cn_curve_number: 91,
        simulated_scs_cn_runoff_depth_mm: 24.7,
        simulated_scs_cn_runoff_ratio: 0.82,
        simulated_scs_cn_note: 'SCS-CN estimate: real NRCS TR-55 method note',
      }),
    )

    render(<WhatIfPanel villages={villages} />)
    await user.click(screen.getByRole('button', { name: /run what-if scenario/i }))

    await waitFor(() => expect(screen.getByText(/SCS-CN rainfall-runoff estimate/i)).toBeInTheDocument())
    expect(screen.getByText('5.2 mm')).toBeInTheDocument()
    expect(screen.getByText('24.7 mm')).toBeInTheDocument()
    expect(screen.getByText(/real NRCS TR-55 method note/i)).toBeInTheDocument()
  })

  it('shows the rainfall I-D threshold comparison, which responds to the overrides unlike the risk score alone', async () => {
    const user = userEvent.setup()
    vi.mocked(api.runSimulation).mockResolvedValue(
      makeResult({
        baseline_rainfall_threshold_status: 'not_indicated_within_24h',
        baseline_rainfall_threshold_hours_to_threshold: 48.3,
        baseline_rainfall_threshold_note: 'baseline rainfall-threshold note',
        simulated_rainfall_threshold_status: 'threshold_exceeded',
        simulated_rainfall_threshold_hours_to_threshold: 0.4,
        simulated_rainfall_threshold_note: 'Kanungo & Sharma (2014) simulated rainfall-threshold note',
      }),
    )

    render(<WhatIfPanel villages={villages} />)
    await user.click(screen.getByRole('button', { name: /run what-if scenario/i }))

    await waitFor(() => expect(screen.getByText(/rainfall intensity-duration threshold/i)).toBeInTheDocument())
    expect(screen.getByText(/not indicated within 24h \(~48\.3h\)/i)).toBeInTheDocument()
    expect(screen.getByText(/threshold exceeded \(~0\.4h\)/i)).toBeInTheDocument()
    expect(screen.getByText(/simulated rainfall-threshold note/i)).toBeInTheDocument()
  })

  it('shows the antecedent rainfall index as a single figure, unaffected by the overrides', async () => {
    const user = userEvent.setup()
    vi.mocked(api.runSimulation).mockResolvedValue(
      makeResult({
        antecedent_rainfall_5day_mm: 18.4,
        antecedent_rainfall_source: 'simulated',
        antecedent_rainfall_note: 'Simulated antecedent-precipitation-index note',
      }),
    )

    render(<WhatIfPanel villages={villages} />)
    await user.click(screen.getByRole('button', { name: /run what-if scenario/i }))

    await waitFor(() => expect(screen.getByText(/antecedent precipitation index/i)).toBeInTheDocument())
    expect(screen.getByText(/18\.4 mm over 5 days \(simulated\)/i)).toBeInTheDocument()
    expect(screen.getByText(/simulated antecedent-precipitation-index note/i)).toBeInTheDocument()
  })

  it('sends null for a disabled override rather than a stale slider value', async () => {
    const user = userEvent.setup()
    vi.mocked(api.runSimulation).mockResolvedValue(makeResult())

    render(<WhatIfPanel villages={villages} />)
    await user.click(screen.getByLabelText(/override soil saturation/i))
    await user.click(screen.getByRole('button', { name: /run what-if scenario/i }))

    await waitFor(() =>
      expect(api.runSimulation).toHaveBeenCalledWith(expect.objectContaining({ soil_moisture_pct: null })),
    )
  })
})

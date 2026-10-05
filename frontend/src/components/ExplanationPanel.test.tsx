import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ExplanationPanel } from './ExplanationPanel'
import * as api from '../lib/api'
import type { Explanation, Village } from '../lib/api'

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

function makeExplanation(overrides: Partial<Explanation> = {}): Explanation {
  return {
    village_id: 1,
    village_name: 'Kedarnath',
    summary: "Kedarnath's risk score (62/100, HIGH) is driven primarily by how saturated the ground already is (40%).",
    ranked_drivers: [
      {
        name: 'soil_moisture',
        plain_language: 'how saturated the ground already is',
        score_contribution: 0.1,
        share_of_score_pct: 40,
        raw_value: 55.2,
        unit: 'pct',
        source: 'simulated',
        detail: 'Current soil saturation at this village',
      },
      {
        name: 'rainfall_intensity',
        plain_language: 'how hard it is currently raining at this village',
        score_contribution: 0.08,
        share_of_score_pct: 32,
        raw_value: 6.1,
        unit: 'mm/hr',
        source: 'simulated',
        detail: 'Current rainfall rate at this village',
      },
    ],
    model_explained: 'weighted_baseline (Phase 4 active model)',
    caveat: 'This explains the ACTIVE baseline model, not a SHAP explanation of the undeployed ML layer.',
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(api.getExplanation).mockReset()
})

describe('ExplanationPanel', () => {
  it('shows the plain-language summary and ranked drivers for the selected village', async () => {
    vi.mocked(api.getExplanation).mockResolvedValue(makeExplanation())

    render(<ExplanationPanel villages={villages} />)

    await waitFor(() => expect(screen.getByText(/driven primarily by/i)).toBeInTheDocument())
    expect(screen.getAllByText(/how saturated the ground already is/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/not a shap explanation/i)).toBeInTheDocument()
  })

  it('re-fetches the explanation when a different village is picked', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getExplanation).mockImplementation(async (id) =>
      id === 2
        ? makeExplanation({ village_id: 2, village_name: 'Rudraprayag', summary: "Rudraprayag's score is low." })
        : makeExplanation(),
    )

    render(<ExplanationPanel villages={villages} />)
    await waitFor(() => expect(screen.getByText(/driven primarily by/i)).toBeInTheDocument())

    await user.selectOptions(screen.getByLabelText(/explain the score for/i), '2')

    await waitFor(() => expect(screen.getByText(/rudraprayag's score is low/i)).toBeInTheDocument())
  })

  it('shows an honest error state if the backend is unreachable', async () => {
    vi.mocked(api.getExplanation).mockRejectedValue(new api.ApiError('down'))

    render(<ExplanationPanel villages={villages} />)

    await waitFor(() => expect(screen.getByText(/explanation unreachable/i)).toBeInTheDocument())
  })

  it('surfaces which live sensor produced a driver, when the backend says one did', async () => {
    vi.mocked(api.getExplanation).mockResolvedValue(
      makeExplanation({
        ranked_drivers: [
          {
            name: 'rainfall_intensity',
            plain_language: 'how hard it is currently raining at this village',
            score_contribution: 0.2,
            share_of_score_pct: 60,
            raw_value: 42.5,
            unit: 'mm/hr',
            source: 'real',
            detail: "Current rainfall rate from this village's live sensor (sensor:esp32-kedarnath-rain-01)",
          },
        ],
      }),
    )

    render(<ExplanationPanel villages={villages} />)

    await waitFor(() => expect(screen.getByText(/esp32-kedarnath-rain-01/i)).toBeInTheDocument())
  })

  it('does not show a sensor detail line for provider-sourced drivers', async () => {
    vi.mocked(api.getExplanation).mockResolvedValue(makeExplanation())

    render(<ExplanationPanel villages={villages} />)

    await waitFor(() => expect(screen.getByText(/driven primarily by/i)).toBeInTheDocument())
    expect(screen.queryByText(/live sensor/i)).not.toBeInTheDocument()
  })
})

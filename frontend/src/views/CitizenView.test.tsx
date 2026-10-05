import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CitizenView } from './CitizenView'
import * as api from '../lib/api'
import type { RiskDetail, Village } from '../lib/api'

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

function makeDetail(overrides: Partial<RiskDetail> = {}): RiskDetail {
  return {
    village_id: 1,
    village_name: 'Kedarnath',
    risk_score: 62,
    risk_level: 'HIGH',
    confidence_pct: 38,
    lead_time_minutes: null,
    lead_time_note: 'Village has no assigned micro-catchment — cannot estimate an upstream propagation time.',
    model_version: 'baseline-v1',
    drivers: {},
    computed_at: '2026-09-03T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(api.getVillages).mockReset()
  vi.mocked(api.getRiskForVillage).mockReset()
  // The language toggle persists to localStorage — clear it so one test's
  // language choice can never leak into the next test's initial render.
  window.localStorage.clear()
})

describe('CitizenView', () => {
  it('shows a plain-language card for the selected village, not raw driver data', async () => {
    vi.mocked(api.getVillages).mockResolvedValue(villages)
    vi.mocked(api.getRiskForVillage).mockResolvedValue(makeDetail())

    render(<CitizenView />)

    await waitFor(() => expect(screen.getByText('Kedarnath')).toBeInTheDocument())
    expect(screen.getByText(/elevated risk/i)).toBeInTheDocument()
    // Never dumps the raw driver breakdown into the citizen-facing card —
    // that stays in AuthorityView.
    expect(screen.queryByText(/rainfall_intensity/i)).not.toBeInTheDocument()
  })

  it('shows the real glacial-lake advisory distance as background context, not part of the reading', async () => {
    vi.mocked(api.getVillages).mockResolvedValue(villages)
    vi.mocked(api.getRiskForVillage).mockResolvedValue(makeDetail({ glacial_lake_distance_km: 5.56 }))

    render(<CitizenView />)

    await waitFor(() => expect(screen.getByText(/5\.6 km/)).toBeInTheDocument())
    expect(screen.getByText(/background context only/i)).toBeInTheDocument()
  })

  it('shows the GLOF contribution indicator as background context, never as a flood probability', async () => {
    vi.mocked(api.getVillages).mockResolvedValue(villages)
    vi.mocked(api.getRiskForVillage).mockResolvedValue(
      makeDetail({ glof_contribution_pct: 71.2, glof_contribution_tier: 'HIGH' }),
    )

    render(<CitizenView />)

    await waitFor(() => expect(screen.getByText(/\(71%\)/)).toBeInTheDocument())
    expect(screen.getByText(/not a percentage chance of a flash flood/i)).toBeInTheDocument()
  })

  it('shows the SCS-CN runoff estimate in plain language, not as a flood prediction', async () => {
    vi.mocked(api.getVillages).mockResolvedValue(villages)
    vi.mocked(api.getRiskForVillage).mockResolvedValue(makeDetail({ scs_cn_runoff_depth_mm: 24.7 }))

    render(<CitizenView />)

    await waitFor(() => expect(screen.getByText(/24\.7 mm/)).toBeInTheDocument())
    expect(screen.getByText(/not a prediction of flooding by itself/i)).toBeInTheDocument()
  })

  it('shows a plain-language message when the rainfall I-D threshold is already exceeded', async () => {
    vi.mocked(api.getVillages).mockResolvedValue(villages)
    vi.mocked(api.getRiskForVillage).mockResolvedValue(
      makeDetail({ rainfall_threshold_status: 'threshold_exceeded', rainfall_threshold_hours_to_threshold: 0.5 }),
    )

    render(<CitizenView />)

    await waitFor(() =>
      expect(screen.getByText(/current rainfall intensity has already reached levels/i)).toBeInTheDocument(),
    )
    expect(screen.getByText(/not part of the score above/i)).toBeInTheDocument()
  })

  it('shows a plain-language countdown when the rainfall I-D threshold is approaching within 24h', async () => {
    vi.mocked(api.getVillages).mockResolvedValue(villages)
    vi.mocked(api.getRiskForVillage).mockResolvedValue(
      makeDetail({ rainfall_threshold_status: 'approaching_within_24h', rainfall_threshold_hours_to_threshold: 6.4 }),
    )

    render(<CitizenView />)

    await waitFor(() => expect(screen.getByText(/6\.4h/)).toBeInTheDocument())
    expect(screen.getByText(/not a forecast/i)).toBeInTheDocument()
  })

  it('shows nothing for the rainfall threshold when it is below the study floor or not indicated', async () => {
    vi.mocked(api.getVillages).mockResolvedValue(villages)
    vi.mocked(api.getRiskForVillage).mockResolvedValue(
      makeDetail({ rainfall_threshold_status: 'below_floor', rainfall_threshold_hours_to_threshold: null }),
    )

    render(<CitizenView />)

    await waitFor(() => expect(screen.getByText('Kedarnath')).toBeInTheDocument())
    expect(screen.queryByText(/historically associated with landslides/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/already reached levels/i)).not.toBeInTheDocument()
  })

  it('never claims to be an official warning', async () => {
    vi.mocked(api.getVillages).mockResolvedValue(villages)
    vi.mocked(api.getRiskForVillage).mockResolvedValue(makeDetail())

    render(<CitizenView />)

    await waitFor(() => expect(screen.getByText(/not an official government warning/i)).toBeInTheDocument())
  })

  it('re-fetches risk when a different village is picked', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getVillages).mockResolvedValue(villages)
    vi.mocked(api.getRiskForVillage).mockImplementation(async (id) =>
      id === 2 ? makeDetail({ village_id: 2, village_name: 'Rudraprayag', risk_level: 'LOW' }) : makeDetail(),
    )

    render(<CitizenView />)
    await waitFor(() => expect(screen.getByText('Kedarnath')).toBeInTheDocument())

    await user.selectOptions(screen.getByLabelText(/your village/i), '2')

    await waitFor(() => expect(screen.getByText('Rudraprayag')).toBeInTheDocument())
    expect(screen.getByText(/no unusual risk detected/i)).toBeInTheDocument()
  })

  it('shows an honest error state if the backend is unreachable', async () => {
    vi.mocked(api.getVillages).mockRejectedValue(new api.ApiError('down'))

    render(<CitizenView />)

    await waitFor(() => expect(screen.getByText(/village list unreachable/i)).toBeInTheDocument())
  })

  it('defaults to English and switches the visible copy to Hindi on toggle, without changing the underlying risk data', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getVillages).mockResolvedValue(villages)
    vi.mocked(api.getRiskForVillage).mockResolvedValue(makeDetail())

    render(<CitizenView />)
    await waitFor(() => expect(screen.getByText(/elevated risk/i)).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'हिन्दी' }))

    // The Hindi HIGH headline, not a re-fetch or a different number.
    await waitFor(() => expect(screen.getByText(/बढ़ा हुआ जोखिम/)).toBeInTheDocument())
    expect(screen.queryByText(/elevated risk/i)).not.toBeInTheDocument()
    expect(screen.getByText('Kedarnath')).toBeInTheDocument() // village name itself is data, not translated copy
    expect(api.getRiskForVillage).toHaveBeenCalledTimes(1) // toggling language must not re-fetch

    await user.click(screen.getByRole('button', { name: 'English' }))
    await waitFor(() => expect(screen.getByText(/elevated risk/i)).toBeInTheDocument())
  })
})

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EvacuationPanel } from './EvacuationPanel'
import * as api from '../lib/api'
import type { EvacuationRoute, Village } from '../lib/api'

vi.mock('../lib/api')

const villages: Village[] = [
  {
    id: 7,
    name: 'Reni',
    district: 'Chamoli',
    state: 'Uttarakhand',
    elevation_m: 1973,
    population: null,
    lat: 30.48555,
    lon: 79.69432,
    coordinate_precision: 'surveyed',
    catchment_id: 2,
    catchment_name: 'Rishiganga-Dhauliganga Valley',
    region_id: 2,
    region_name: 'Chamoli Disaster Valley',
    source: 'real',
    provenance: null,
  },
  {
    id: 9,
    name: 'Vishnuprayag',
    district: 'Chamoli',
    state: 'Uttarakhand',
    elevation_m: 1372,
    population: null,
    lat: 30.5625,
    lon: 79.57528,
    coordinate_precision: 'surveyed',
    catchment_id: 2,
    catchment_name: 'Rishiganga-Dhauliganga Valley',
    region_id: 2,
    region_name: 'Chamoli Disaster Valley',
    source: 'real',
    provenance: null,
  },
]

function makeRoute(overrides: Partial<EvacuationRoute> = {}): EvacuationRoute {
  return {
    origin_village_id: 7,
    origin_village_name: 'Reni',
    destination_village_id: 9,
    destination_village_name: 'Vishnuprayag',
    hops: [
      {
        from_village_id: 7,
        from_village_name: 'Reni',
        to_village_id: 9,
        to_village_name: 'Vishnuprayag',
        distance_km: 32.74,
        unsafe: false,
        unsafe_reason: null,
        distance_source: 'real_road_network',
        road_note: 'Real OpenStreetMap road/trail path (335 mapped points), snapped 17m from Reni.',
        polyline: [
          [30.48555, 79.69432],
          [30.5625, 79.57528],
        ],
      },
    ],
    total_distance_km: 32.74,
    estimated_minutes: 392.8,
    note: 'Prototype route: 1 hop(s)... all 1 hop(s) used real OpenStreetMap road/trail routing.',
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(api.getEvacuationRoute).mockReset()
  vi.mocked(api.getAllEvacuationRoutes).mockReset()
  // Default: an empty summary table, so tests focused on the detail view
  // don't need to also stub this call unless they care about it.
  vi.mocked(api.getAllEvacuationRoutes).mockResolvedValue([])
})

describe('EvacuationPanel', () => {
  it('shows the computed route with distance and unsafe flags', async () => {
    vi.mocked(api.getEvacuationRoute).mockResolvedValue(
      makeRoute({
        hops: [
          {
            from_village_id: 7,
            from_village_name: 'Reni',
            to_village_id: 9,
            to_village_name: 'Vishnuprayag',
            distance_km: 32.74,
            unsafe: true,
            unsafe_reason: 'Reni currently at HIGH risk — derived heuristic, not real road data.',
            distance_source: 'real_road_network',
            road_note: 'Real OpenStreetMap road/trail path.',
            polyline: [
              [30.48555, 79.69432],
              [30.5625, 79.57528],
            ],
          },
        ],
      }),
    )

    render(<EvacuationPanel villages={villages} regionId={2} />)

    await waitFor(() => expect(screen.getByText(/vishnuprayag/i)).toBeInTheDocument())
    expect(screen.getAllByText(/32.74 km/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/flagged/i)).toBeInTheDocument()
    expect(screen.getByText(/derived heuristic, not real road data/i)).toBeInTheDocument()
  })

  it('shows the honest empty-route note when origin is already the destination', async () => {
    vi.mocked(api.getEvacuationRoute).mockResolvedValue(
      makeRoute({
        hops: [],
        total_distance_km: 0,
        estimated_minutes: null,
        note: 'Vishnuprayag is already this catchment’s lowest-elevation seeded settlement — no route to compute.',
      }),
    )

    render(<EvacuationPanel villages={villages} regionId={2} />)

    await waitFor(() => expect(screen.getByText(/already this catchment/i)).toBeInTheDocument())
  })

  it('re-fetches the route when a different origin village is picked', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getEvacuationRoute).mockImplementation(async (id) =>
      id === 9
        ? makeRoute({ origin_village_id: 9, origin_village_name: 'Vishnuprayag', hops: [], total_distance_km: 0, estimated_minutes: null, note: 'already there' })
        : makeRoute(),
    )

    render(<EvacuationPanel villages={villages} regionId={2} />)
    await waitFor(() => expect(screen.getByText(/vishnuprayag/i)).toBeInTheDocument())

    await user.selectOptions(screen.getByLabelText(/route detail from/i), '9')

    await waitFor(() => expect(screen.getByText(/already there/i)).toBeInTheDocument())
  })

  it('shows an honest error state if the backend is unreachable', async () => {
    vi.mocked(api.getEvacuationRoute).mockRejectedValue(new api.ApiError('down'))

    render(<EvacuationPanel villages={villages} regionId={2} />)

    await waitFor(() => expect(screen.getByText(/route unreachable/i)).toBeInTheDocument())
  })

  it('shows every village’s route in a summary table, including unsafe-hop counts', async () => {
    vi.mocked(api.getEvacuationRoute).mockResolvedValue(makeRoute())
    vi.mocked(api.getAllEvacuationRoutes).mockResolvedValue([
      makeRoute(),
      makeRoute({
        origin_village_id: 9,
        origin_village_name: 'Vishnuprayag',
        hops: [],
        total_distance_km: 0,
        estimated_minutes: null,
        note: 'already there',
      }),
    ])

    render(<EvacuationPanel villages={villages} regionId={2} />)

    await waitFor(() => expect(screen.getByText(/every village/i)).toBeInTheDocument())
    // Both villages appear as rows in the summary table.
    const table = screen.getByRole('table')
    expect(table).toHaveTextContent('Reni')
    expect(table).toHaveTextContent('Vishnuprayag')
    expect(table).toHaveTextContent('none') // Reni's route has no unsafe hops
  })

  it('clicking a summary row selects that village for the detail view', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getEvacuationRoute).mockImplementation(async (id) =>
      id === 9
        ? makeRoute({ origin_village_id: 9, origin_village_name: 'Vishnuprayag', hops: [], total_distance_km: 0, estimated_minutes: null, note: 'already there' })
        : makeRoute(),
    )
    vi.mocked(api.getAllEvacuationRoutes).mockResolvedValue([
      makeRoute(),
      makeRoute({
        origin_village_id: 9,
        origin_village_name: 'Vishnuprayag',
        destination_village_id: null,
        destination_village_name: null,
        hops: [],
        total_distance_km: 0,
        estimated_minutes: null,
      }),
    ])

    render(<EvacuationPanel villages={villages} regionId={2} />)
    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument())

    const rows = within(screen.getByRole('table')).getAllByRole('row')
    const vishnuprayagRow = rows.find(
      (row) => within(row).queryAllByRole('cell')[0]?.textContent === 'Vishnuprayag',
    )
    await user.click(within(vishnuprayagRow!).getByText('Vishnuprayag'))

    await waitFor(() => expect(screen.getByText(/already there/i)).toBeInTheDocument())
  })

  it('shows an honest empty state for the summary table when the backend is unreachable', async () => {
    vi.mocked(api.getEvacuationRoute).mockResolvedValue(makeRoute())
    vi.mocked(api.getAllEvacuationRoutes).mockRejectedValue(new api.ApiError('down'))

    render(<EvacuationPanel villages={villages} regionId={2} />)

    await waitFor(() => expect(screen.getByText(/route summary unreachable/i)).toBeInTheDocument())
  })

  // -------------------------------------------------------------------
  // Real OpenStreetMap road/trail network follow-up (user-requested):
  // each hop's distance_source must be shown honestly, never hidden or
  // presented as if every hop were the same kind of data.
  // -------------------------------------------------------------------
  it('labels a real-road-network hop distinctly from a straight-line-proxy hop', async () => {
    vi.mocked(api.getEvacuationRoute).mockResolvedValue(
      makeRoute({
        hops: [
          {
            from_village_id: 7,
            from_village_name: 'Reni',
            to_village_id: 8,
            to_village_name: 'Tapovan',
            distance_km: 10.17,
            unsafe: false,
            unsafe_reason: null,
            distance_source: 'real_road_network',
            road_note: 'Real OpenStreetMap road/trail path (336 mapped points).',
            polyline: [
              [30.48555, 79.69432],
              [30.49414, 79.62753],
            ],
          },
          {
            from_village_id: 8,
            from_village_name: 'Tapovan',
            to_village_id: 9,
            to_village_name: 'Vishnuprayag',
            distance_km: 22.0,
            unsafe: false,
            unsafe_reason: null,
            distance_source: 'straight_line_proxy',
            road_note: 'No real road/trail path found — using the straight-line elevation-order proxy.',
            polyline: null,
          },
        ],
      }),
    )

    render(<EvacuationPanel villages={villages} regionId={2} />)

    await waitFor(() => expect(screen.getByText(/vishnuprayag/i)).toBeInTheDocument())
    expect(screen.getByText(/^real road\/trail$/i)).toBeInTheDocument()
    expect(screen.getByText(/^straight-line est\.$/i)).toBeInTheDocument()
    expect(screen.getByText(/336 mapped points/i)).toBeInTheDocument()
    expect(screen.getByText(/using the straight-line elevation-order proxy/i)).toBeInTheDocument()
  })

  it("shows the summary table's per-route road-data badge, mixed when only some hops are real", async () => {
    vi.mocked(api.getEvacuationRoute).mockResolvedValue(makeRoute())
    vi.mocked(api.getAllEvacuationRoutes).mockResolvedValue([
      makeRoute(), // all-real single hop
      makeRoute({
        origin_village_id: 9,
        origin_village_name: 'Vishnuprayag',
        hops: [
          {
            from_village_id: 9,
            from_village_name: 'Vishnuprayag',
            to_village_id: 7,
            to_village_name: 'Reni',
            distance_km: 5,
            unsafe: false,
            unsafe_reason: null,
            distance_source: 'straight_line_proxy',
            road_note: 'No real road/trail path found.',
            polyline: null,
          },
        ],
      }),
    ])

    render(<EvacuationPanel villages={villages} regionId={2} />)

    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument())
    const table = screen.getByRole('table')
    expect(within(table).getByText(/^real road\/trail$/i)).toBeInTheDocument()
    expect(within(table).getByText(/^straight-line est\.$/i)).toBeInTheDocument()
  })
})

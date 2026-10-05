import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { PilotMap } from './PilotMap'
import type { Village, WindField } from '../lib/api'

vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children?: ReactNode }) => <div data-testid="map-container">{children}</div>,
  TileLayer: () => null,
  CircleMarker: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Popup: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Polyline: () => null,
}))
vi.mock('./WindLayer', () => ({ WindLayer: () => <div data-testid="wind-layer" /> }))

const villages: Village[] = [
  {
    id: 1, name: 'Kedarnath', district: 'Rudraprayag', state: 'Uttarakhand', elevation_m: 3583,
    population: null, lat: 30.73, lon: 79.06, coordinate_precision: 'surveyed', catchment_id: 1,
    catchment_name: 'Mandakini', region_id: 1, region_name: 'Mandakini', source: 'real', provenance: 'x',
  },
]
const field: WindField = {
  south: 30, west: 78, north: 31, east: 80, nx: 2, ny: 2,
  points: [0, 1, 2, 3].map((i) => ({ lat: 30, lon: 78, speed_ms: 3, direction_deg: 270, gust_ms: null, u: 3, v: i })),
  valid_time: null, source: 'real', provider: 'Open-Meteo', note: '',
}

const fetchMock = vi.fn()
beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(cleanup)

describe('PilotMap wind overlay', () => {
  it('is off by default and does not call the wind API', () => {
    render(<PilotMap villages={villages} />)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.queryByTestId('wind-layer')).toBeNull()
  })

  it('fetches real wind and shows the layer plus honest legend when toggled on', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => field })
    render(<PilotMap villages={villages} />)
    await userEvent.click(screen.getByRole('button', { name: /show wind/i }))
    await waitFor(() => expect(screen.getByTestId('wind-layer')).toBeInTheDocument())
    expect(screen.getByText(/not used by the risk model/i)).toBeInTheDocument()
  })

  it('says wind is unavailable instead of drawing anything when the API fails', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 503, json: async () => ({}) })
    render(<PilotMap villages={villages} />)
    await userEvent.click(screen.getByRole('button', { name: /show wind/i }))
    await waitFor(() => expect(screen.getByText(/wind data unavailable/i)).toBeInTheDocument())
    expect(screen.queryByTestId('wind-layer')).toBeNull()
  })
})

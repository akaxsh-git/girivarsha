import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { PilotMap } from './PilotMap'
import type { Village } from '../lib/api'

// jsdom doesn't implement enough of the layout/canvas APIs for real Leaflet
// map panes to initialise (a known jsdom+Leaflet limitation, not specific to
// this component) — so the map primitives are stubbed here. That still lets
// these tests verify what's actually ours: PilotMap's own logic (the empty
// state, the legend, and that it doesn't throw wiring real village data
// through to react-leaflet's props) without re-testing Leaflet itself.
vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children?: ReactNode }) => <div data-testid="map-container">{children}</div>,
  TileLayer: () => <div data-testid="tile-layer" />,
  CircleMarker: ({ children }: { children?: ReactNode }) => <div data-testid="circle-marker">{children}</div>,
  Popup: ({ children }: { children?: ReactNode }) => <div data-testid="popup">{children}</div>,
  Polyline: () => <div data-testid="polyline" />,
}))

const sampleVillages: Village[] = [
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
    provenance: 'Wikipedia',
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
    coordinate_precision: 'approximate',
    catchment_id: 1,
    catchment_name: 'Mandakini Valley',
    region_id: 1,
    region_name: 'Mandakini Valley',
    source: 'real',
    provenance: 'interpolated',
  },
]

const secondValleyVillages: Village[] = [
  {
    id: 3,
    name: 'Reni',
    district: 'Chamoli',
    state: 'Uttarakhand',
    elevation_m: 1973,
    population: null,
    lat: 30.48555,
    lon: 79.69432,
    coordinate_precision: 'surveyed',
    catchment_id: 2,
    catchment_name: 'Rishiganga-Dhauliganga Valley (Reni -> Vishnuprayag)',
    region_id: 2,
    region_name: 'Chamoli Disaster Valley',
    source: 'real',
    provenance: 'GEER report',
  },
  {
    id: 4,
    name: 'Vishnuprayag',
    district: 'Chamoli',
    state: 'Uttarakhand',
    elevation_m: 1372,
    population: null,
    lat: 30.5625,
    lon: 79.57528,
    coordinate_precision: 'surveyed',
    catchment_id: 2,
    catchment_name: 'Rishiganga-Dhauliganga Valley (Reni -> Vishnuprayag)',
    region_id: 2,
    region_name: 'Chamoli Disaster Valley',
    source: 'real',
    provenance: 'Wikipedia',
  },
]

describe('PilotMap', () => {
  it('shows an honest empty state instead of a blank/fake map when there is no data', () => {
    render(<PilotMap villages={[]} />)
    expect(screen.getByRole('status')).toHaveTextContent(/no village location data/i)
  })

  it('renders a map container and the coordinate-precision legend for real village data', () => {
    render(<PilotMap villages={sampleVillages} />)
    expect(screen.getByTestId('map-container')).toBeInTheDocument()
    expect(screen.getAllByTestId('circle-marker')).toHaveLength(sampleVillages.length)
    expect(screen.getByText(/surveyed coordinates/i)).toBeInTheDocument()
    expect(screen.getByText(/approximate coordinates/i)).toBeInTheDocument()
    expect(screen.getByText(/not the real river course/i)).toBeInTheDocument()
  })

  it('draws one elevation-order line per catchment, never one line jumping across two unrelated valleys', () => {
    // Phase 11 regression check: with two regions' villages both on screen,
    // a single global elevation sort would draw a line straight from a
    // Chamoli village to a Mandakini one just because their elevations
    // happen to be adjacent. Grouping by catchment_id first must produce
    // exactly one polyline per catchment (2 catchments here -> 2 lines).
    render(<PilotMap villages={[...sampleVillages, ...secondValleyVillages]} />)
    expect(screen.getAllByTestId('polyline')).toHaveLength(2)
    expect(screen.getAllByTestId('circle-marker')).toHaveLength(4)
  })
})

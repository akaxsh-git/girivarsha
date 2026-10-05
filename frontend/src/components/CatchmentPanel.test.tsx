import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CatchmentPanel } from './CatchmentPanel'
import type { MicroCatchment } from '../lib/api'

const sampleCatchment: MicroCatchment = {
  id: 1,
  name: 'Mandakini Valley (Kedarnath -> Rudraprayag)',
  watershed_name: 'Mandakini',
  river_name: 'Mandakini River',
  region_id: 1,
  region_name: 'Mandakini Valley',
  upstream_catchment_id: null,
  has_polygon_geometry: false,
  village_count: 6,
  source: 'derived',
  provenance: 'River-order research',
}

describe('CatchmentPanel', () => {
  it('shows a loading state, not a blank panel, while data is in flight', () => {
    render(<CatchmentPanel catchments={null} error={false} />)
    expect(screen.getByText(/loading catchment topology/i)).toBeInTheDocument()
  })

  it('shows an honest error state on failure, never fabricated data', () => {
    render(<CatchmentPanel catchments={null} error={true} />)
    expect(screen.getByText(/unreachable/i)).toBeInTheDocument()
  })

  it('never claims a real polygon boundary exists when has_polygon_geometry is false', () => {
    render(<CatchmentPanel catchments={[sampleCatchment]} error={false} />)
    expect(screen.getByText(sampleCatchment.name)).toBeInTheDocument()
    expect(screen.getByText(/no real boundary polygon yet/i)).toBeInTheDocument()
    expect(screen.queryByText(/real delineated boundary available/i)).not.toBeInTheDocument()
  })

  it('reports a real boundary only when the backend says has_polygon_geometry is true', () => {
    render(<CatchmentPanel catchments={[{ ...sampleCatchment, has_polygon_geometry: true }]} error={false} />)
    expect(screen.getByText(/real delineated boundary available/i)).toBeInTheDocument()
  })
})

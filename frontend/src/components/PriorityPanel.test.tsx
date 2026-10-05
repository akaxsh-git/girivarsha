import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { PriorityPanel } from './PriorityPanel'
import * as api from '../lib/api'
import type { EvacuationPriorityEntry } from '../lib/api'

vi.mock('../lib/api')

const entries: EvacuationPriorityEntry[] = [
  { village_id: 7, village_name: 'Reni', risk_level: 'MODERATE', risk_score: 31.2, lead_time_minutes: null, rank: 1 },
  { village_id: 8, village_name: 'Tapovan', risk_level: 'LOW', risk_score: 25.6, lead_time_minutes: 30, rank: 2 },
]

beforeEach(() => {
  vi.mocked(api.getEvacuationPriority).mockReset()
})

describe('PriorityPanel', () => {
  it('renders villages in rank order with their risk level and lead time', async () => {
    vi.mocked(api.getEvacuationPriority).mockResolvedValue(entries)

    render(<PriorityPanel regionId={2} />)

    await waitFor(() => expect(screen.getByText('Reni')).toBeInTheDocument())
    expect(screen.getByText('Tapovan')).toBeInTheDocument()
    expect(screen.getByText('MODERATE')).toBeInTheDocument()
    expect(screen.getByText(/30 min warning/i)).toBeInTheDocument()
    expect(screen.getByText(/no upstream estimate/i)).toBeInTheDocument()
  })

  it('re-fetches when the region changes', async () => {
    vi.mocked(api.getEvacuationPriority).mockResolvedValue(entries)
    const { rerender } = render(<PriorityPanel regionId={1} />)
    await waitFor(() => expect(api.getEvacuationPriority).toHaveBeenCalledWith(expect.anything(), 1))

    rerender(<PriorityPanel regionId={2} />)
    await waitFor(() => expect(api.getEvacuationPriority).toHaveBeenCalledWith(expect.anything(), 2))
  })

  it('shows an honest error state if the backend is unreachable', async () => {
    vi.mocked(api.getEvacuationPriority).mockRejectedValue(new api.ApiError('down'))

    render(<PriorityPanel regionId={null} />)

    await waitFor(() => expect(screen.getByText(/priority list unreachable/i)).toBeInTheDocument())
  })
})

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReplayPanel } from './ReplayPanel'
import * as api from '../lib/api'
import type { ReplayEvent, ReplayEventSummary } from '../lib/api'

vi.mock('../lib/api')

const summaries: ReplayEventSummary[] = [
  { event_id: 1, village_id: 1, village_name: 'Kedarnath', event_type: 'flash_flood', event_date: '2013-06-16T00:00:00+00:00', severity: 'catastrophic', entry_count: 2 },
]

function makeEvent(overrides: Partial<ReplayEvent> = {}): ReplayEvent {
  return {
    event_id: 1,
    village_id: 1,
    village_name: 'Kedarnath',
    event_type: 'flash_flood',
    event_date: '2013-06-16T00:00:00+00:00',
    severity: 'catastrophic',
    description: 'The 2013 Kedarnath disaster.',
    source_citation: 'https://en.wikipedia.org/wiki/2013_North_India_floods',
    timeline: [
      {
        sequence_order: 0,
        occurred_at: '2013-06-15T09:00:00+00:00',
        time_precision: 'exact_time',
        headline: 'IMD upgrades to heavy rainfall bulletin',
        description: 'IMD issues a 9am bulletin.',
        source_citation: 'https://www.downtoearth.org.in/natural-disasters/heavens-rage-41497',
      },
      {
        sequence_order: 1,
        occurred_at: '2013-06-17T00:00:00+00:00',
        time_precision: 'date_only',
        headline: 'Chorabari Lake breaches',
        description: 'The lake breaches its banks.',
        source_citation: 'https://dialogue.earth/en/climate/death-of-chorabari-lake/',
      },
    ],
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(api.getReplayEvents).mockReset()
  vi.mocked(api.getReplayEvent).mockReset()
})

describe('ReplayPanel', () => {
  it('shows the first real timeline entry and steps forward through the rest', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getReplayEvents).mockResolvedValue(summaries)
    vi.mocked(api.getReplayEvent).mockResolvedValue(makeEvent())

    render(<ReplayPanel />)

    await waitFor(() => expect(screen.getByText(/imd upgrades to heavy rainfall bulletin/i)).toBeInTheDocument())
    expect(screen.getByText(/step 1 of 2/i)).toBeInTheDocument()
    expect(screen.getByText(/exact time/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /next/i }))

    await waitFor(() => expect(screen.getByText(/chorabari lake breaches/i)).toBeInTheDocument())
    expect(screen.getByText(/step 2 of 2/i)).toBeInTheDocument()
    expect(screen.getByText(/date only/i)).toBeInTheDocument()
  })

  it('cites a real source for every entry shown', async () => {
    vi.mocked(api.getReplayEvents).mockResolvedValue(summaries)
    vi.mocked(api.getReplayEvent).mockResolvedValue(makeEvent())

    render(<ReplayPanel />)

    await waitFor(() => expect(screen.getByText(/source:/i)).toBeInTheDocument())
    expect(screen.getByText(/downtoearth\.org\.in/i)).toBeInTheDocument()
  })

  it('shows an honest empty state when no event has a seeded timeline', async () => {
    vi.mocked(api.getReplayEvents).mockResolvedValue([])

    render(<ReplayPanel />)

    await waitFor(() => expect(screen.getByText(/no historical events have a seeded timeline/i)).toBeInTheDocument())
  })

  it('shows an honest error state if the event list is unreachable', async () => {
    vi.mocked(api.getReplayEvents).mockRejectedValue(new api.ApiError('down'))

    render(<ReplayPanel />)

    await waitFor(() => expect(screen.getByText(/replay event list unreachable/i)).toBeInTheDocument())
  })
})

import { useEffect, useState } from 'react'
import { getReplayEvent, getReplayEvents, type ReplayEvent, type ReplayEventSummary } from '../lib/api'

const PRECISION_LABEL: Record<string, string> = {
  exact_time: 'exact time',
  approximate: 'approximate time',
  date_only: 'date only — no time recorded',
}

/**
 * Phase 12 — historical event replay, for authority users. Real GET
 * /replay/events + GET /replay/{id} — every entry shown here is a real,
 * cited sub-event (see backend/app/models/orm.py::EventTimelineEntry and
 * scripts/seed_event_timelines.py). Stepping is done entirely client-side
 * over the real ordered array returned by the API — there is no
 * simulated/fabricated timeline to step through, and no backend session
 * state, deliberately: this is real-data playback, not a simulation.
 */
export function ReplayPanel() {
  const [events, setEvents] = useState<ReplayEventSummary[] | null>(null)
  const [eventsError, setEventsError] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [event, setEvent] = useState<ReplayEvent | null>(null)
  const [eventError, setEventError] = useState(false)
  const [step, setStep] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    getReplayEvents(controller.signal)
      .then((e) => {
        setEvents(e)
        setEventsError(false)
        if (e.length > 0) setSelectedId(e[0].event_id)
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setEventsError(true)
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (selectedId === null) return
    const controller = new AbortController()
    getReplayEvent(selectedId, controller.signal)
      .then((e) => {
        setEvent(e)
        setEventError(false)
        setStep(0)
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setEventError(true)
      })
    return () => controller.abort()
  }, [selectedId])

  if (eventsError) {
    return <p className="catchment-empty">Replay event list unreachable — backend/DB may be down.</p>
  }
  if (events === null) {
    return <p className="catchment-empty">Loading replayable events…</p>
  }
  if (events.length === 0) {
    return <p className="catchment-empty">No historical events have a seeded timeline yet.</p>
  }
  if (eventError || !event) {
    return (
      <div className="replay-panel">
        <label htmlFor="replay-event-select">Historical event</label>
        <select
          id="replay-event-select"
          value={selectedId ?? ''}
          onChange={(e) => setSelectedId(Number(e.target.value))}
        >
          {events.map((e) => (
            <option key={e.event_id} value={e.event_id}>
              {e.village_name} — {e.event_date.slice(0, 10)}
            </option>
          ))}
        </select>
        <p className="catchment-empty">
          {eventError ? 'Timeline unreachable — backend/DB may be down.' : 'Loading timeline…'}
        </p>
      </div>
    )
  }

  const current = event.timeline[step]

  return (
    <div className="replay-panel">
      <label htmlFor="replay-event-select">Historical event</label>
      <select
        id="replay-event-select"
        value={selectedId ?? ''}
        onChange={(e) => setSelectedId(Number(e.target.value))}
      >
        {events.map((e) => (
          <option key={e.event_id} value={e.event_id}>
            {e.village_name} — {e.event_date.slice(0, 10)}
          </option>
        ))}
      </select>

      <p className="replay-event-description">{event.description}</p>

      <div className="replay-controls">
        <button type="button" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0}>
          ← Previous
        </button>
        <span className="replay-step-indicator">
          Step {step + 1} of {event.timeline.length}
        </span>
        <button
          type="button"
          onClick={() => setStep((s) => Math.min(event.timeline.length - 1, s + 1))}
          disabled={step === event.timeline.length - 1}
        >
          Next →
        </button>
      </div>

      <div className="replay-entry">
        <div className="replay-entry-when">
          {current.occurred_at
            ? new Date(current.occurred_at).toLocaleString('en-IN', {
                timeZone: 'Asia/Kolkata',
                day: 'numeric',
                month: 'short',
                year: 'numeric',
                ...(current.time_precision === 'date_only' ? {} : { hour: '2-digit', minute: '2-digit' }),
              }) + (current.time_precision === 'date_only' ? '' : ' IST')
            : 'time not recorded'}
          <span className={`replay-precision precision-${current.time_precision}`}>
            {PRECISION_LABEL[current.time_precision] ?? current.time_precision}
          </span>
        </div>
        <div className="replay-entry-headline">{current.headline}</div>
        <p className="replay-entry-description">{current.description}</p>
        <p className="replay-entry-citation">Source: {current.source_citation}</p>
      </div>

      <p className="replay-caveat">
        Every step is a real, cited moment from the historical record. Gaps and approximate times are
        labelled as such rather than filled in.
      </p>
    </div>
  )
}

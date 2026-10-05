import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SensorPanel } from './SensorPanel'
import type { Sensor } from '../lib/api'

const onlineSensor: Sensor = {
  id: 1,
  external_device_id: 'esp32-kedarnath-rain-01',
  village_id: 1,
  village_name: 'Kedarnath',
  sensor_type: 'rainfall',
  status: 'online',
  last_seen_at: '2026-09-04T09:12:57Z',
  seconds_since_last_seen: 12,
  battery_pct: null,
  last_value: 13.8,
  last_unit: 'mm/hr',
  last_reading_source: 'simulated',
  authenticated: true,
  fallback_value: null,
  fallback_unit: null,
  fallback_source: null,
}

describe('SensorPanel', () => {
  it('shows a loading state while sensor data is in flight', () => {
    render(<SensorPanel sensors={null} error={false} />)
    expect(screen.getByText(/loading sensor network/i)).toBeInTheDocument()
  })

  it('shows an honest error state on failure', () => {
    render(<SensorPanel sensors={null} error={true} />)
    expect(screen.getByText(/unreachable/i)).toBeInTheDocument()
  })

  it('never fabricates a reading for a node with no data yet', () => {
    const offline: Sensor = { ...onlineSensor, status: 'offline', last_value: null, last_unit: null, seconds_since_last_seen: null }
    render(<SensorPanel sensors={[offline]} error={false} />)
    expect(screen.getByText('esp32-kedarnath-rain-01')).toBeInTheDocument()
    expect(screen.getByText('offline')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.getByText(/never reported/i)).toBeInTheDocument()
  })

  it('renders a real value and status for an online node', () => {
    render(<SensorPanel sensors={[onlineSensor]} error={false} />)
    expect(screen.getByText('online')).toBeInTheDocument()
    expect(screen.getByText('13.8 mm/hr')).toBeInTheDocument()
  })

  it('discloses that the current data path uses a simulated publisher', () => {
    render(<SensorPanel sensors={[onlineSensor]} error={false} />)
    expect(screen.getByText(/simulator publishes the values/i)).toBeInTheDocument()
  })

  it('shows a keyed badge for a sensor with a real API key on file', () => {
    render(<SensorPanel sensors={[onlineSensor]} error={false} />)
    expect(screen.getByText('keyed')).toBeInTheDocument()
  })

  it('honestly shows "no key" for a not-yet-rotated sensor, never hiding the gap', () => {
    const keyless: Sensor = { ...onlineSensor, authenticated: false }
    render(<SensorPanel sensors={[keyless]} error={false} />)
    expect(screen.getByText('no key')).toBeInTheDocument()
  })

  it('shows a real regional estimate, clearly labelled, when a sensor has no live reading of its own', () => {
    const offlineWithFallback: Sensor = {
      ...onlineSensor,
      status: 'offline',
      last_value: null,
      last_unit: null,
      seconds_since_last_seen: null,
      fallback_value: 2.3,
      fallback_unit: 'mm/hr',
      fallback_source: 'derived',
    }
    render(<SensorPanel sensors={[offlineWithFallback]} error={false} />)
    expect(screen.getByText(/~2\.3 mm\/hr \(regional est\.\)/)).toBeInTheDocument()
    // Must never render a bare dash once a real fallback value exists.
    expect(screen.queryByText('—')).not.toBeInTheDocument()
  })

  it('still shows an honest dash when neither a live reading nor a fallback is available', () => {
    const trulyEmpty: Sensor = {
      ...onlineSensor,
      status: 'offline',
      last_value: null,
      last_unit: null,
      seconds_since_last_seen: null,
      fallback_value: null,
      fallback_source: null,
    }
    render(<SensorPanel sensors={[trulyEmpty]} error={false} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})

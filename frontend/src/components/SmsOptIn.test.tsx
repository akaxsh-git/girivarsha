import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SmsOptIn } from './SmsOptIn'
import * as api from '../lib/api'

vi.mock('../lib/api')

beforeEach(() => {
  vi.mocked(api.subscribeToSmsAlerts).mockReset()
})

describe('SmsOptIn', () => {
  it('disables the submit button until a phone number is entered', () => {
    render(<SmsOptIn villageId={1} language="en" />)
    expect(screen.getByRole('button', { name: /text me alerts/i })).toBeDisabled()
  })

  it('submits the entered number for the given village and shows a success message', async () => {
    const user = userEvent.setup()
    vi.mocked(api.subscribeToSmsAlerts).mockResolvedValue({
      village_id: 1,
      phone_number: '+919812345678',
      status: 'subscribed',
    })

    render(<SmsOptIn villageId={1} language="en" />)
    await user.type(screen.getByPlaceholderText(/phone number/i), '+919812345678')
    await user.click(screen.getByRole('button', { name: /text me alerts/i }))

    expect(api.subscribeToSmsAlerts).toHaveBeenCalledWith(1, '+919812345678')
    await waitFor(() => expect(screen.getByText(/saved/i)).toBeInTheDocument())
  })

  it('shows a distinct message when already subscribed, not a false "saved" claim', async () => {
    const user = userEvent.setup()
    vi.mocked(api.subscribeToSmsAlerts).mockResolvedValue({
      village_id: 1,
      phone_number: '+919812345678',
      status: 'already_subscribed',
    })

    render(<SmsOptIn villageId={1} language="en" />)
    await user.type(screen.getByPlaceholderText(/phone number/i), '+919812345678')
    await user.click(screen.getByRole('button', { name: /text me alerts/i }))

    await waitFor(() => expect(screen.getByText(/already opted in/i)).toBeInTheDocument())
  })

  it('shows an honest error state on failure, never a false success', async () => {
    const user = userEvent.setup()
    vi.mocked(api.subscribeToSmsAlerts).mockRejectedValue(new api.ApiError('bad request'))

    render(<SmsOptIn villageId={1} language="en" />)
    await user.type(screen.getByPlaceholderText(/phone number/i), '123')
    await user.click(screen.getByRole('button', { name: /text me alerts/i }))

    await waitFor(() => expect(screen.getByText(/could not save/i)).toBeInTheDocument())
  })

  it('always shows the honest delivery caveat, in both languages', () => {
    const { rerender } = render(<SmsOptIn villageId={1} language="en" />)
    expect(screen.getByText(/depends on whether a real sms gateway is configured/i)).toBeInTheDocument()

    rerender(<SmsOptIn villageId={1} language="hi" />)
    expect(screen.getByText(/वास्तविक SMS गेटवे कॉन्फ़िगर है/)).toBeInTheDocument()
  })
})

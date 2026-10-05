import { useState, type FormEvent } from 'react'
import { subscribeToSmsAlerts } from '../lib/api'

type Language = 'en' | 'hi'
type Status = 'idle' | 'submitting' | 'done' | 'error'

interface SmsOptInProps {
  villageId: number
  language: Language
}

const COPY: Record<Language, Record<string, string>> = {
  en: {
    heading: "Get an SMS if this village's risk becomes ORANGE or RED",
    placeholder: 'Phone number, e.g. +919812345678',
    button: 'Text me alerts',
    buttonBusy: 'Saving…',
    caveat:
      'Delivery depends on whether a real SMS gateway is configured on this server — by default, requests are only logged for testing, not actually sent as a text message.',
    successSubscribed:
      "Saved — this number will be alerted for this village's ORANGE/RED alerts (if a real SMS provider is configured).",
    successAlready: 'This number is already opted in for this village.',
    error: 'Could not save this right now — check the number and try again.',
  },
  hi: {
    heading: 'यदि इस गाँव का जोखिम ऑरेंज या रेड हो जाए तो SMS पाएं',
    placeholder: 'फ़ोन नंबर, जैसे +919812345678',
    button: 'मुझे SMS भेजें',
    buttonBusy: 'सहेजा जा रहा है…',
    caveat:
      'डिलीवरी इस पर निर्भर करती है कि सर्वर पर वास्तविक SMS गेटवे कॉन्फ़िगर है या नहीं — डिफ़ॉल्ट रूप से, अनुरोध केवल परीक्षण के लिए लॉग किए जाते हैं, वास्तव में टेक्स्ट संदेश के रूप में नहीं भेजे जाते।',
    successSubscribed:
      'सहेजा गया — यदि वास्तविक SMS प्रदाता कॉन्फ़िगर है, तो इस नंबर को इस गाँव के ऑरेंज/रेड अलर्ट के लिए सूचित किया जाएगा।',
    successAlready: 'यह नंबर इस गाँव के लिए पहले से ही जुड़ा हुआ है।',
    error: 'अभी इसे सहेजा नहीं जा सका — नंबर जांचें और फिर से प्रयास करें।',
  },
}

/**
 * Reach follow-up (user-requested): a real, working SMS opt-in form on the
 * citizen card. Calls the real POST /notifications/subscribe endpoint
 * (backend/app/api/routes/notifications.py) — there is nothing fabricated
 * about the subscription itself, but actual message DELIVERY depends on
 * whether a real SMS gateway is configured server-side (see
 * app/providers/notification.py); the caveat text below says so
 * explicitly rather than implying a text message is guaranteed to arrive.
 */
export function SmsOptIn({ villageId, language }: SmsOptInProps) {
  const [phone, setPhone] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [resultText, setResultText] = useState<string | null>(null)
  const c = COPY[language]

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = phone.trim()
    if (!trimmed) return
    setStatus('submitting')
    try {
      const result = await subscribeToSmsAlerts(villageId, trimmed)
      setStatus('done')
      setResultText(result.status === 'already_subscribed' ? c.successAlready : c.successSubscribed)
    } catch {
      setStatus('error')
      setResultText(c.error)
    }
  }

  return (
    <form className="sms-optin" onSubmit={handleSubmit}>
      <div className="sms-optin-heading">{c.heading}</div>
      <div className="sms-optin-row">
        <input
          type="tel"
          inputMode="tel"
          className="sms-optin-input"
          placeholder={c.placeholder}
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          disabled={status === 'submitting'}
          aria-label={c.heading}
        />
        <button type="submit" className="sms-optin-button" disabled={status === 'submitting' || !phone.trim()}>
          {status === 'submitting' ? c.buttonBusy : c.button}
        </button>
      </div>
      <div className="sms-optin-caveat">{c.caveat}</div>
      {resultText && (
        <div className={status === 'error' ? 'sms-optin-result sms-optin-result-error' : 'sms-optin-result'}>
          {resultText}
        </div>
      )}
    </form>
  )
}

import { useEffect, useState } from 'react'
import { getVillages, getRiskForVillage, type Village, type RiskDetail } from '../lib/api'
import { SmsOptIn } from '../components/SmsOptIn'

type LoadState = 'idle' | 'loading' | 'error'
type Language = 'en' | 'hi'

const LANGUAGE_STORAGE_KEY = 'girivarsha-citizen-language'

// Reach follow-up (user-requested): a Hindi toggle for the one view real
// end-users (not officials) actually read, since English-only plain-
// language copy is a real barrier for the population this app is meant to
// serve. English stays the default in every case (first load, and if
// localStorage is unavailable/empty) so nothing here changes existing
// behavior for anyone who doesn't touch the toggle.
function loadStoredLanguage(): Language {
  try {
    const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY)
    return stored === 'hi' ? 'hi' : 'en'
  } catch {
    return 'en'
  }
}

function storeLanguage(lang: Language): void {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang)
  } catch {
    // Private-browsing/storage-disabled — the toggle still works for this
    // page view, it just won't be remembered next visit. Not worth
    // surfacing as an error to a villager checking a flood warning.
  }
}

// Plain-language framing per risk band, in both languages. Deliberately
// advisory, never a command — Girivarsha is decision-support, not an
// authority that issues evacuation orders (see docs/Limitations.md and the
// standing disclaimer). English strings here are unchanged from before the
// language toggle existed — CitizenView.test.tsx asserts on several of
// them verbatim.
const LEVEL_COPY: Record<Language, Record<string, { headline: string; guidance: string; className: string }>> = {
  en: {
    LOW: {
      headline: 'No unusual risk detected',
      guidance:
        'Conditions look normal right now. This can change quickly during heavy rain — recheck if the weather turns.',
      className: 'citizen-low',
    },
    MODERATE: {
      headline: 'Conditions are being watched',
      guidance:
        'Rainfall and soil-moisture signals are elevated. Stay aware of local weather updates and official guidance.',
      className: 'citizen-moderate',
    },
    HIGH: {
      headline: 'Elevated risk — pay close attention',
      guidance:
        'Signals indicate meaningfully higher risk. Follow guidance from local authorities and be ready to act if they advise it.',
      className: 'citizen-high',
    },
    CRITICAL: {
      headline: 'Highest risk level on this scale',
      guidance:
        'This is the highest band this prototype tracks. Follow instructions from local disaster-management authorities — this app does not issue evacuation orders itself.',
      className: 'citizen-critical',
    },
  },
  hi: {
    LOW: {
      headline: 'कोई असामान्य जोखिम नहीं पाया गया',
      guidance: 'अभी स्थिति सामान्य दिखाई दे रही है। भारी बारिश के दौरान यह जल्दी बदल सकती है — मौसम बदलने पर दोबारा जांचें।',
      className: 'citizen-low',
    },
    MODERATE: {
      headline: 'स्थिति पर नज़र रखी जा रही है',
      guidance: 'वर्षा और मिट्टी-नमी के संकेत बढ़े हुए हैं। स्थानीय मौसम अपडेट और आधिकारिक मार्गदर्शन से अवगत रहें।',
      className: 'citizen-moderate',
    },
    HIGH: {
      headline: 'बढ़ा हुआ जोखिम — पूरा ध्यान दें',
      guidance:
        'संकेत काफी अधिक जोखिम दिखा रहे हैं। स्थानीय अधिकारियों के मार्गदर्शन का पालन करें और उनके सुझाव पर कार्रवाई के लिए तैयार रहें।',
      className: 'citizen-high',
    },
    CRITICAL: {
      headline: 'इस पैमाने पर उच्चतम जोखिम स्तर',
      guidance:
        'यह इस प्रोटोटाइप द्वारा ट्रैक किया गया उच्चतम स्तर है। स्थानीय आपदा-प्रबंधन अधिकारियों के निर्देशों का पालन करें — यह ऐप स्वयं निकासी के आदेश जारी नहीं करता।',
      className: 'citizen-critical',
    },
  },
}

const GLOF_TIER_LABEL: Record<Language, Record<string, string>> = {
  en: { LOW: 'LOW', MODERATE: 'MODERATE', HIGH: 'HIGH', CRITICAL: 'CRITICAL' },
  hi: { LOW: 'निम्न', MODERATE: 'मध्यम', HIGH: 'उच्च', CRITICAL: 'अति गंभीर' },
}

const STRINGS: Record<Language, Record<string, string>> = {
  en: {
    pageTitle: 'Is my village at risk right now?',
    pageSub: 'Choose your village to see current flash-flood and landslide conditions in plain language.',
    yourVillage: 'Your village',
    loadingVillages: 'Loading villages…',
    villageListUnreachable: 'Village list unreachable — backend/DB may be down.',
    checkingConditions: 'Checking current conditions…',
    riskInfoUnreachable: 'Risk information unreachable — backend/DB may be down.',
    confidencePrefix: 'Confidence in this reading: ',
    currentlyLimited: ' (currently limited — see below)',
    leadTimePrefix: 'If conditions worsen upstream, this village may see roughly ',
    leadTimeUnit: 'minute',
    leadTimeUnitPlural: 'minutes',
    leadTimeSuffix:
      ' of warning before it arrives here — a rough, prototype estimate, not a guarantee (see the note below).',
    glacialLakePrefix: 'Nearest real, satellite-mapped glacial lake: roughly ',
    glacialLakeUnit: 'km',
    glacialLakeSuffix: ' away — background context only, not part of the reading above.',
    glofPrefix: 'Glacial hazard context (nearby glacial lake + glacier melt rate combined): ',
    glofSuffix:
      ' — a background indicator, not a percentage chance of a flash flood, and not part of the reading above.',
    scsCnPrefix:
      "Using this village's real soil and land-cover data and a standard hydrology method (SCS-CN), about ",
    scsCnUnit: 'mm',
    scsCnSuffix:
      ' of the current rain is estimated to run off rather than soak in — a separate physical estimate, not part of the score above, and not a prediction of flooding by itself.',
    rainfallThresholdExceeded:
      'Current rainfall intensity has already reached levels that a published regional study associates with triggering shallow landslides in this area — background context, not part of the score above.',
    rainfallThresholdApproachingPrefix: 'At the current rainfall rate, levels historically associated with landslides in this region could be reached in roughly ',
    rainfallThresholdHourUnit: 'h',
    rainfallThresholdApproachingSuffix:
      ' if it continues at this rate — based on a published regional rainfall-threshold study, not a forecast, and not part of the score above.',
    disclaimerIntro: 'This is a prototype decision-support tool, not an official government warning.',
    disclaimerMixed:
      ' It is currently using a mix of live weather data and simulated inputs — confidence above reflects exactly that mix, not a claim of full accuracy.',
    disclaimerSimulatedOnly:
      ' It is currently fed by simulated rainfall and soil-moisture readings, not live sensors — that is why confidence is capped low.',
    disclaimerOfficial: ' For official warnings, follow IMD, NDMA SACHET, and your local disaster-management authority.',
    disclaimerLeadTimeCaveat:
      ' The warning-time estimate above is a rough prototype — straight-line distance to the nearest upstream village divided by one assumed flow speed, not real river-course routing or a validated model. Treat it as order-of-magnitude, not a promise.',
    disclaimerOfficials:
      ' Officials wanting the full technical breakdown, including the exact distance and village used, can use the Authority dashboard.',
  },
  hi: {
    pageTitle: 'क्या मेरे गाँव में अभी खतरा है?',
    pageSub: 'अपना गाँव चुनें और अचानक बाढ़ व भूस्खलन की मौजूदा स्थिति आसान भाषा में देखें।',
    yourVillage: 'आपका गाँव',
    loadingVillages: 'गाँव लोड हो रहे हैं…',
    villageListUnreachable: 'गाँवों की सूची उपलब्ध नहीं है — बैकएंड/डेटाबेस बंद हो सकता है।',
    checkingConditions: 'वर्तमान स्थिति जांची जा रही है…',
    riskInfoUnreachable: 'जोखिम जानकारी उपलब्ध नहीं है — बैकएंड/डेटाबेस बंद हो सकता है।',
    confidencePrefix: 'इस रीडिंग में विश्वास स्तर: ',
    currentlyLimited: ' (फिलहाल सीमित — नीचे देखें)',
    leadTimePrefix: 'यदि ऊपरी क्षेत्र में स्थिति बिगड़ती है, तो इस गाँव को लगभग ',
    leadTimeUnit: 'मिनट',
    leadTimeUnitPlural: 'मिनट',
    leadTimeSuffix: ' की चेतावनी मिल सकती है — यह एक अनुमानित प्रोटोटाइप अनुमान है, गारंटी नहीं (नीचे टिप्पणी देखें)।',
    glacialLakePrefix: 'निकटतम वास्तविक, सैटेलाइट-मैप्ड हिमनद झील: लगभग ',
    glacialLakeUnit: 'किमी',
    glacialLakeSuffix: ' दूर — यह केवल पृष्ठभूमि संदर्भ है, ऊपर दी गई रीडिंग का हिस्सा नहीं।',
    glofPrefix: 'हिमनद खतरा संदर्भ (निकटवर्ती हिमनद झील + हिमनद पिघलने की दर सम्मिलित): ',
    glofSuffix: ' — यह एक पृष्ठभूमि संकेतक है, फ्लैश फ्लड की प्रतिशत संभावना नहीं, और ऊपर दी गई रीडिंग का हिस्सा नहीं।',
    scsCnPrefix:
      'इस गाँव के वास्तविक मिट्टी और भू-आवरण डेटा और एक मानक जल विज्ञान पद्धति (SCS-CN) का उपयोग करते हुए, वर्तमान वर्षा का लगभग ',
    scsCnUnit: 'मिमी',
    scsCnSuffix:
      ' भाग रिसने के बजाय बह जाने का अनुमान है — यह ऊपर दिए गए स्कोर से अलग एक भौतिक अनुमान है, और अपने आप में बाढ़ की भविष्यवाणी नहीं है।',
    rainfallThresholdExceeded:
      'वर्तमान वर्षा की तीव्रता पहले ही उस स्तर तक पहुँच चुकी है जिसे एक प्रकाशित क्षेत्रीय अध्ययन इस क्षेत्र में भूस्खलन शुरू होने से जोड़ता है — यह पृष्ठभूमि संदर्भ है, ऊपर दिए गए स्कोर का हिस्सा नहीं।',
    rainfallThresholdApproachingPrefix: 'वर्तमान वर्षा दर पर, इस क्षेत्र में भूस्खलन से जुड़े ऐतिहासिक स्तर लगभग ',
    rainfallThresholdHourUnit: 'घंटे',
    rainfallThresholdApproachingSuffix:
      ' में पहुँच सकते हैं यदि यह दर जारी रहती है — यह एक प्रकाशित क्षेत्रीय वर्षा-सीमा अध्ययन पर आधारित है, पूर्वानुमान नहीं, और ऊपर दिए गए स्कोर का हिस्सा नहीं।',
    disclaimerIntro: 'यह एक प्रोटोटाइप निर्णय-सहायता उपकरण है, कोई आधिकारिक सरकारी चेतावनी नहीं।',
    disclaimerMixed:
      ' वर्तमान में यह लाइव मौसम डेटा और सिम्युलेटेड इनपुट के मिश्रण का उपयोग कर रहा है — ऊपर दिया गया विश्वास स्तर ठीक उसी मिश्रण को दर्शाता है, पूर्ण सटीकता का दावा नहीं।',
    disclaimerSimulatedOnly:
      ' यह वर्तमान में सिम्युलेटेड वर्षा और मिट्टी-नमी रीडिंग से संचालित है, लाइव सेंसर से नहीं — इसीलिए विश्वास स्तर कम रखा गया है।',
    disclaimerOfficial: ' आधिकारिक चेतावनियों के लिए, IMD, NDMA SACHET, और अपने स्थानीय आपदा-प्रबंधन प्राधिकरण का अनुसरण करें।',
    disclaimerLeadTimeCaveat:
      ' ऊपर दिया गया चेतावनी-समय अनुमान एक मोटा प्रोटोटाइप है — निकटतम ऊपरी गाँव की सीधी दूरी को एक अनुमानित प्रवाह गति से विभाजित किया गया है, यह वास्तविक नदी-मार्ग रूटिंग या एक सत्यापित मॉडल नहीं है। इसे मोटा अनुमान मानें, वादा नहीं।',
    disclaimerOfficials:
      ' पूर्ण तकनीकी विवरण चाहने वाले अधिकारी, जिसमें सटीक दूरी और उपयोग किया गया गाँव शामिल है, अथॉरिटी डैशबोर्ड का उपयोग कर सकते हैं।',
  },
}

/**
 * The public-facing view (Phase 6-7): pick your village, see one plain-
 * language card. No raw driver tables, no jargon — that detail lives in
 * AuthorityView for officials who need it. Still built on the exact same
 * real GET /risk/{village_id} endpoint, so nothing shown here is a
 * different (or friendlier-looking) number than what the authority
 * dashboard shows — just less of it, and explained in words.
 *
 * Reach follow-up (user-requested): an English/Hindi toggle (default
 * English, so every existing behavior/test is unchanged unless a visitor
 * actively switches it) and an SMS opt-in (see components/SmsOptIn.tsx) —
 * a web dashboard alone doesn't reach someone without a data connection,
 * which is the realistic case for a lot of this app's intended audience.
 */
export function CitizenView() {
  const [villages, setVillages] = useState<Village[]>([])
  const [villagesState, setVillagesState] = useState<LoadState>('loading')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<RiskDetail | null>(null)
  const [detailState, setDetailState] = useState<LoadState>('idle')
  const [language, setLanguage] = useState<Language>(loadStoredLanguage)

  useEffect(() => {
    const controller = new AbortController()
    getVillages(controller.signal)
      .then((v) => {
        setVillages(v)
        setVillagesState('idle')
        if (v.length > 0) setSelectedId(v[0].id)
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setVillagesState('error')
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (selectedId === null) return
    const controller = new AbortController()
    setDetailState('loading')
    getRiskForVillage(selectedId, controller.signal)
      .then((d) => {
        setDetail(d)
        setDetailState('idle')
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setDetailState('error')
      })
    return () => controller.abort()
  }, [selectedId])

  function changeLanguage(lang: Language) {
    setLanguage(lang)
    storeLanguage(lang)
  }

  const t = STRINGS[language]
  const copy = detail ? LEVEL_COPY[language][detail.risk_level] : null

  // Whether ANY input feeding this reading is real (Phase 9-10: opt-in real
  // weather providers) vs. every input being simulated — read from the same
  // real drivers payload the Authority dashboard shows in full, not a
  // separate/friendlier number. Loosely typed on purpose: `drivers` is a
  // passthrough JSON blob (see RiskDetail in lib/api.ts).
  const driverComponents =
    (detail?.drivers as { components?: { source?: string }[] } | undefined)?.components ?? []
  const anyRealInput = driverComponents.some((c) => c.source === 'real')

  return (
    <main className="citizen-main">
      <div className="citizen-hero">
        <div>
          <h1 className="page-title">{t.pageTitle}</h1>
          <p className="page-sub">{t.pageSub}</p>
        </div>
      <div className="lang-toggle" role="group" aria-label="Language / भाषा">
        <button
          type="button"
          className={language === 'en' ? 'lang-toggle-btn active' : 'lang-toggle-btn'}
          onClick={() => changeLanguage('en')}
        >
          English
        </button>
        <button
          type="button"
          className={language === 'hi' ? 'lang-toggle-btn active' : 'lang-toggle-btn'}
          onClick={() => changeLanguage('hi')}
        >
          हिन्दी
        </button>
      </div>
      </div>

      <div className="citizen-picker">
        <label htmlFor="village-select">{t.yourVillage}</label>
        {villagesState === 'error' ? (
          <p className="catchment-empty">{t.villageListUnreachable}</p>
        ) : (
          <select
            id="village-select"
            value={selectedId ?? ''}
            onChange={(e) => setSelectedId(Number(e.target.value))}
            disabled={villages.length === 0}
          >
            {villages.length === 0 && <option>{t.loadingVillages}</option>}
            {/* Phase 11: villages can now come from more than one real pilot
                valley — group them by region so picking the right "Reni" or
                "Joshimath" is unambiguous, rather than one flat list that
                silently mixes two unrelated valleys together. */}
            {Object.entries(
              villages.reduce<Record<string, Village[]>>((groups, v) => {
                const key = v.region_name ?? 'Other'
                ;(groups[key] ??= []).push(v)
                return groups
              }, {}),
            ).map(([regionName, vs]) => (
              <optgroup key={regionName} label={regionName}>
                {vs.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name} ({v.district})
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        )}
      </div>

      <div className="section">
        {detailState === 'error' ? (
          <p className="catchment-empty">{t.riskInfoUnreachable}</p>
        ) : detailState === 'loading' || !detail || !copy ? (
          <p className="catchment-empty">{t.checkingConditions}</p>
        ) : (
          <div className={`citizen-card ${copy.className}`}>
            <div className="citizen-village-name">{detail.village_name}</div>
            <div className="citizen-headline">{copy.headline}</div>
            <div className="citizen-guidance">{copy.guidance}</div>
            <div className="citizen-meta">
              {t.confidencePrefix}
              {detail.confidence_pct.toFixed(0)}%
              {detail.confidence_pct < 50 && t.currentlyLimited}
            </div>
            {detail.lead_time_minutes !== null && (
              <div className="citizen-meta citizen-lead-time">
                {t.leadTimePrefix}
                <strong>
                  {detail.lead_time_minutes} {detail.lead_time_minutes === 1 ? t.leadTimeUnit : t.leadTimeUnitPlural}
                </strong>
                {t.leadTimeSuffix}
              </div>
            )}
            {detail.glacial_lake_distance_km != null && (
              <div className="citizen-meta citizen-glacial-lake">
                {t.glacialLakePrefix}
                <strong>
                  {detail.glacial_lake_distance_km.toFixed(1)} {t.glacialLakeUnit}
                </strong>
                {t.glacialLakeSuffix}
              </div>
            )}
            {detail.glof_contribution_pct != null && (
              <div className="citizen-meta citizen-glof-indicator">
                {t.glofPrefix}
                <strong>{GLOF_TIER_LABEL[language][detail.glof_contribution_tier ?? ''] ?? detail.glof_contribution_tier}</strong>{' '}
                ({detail.glof_contribution_pct.toFixed(0)}%){t.glofSuffix}
              </div>
            )}
            {detail.scs_cn_runoff_depth_mm != null && (
              <div className="citizen-meta citizen-scs-cn">
                {t.scsCnPrefix}
                <strong>
                  {detail.scs_cn_runoff_depth_mm.toFixed(1)} {t.scsCnUnit}
                </strong>
                {t.scsCnSuffix}
              </div>
            )}
            {detail.rainfall_threshold_status === 'threshold_exceeded' && (
              <div className="citizen-meta citizen-rainfall-threshold">{t.rainfallThresholdExceeded}</div>
            )}
            {detail.rainfall_threshold_status === 'approaching_within_24h' &&
              detail.rainfall_threshold_hours_to_threshold != null && (
                <div className="citizen-meta citizen-rainfall-threshold">
                  {t.rainfallThresholdApproachingPrefix}
                  <strong>
                    {detail.rainfall_threshold_hours_to_threshold.toFixed(1)}
                    {t.rainfallThresholdHourUnit}
                  </strong>
                  {t.rainfallThresholdApproachingSuffix}
                </div>
              )}

            {selectedId !== null && <SmsOptIn villageId={selectedId} language={language} />}
          </div>
        )}
      </div>

      <div className="section citizen-disclaimer-block">
        <p>
          {t.disclaimerIntro}
          {anyRealInput ? t.disclaimerMixed : t.disclaimerSimulatedOnly} {t.disclaimerOfficial}
          {detail?.lead_time_minutes !== null && detail ? t.disclaimerLeadTimeCaveat : ''} {t.disclaimerOfficials}
        </p>
      </div>
    </main>
  )
}

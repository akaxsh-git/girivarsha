import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import { BackendStatus } from './components/BackendStatus'
import { CitizenView } from './views/CitizenView'
import { AuthorityView } from './views/AuthorityView'
import { IconHome, IconLogomark, IconShield } from './components/Icons'

/**
 * Phase 6-7: the single shared homepage from Phases 1-5 is now two real
 * routes sharing one header/shell — CitizenView (plain-language, public)
 * and AuthorityView (full technical detail, for district officials/DM
 * cell staff). Both call the same real backend endpoints; the split is
 * presentation-only, not a different data path or a friendlier set of
 * numbers for one audience.
 */
export default function App() {
  return (
    <BrowserRouter>
      <div className="disclaimer">
        Prototype decision-support system — not an official government warning mechanism.
      </div>
      <header className="hero">
        <div className="hero-inner">
          <div className="eyebrow">Girivarsha · Flash-flood &amp; landslide prediction for hilly regions</div>
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <IconLogomark size={30} />
            Girivarsha
          </h1>
          <div className="subtitle">Hyper-Local Flash Flood &amp; Landslide Early Warning</div>
          <div className="tagline">Detect → Predict → Explain → Act</div>
          <BackendStatus />
          <nav className="view-tabs">
            <NavLink to="/" end className={({ isActive }) => (isActive ? 'view-tab active' : 'view-tab')}>
              <IconHome size={15} />
              Citizen view
            </NavLink>
            <NavLink to="/authority" className={({ isActive }) => (isActive ? 'view-tab active' : 'view-tab')}>
              <IconShield size={15} />
              Authority dashboard
            </NavLink>
          </nav>
        </div>
      </header>

      <Routes>
        <Route path="/" element={<CitizenView />} />
        <Route path="/authority" element={<AuthorityView />} />
      </Routes>
    </BrowserRouter>
  )
}

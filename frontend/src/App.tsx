import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import { BackendStatus } from './components/BackendStatus'
import { CitizenView } from './views/CitizenView'
import { AuthorityView } from './views/AuthorityView'
import { IconHome, IconLogomark, IconShield } from './components/Icons'

/**
 * Two routes sharing one shell: CitizenView (plain-language, public) and
 * AuthorityView (operational detail for district officials). Both call the
 * same backend endpoints; the split is presentation-only.
 */
export default function App() {
  return (
    <BrowserRouter>
      <div className="disclaimer">
        Prototype decision-support system — not an official government warning mechanism.
      </div>
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/" className="brand" aria-label="Girivarsha home">
            <IconLogomark size={26} />
            <span className="brand-text">
              <span className="brand-name">Girivarsha</span>
              <span className="brand-tag">Flash-flood &amp; landslide early warning</span>
            </span>
          </NavLink>
          <nav className="view-tabs" aria-label="Views">
            <NavLink to="/" end className={({ isActive }) => (isActive ? 'view-tab active' : 'view-tab')}>
              <IconHome size={15} />
              Citizen view
            </NavLink>
            <NavLink to="/authority" className={({ isActive }) => (isActive ? 'view-tab active' : 'view-tab')}>
              <IconShield size={15} />
              Authority dashboard
            </NavLink>
          </nav>
          <BackendStatus />
        </div>
      </header>

      <Routes>
        <Route path="/" element={<CitizenView />} />
        <Route path="/authority" element={<AuthorityView />} />
      </Routes>

      <footer className="site-footer">
        Girivarsha · Weather data from Open-Meteo and NASA POWER · Map data © OpenStreetMap contributors ·
        Decision support only — always follow official guidance from your district administration.
      </footer>
    </BrowserRouter>
  )
}

import { useEffect, useRef, useState } from 'react'
import { NavLink, Link, Route, Routes, useLocation } from 'react-router-dom'
import { LayoutDashboard, Search, Globe, FilePenLine, Bookmark, Settings, Moon, Sun, Menu, X, PanelLeftClose, PanelLeftOpen, ArrowRight, RefreshCw, Laptop } from 'lucide-react'
import { Brand } from './components/Brand'
import { useHealth } from './hooks/useHealth'
import { useTheme } from './hooks/useTheme'
import { Overview, FindLeads } from './pages/Workspace'
import { SavedLeads, LeadDetail } from './pages/Leads'
import { ProposalStudio } from './pages/ProposalStudio'
import { IntelligenceDetail, IntelligenceList } from './pages/Intelligence'
import { WebsiteAudit } from './pages/WebsiteAudit'
import { API_TARGET } from './services/api'

const navigation = [
  { path: '/', title: 'Overview', icon: LayoutDashboard },
  { path: '/find-leads', title: 'Find Leads', icon: Search },
  { path: '/website-audit', title: 'Website Audit', icon: Globe },
  { path: '/proposal-studio', title: 'Proposal Studio', icon: FilePenLine },
  { path: '/saved-leads', title: 'Saved Leads', icon: Bookmark },
  { path: '/settings', title: 'Settings', icon: Settings },
]

export default function App() {
  const location = useLocation()
  const theme = useTheme()
  const health = useHealth()
  const [collapsed, setCollapsed] = useState(false)
  const [drawer, setDrawer] = useState(false)
  const sidebar = useRef<HTMLElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  const main = useRef<HTMLElement>(null)
  const previousRoute = useRef(location.pathname)
  const title = navigation.find(item => item.path === location.pathname)?.title ?? (location.pathname.startsWith('/saved-leads/') ? 'Lead details' : 'Page not found')
  useEffect(() => {
    document.title = `${title} · ClientScout AI`
    setDrawer(false)
    if (previousRoute.current !== location.pathname) {
      previousRoute.current = location.pathname
      main.current?.focus({ preventScroll: true })
      window.scrollTo({ top: 0 })
    }
  }, [location.pathname, title])
  useEffect(() => {
    if (!drawer) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    sidebar.current?.querySelector<HTMLButtonElement>('.drawer-close')?.focus()
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setDrawer(false); menuButton.current?.focus() }
      if (event.key !== 'Tab') return
      const controls = sidebar.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled])')
      const visible = controls ? [...controls].filter(element => element.getClientRects().length) : []
      const first = visible[0], last = visible[visible.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    const resize = () => { if (window.innerWidth > 760) setDrawer(false) }
    document.addEventListener('keydown', keyboard)
    window.addEventListener('resize', resize)
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', keyboard); window.removeEventListener('resize', resize) }
  }, [drawer])
  function closeDrawer() { setDrawer(false); menuButton.current?.focus() }
  return <div className={`app-shell ${collapsed ? 'is-collapsed' : ''}`}>
    <a className="skip-link" href="#main">Skip to content</a>
    {drawer && <div className="drawer-overlay" onClick={closeDrawer} aria-hidden="true" />}
    <aside ref={sidebar} id="sidebar" className={`sidebar ${drawer ? 'is-open' : ''}`} role={drawer ? 'dialog' : undefined} aria-modal={drawer || undefined} aria-label="Workspace navigation">
      <div className="brand"><Brand /><div className="brand-copy"><strong>ClientScout <span>AI</span></strong><small>AI WORKSPACE</small></div><button className="icon-button drawer-close" aria-label="Close navigation" onClick={closeDrawer}><X size={20} /></button></div>
      <span className="nav-caption">WORKSPACE</span>
      <nav aria-label="Primary navigation">{navigation.map(({ path, title: label, icon: Icon }) => <NavLink key={path} to={path} end={path === '/'} title={collapsed ? label : undefined} aria-label={label}><Icon size={20} /><span>{label}</span></NavLink>)}</nav>
      <div className="sidebar-bottom"><div className="local-profile"><span className="profile-icon"><Laptop size={18} /></span><div><strong>Personal workspace</strong><small>Local · Single user</small></div></div><button className="collapse-button" onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-expanded={!collapsed}>{collapsed ? <PanelLeftOpen size={19} /> : <><PanelLeftClose size={19} /><span>Collapse sidebar</span></>}</button></div>
    </aside>
    <div className="workspace">
      <header className="header"><div className="header-left"><button ref={menuButton} className="icon-button menu-button" onClick={() => setDrawer(true)} aria-label="Open navigation" aria-expanded={drawer} aria-controls="sidebar"><Menu size={21} /></button><span className="breadcrumb-root">Workspace</span><span className="breadcrumb-slash">/</span><span>{title}</span></div><div className="header-actions"><span className={`connection ${health.status}`} role="status"><span className="status-dot" />{health.status === 'checking' ? 'Checking backend…' : health.status === 'connected' ? 'Backend connected' : 'Backend offline'}</span><button className="icon-button" onClick={theme.toggle} aria-label={`Switch to ${theme.theme === 'light' ? 'dark' : 'light'} theme`}>{theme.theme === 'light' ? <Moon size={20} /> : <Sun size={20} />}</button></div></header>
      <main ref={main} id="main" tabIndex={-1}>
        {health.status === 'offline' && <div className="connection-alert" role="alert"><span>Backend unavailable. Check that the backend is running and both servers use the same local configuration. {health.error}</span><button className="text-link" onClick={() => void health.check()}><RefreshCw size={16} />Retry</button></div>}
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/find-leads" element={<FindLeads />} />
          <Route path="/website-audit" element={<WebsiteAudit />} />
          <Route path="/proposal-studio" element={<ProposalStudio />} />
          <Route path="/saved-leads" element={<SavedLeads />} />
          <Route path="/saved-leads/intelligence" element={<IntelligenceList />} /><Route path="/saved-leads/intelligence/:type/:id" element={<IntelligenceDetail />} /><Route path="/saved-leads/:id" element={<LeadDetail />} />
          <Route path="/settings" element={<><div className="hero"><span className="eyebrow">MAKE YOURSELF AT HOME</span><h1>Settings</h1><p>A few simple preferences for your personal workspace.</p></div><section className="card settings-card"><h2>Appearance</h2><p>Choose a theme, or follow your device. Your choice is saved in this browser when local storage is available.</p><div className="theme-options" role="group" aria-label="Theme preference">{(['light', 'dark', 'system'] as const).map(option => <button key={option} className="secondary-button" aria-pressed={theme.preference === option} onClick={() => theme.setPreference(option)}>{option === 'light' ? <Sun size={18} /> : option === 'dark' ? <Moon size={18} /> : <Laptop size={18} />}{option[0].toUpperCase() + option.slice(1)}</button>)}</div></section><section className="card settings-card"><div className="section-top"><h2>Backend connection</h2><button className="secondary-button" disabled={health.status === 'checking'} onClick={() => void health.check()}><RefreshCw size={16} />{health.status === 'checking' ? 'Checking…' : 'Check connection'}</button></div><dl><div><dt>Endpoint</dt><dd><code>/api/health</code></dd></div><div><dt>Configured backend</dt><dd><code>{API_TARGET}</code></dd></div><div><dt>Status</dt><dd>{health.status}</dd></div>{health.data && <div><dt>API version</dt><dd>{health.data.version}</dd></div>}{health.checkedAt && <div><dt>Last checked</dt><dd>{health.checkedAt.toLocaleTimeString()}</dd></div>}</dl><p className="helper">Checked on opening, every 30 seconds and on request. A successful check confirms API reachability and the migrated local database. Port settings come from the shared local configuration; restart both servers after changes.</p></section><section className="card settings-card"><h2>Local workspace · Checkpoint 4</h2><p>Your Personal Freelance Intelligence Workspace</p><p>Leads, URL/CSV imports, statuses and notes are saved in your local SQLite database. Permitted URL audits and optional PageSpeed measurements are available in Website Audit. Attributed OpenStreetMap discovery is available in Find Leads. Public contact enrichment, evidence priority and reviewed draft preparation are available. Gemini is optional and configured only on the backend. API keys are never entered in this frontend.</p></section></>} />
          <Route path="*" element={<section className="card empty-state"><h1>Page not found</h1><p>This page is not part of your workspace.</p><Link to="/" className="secondary-button">Back to overview <ArrowRight size={16} /></Link></section>} />
        </Routes>
        <footer className="main-footer"><span>ClientScout AI</span><span>Local workspace · Made for your next opportunity</span></footer>
      </main>
    </div>
  </div>
}

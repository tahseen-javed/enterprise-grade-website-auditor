import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import {
  IconAudit, IconHealth, IconJobs, IconMenu, IconMoon, IconReport, IconSettings, IconSun,
  IconUpload,
} from './components/icons'
import { useApp } from './lib/store'
import Audits from './pages/Audits'
import Jobs from './pages/Jobs'
import Reports from './pages/Reports'
import Settings from './pages/Settings'
import SystemHealth from './pages/SystemHealth'
import Upload from './pages/Upload'

const NAV = [
  {
    label: 'Audits',
    items: [
      { to: '/audits', label: 'Website Audits', icon: IconAudit },
      { to: '/upload', label: 'New audit', icon: IconUpload },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/reports', label: 'Reports', icon: IconReport },
      { to: '/jobs', label: 'Jobs', icon: IconJobs },
      { to: '/settings', label: 'Settings', icon: IconSettings },
      { to: '/health', label: 'System Health', icon: IconHealth },
    ],
  },
]

const TITLES = {
  '/audits': ['Website Audits', 'What was measured on each site'],
  '/reports': ['Reports & exports', 'Audit reports and data exports'],
  '/jobs': ['Jobs', 'Start, pause, resume and retry'],
  '/upload': ['New audit', 'Audit a website URL'],
  '/settings': ['Settings', 'Scoring weights and engine configuration'],
  '/health': ['System Health', 'Every component, honestly reported'],
}

export default function App() {
  const { theme, setTheme, toasts, connected, runningJobs, jobs } = useApp()
  const [navOpen, setNavOpen] = useState(false)
  const location = useLocation()

  useEffect(() => setNavOpen(false), [location.pathname])

  const [title, subtitle] = TITLES[location.pathname] || ['Advanced Website Auditor', '']
  const activeJob = jobs.find((j) => runningJobs.includes(j.id))

  const cycleTheme = () =>
    setTheme(theme === 'light' ? 'dark' : theme === 'dark' ? 'system' : 'light')

  const counts = jobs.reduce((acc, j) => acc + (j.counts?.completed || 0), 0)

  return (
    <div className="app">
      {navOpen && <div className="overlay" onClick={() => setNavOpen(false)} style={{ zIndex: 39 }} />}

      <aside className={`sidebar${navOpen ? ' open' : ''}`}>
        <div className="sidebar-brand">
          <span className="mark">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 15l5-6 4 4 6-7" />
            </svg>
          </span>
          <div style={{ minWidth: 0 }}>
            <div className="name">Advanced Website Auditor</div>
            <div className="ver">Premium site audits</div>
          </div>
        </div>

        <nav className="nav">
          {NAV.map((section) => (
            <div className="nav-section" key={section.label}>
              <div className="nav-label">{section.label}</div>
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
                >
                  <item.icon size={16} />
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="row xsmall muted" style={{ gap: 7 }}>
            <span className={`dot ${connected ? 'dot-live' : 'dot-danger'}`} />
            <span>{connected ? 'Live stream connected' : 'Reconnecting…'}</span>
          </div>
          {activeJob && (
            <div className="xsmall muted" style={{ marginTop: 5 }}>
              Running: {activeJob.name.slice(0, 30)}
            </div>
          )}
          {!activeJob && counts > 0 && (
            <div className="xsmall muted" style={{ marginTop: 5 }}>
              {counts.toLocaleString()} sites audited
            </div>
          )}
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button className="btn btn-ghost btn-icon mobile-toggle" onClick={() => setNavOpen((v) => !v)} aria-label="Menu">
            <IconMenu size={17} />
          </button>
          <div style={{ minWidth: 0 }}>
            <h1>{title}</h1>
            {subtitle && <div className="sub">{subtitle}</div>}
          </div>
          <div className="topbar-actions">
            <button
              className="btn btn-ghost btn-icon"
              onClick={cycleTheme}
              title={`Theme: ${theme}. Click to change.`}
              aria-label="Toggle theme"
            >
              {theme === 'dark' ? <IconMoon size={16} /> : theme === 'light' ? <IconSun size={16} /> : <IconSun size={16} style={{ opacity: 0.55 }} />}
            </button>
          </div>
        </header>

        <main>
          <Routes>
            <Route path="/" element={<Navigate to="/audits" replace />} />
            <Route path="/audits" element={<Audits />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/upload" element={<Upload />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/health" element={<SystemHealth />} />
            <Route path="*" element={<Navigate to="/audits" replace />} />
          </Routes>
        </main>
      </div>

      <div className="toast-wrap">
        {toasts.map((t) => (
          <div key={t.id} className={`toast${t.kind === 'err' ? ' err' : ''}`}>
            {t.message}
          </div>
        ))}
      </div>
    </div>
  )
}

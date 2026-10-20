import { FolderGit2, KeyRound, LayoutDashboard, ListChecks, Moon, Search, Settings, Sun } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useState } from 'react'
import { NavLink } from 'react-router'
import { getApiKey } from '../../api/apiKey'
import { useReadiness } from '../../api/hooks'
import { spring } from '../../lib/motion'
import { switchTheme, useTheme } from '../../lib/theme'
import { useHotkey } from '../../lib/useHotkey'
import { AnimatedOutlet } from '../motion/AnimatedOutlet'
import { TopLoader } from '../motion/TopLoader'
import { CommandPalette } from './CommandPalette'

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/repositories', label: 'Repositories', icon: FolderGit2, end: false },
  { to: '/jobs', label: 'Jobs', icon: ListChecks, end: false },
  { to: '/settings', label: 'Settings', icon: Settings, end: false },
]

/** Sidebar navigation, a top bar (search, API status, theme) and the page in between, over a
 * slowly drifting background. */
export function AppShell() {
  const [paletteOpen, setPaletteOpen] = useState(false)
  const theme = useTheme()
  const readiness = useReadiness()
  const openPalette = useCallback(() => setPaletteOpen(true), [])
  useHotkey('k', openPalette)

  const healthy = readiness.data?.ok
  const healthLabel = readiness.isPending ? 'Checking the API…' : healthy ? 'API ready' : 'API not ready'
  const toggleTheme = (event: React.MouseEvent) =>
    switchTheme(theme === 'dark' ? 'light' : 'dark', { x: event.clientX, y: event.clientY })

  return (
    <div className="shell">
      <div className="backdrop" aria-hidden="true">
        <span className="blob a" />
        <span className="blob b" />
        <span className="blob c" />
        <span className="grid-dots" />
      </div>
      <TopLoader />
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">CE</span>
          CodeEvidence
        </div>
        <div className="nav-section">Workspace</div>
        <nav aria-label="Main" className="stack" style={{ gap: 2 }}>
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              {({ isActive }) => (
                <>
                  {isActive && <motion.span layoutId="nav-pill" className="nav-pill" transition={spring} />}
                  <Icon size={16} aria-hidden="true" />
                  {label}
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer small muted stack" style={{ gap: 6 }}>
          <span className="row">
            <span className={`health-dot ${readiness.isPending ? '' : healthy ? 'ok' : 'down'}`} aria-hidden="true" />
            {healthLabel}
          </span>
          {!getApiKey() && (
            <NavLink to="/settings" className="row link">
              <KeyRound size={13} aria-hidden="true" /> Add an API key
            </NavLink>
          )}
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button type="button" className="search-button" onClick={openPalette}>
            <Search size={15} aria-hidden="true" />
            Search pages, repositories, pull requests…
            <span className="kbd">⌘K</span>
          </button>
          <span className="grow" />
          <button type="button" className="btn ghost" onClick={toggleTheme} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>
            <AnimatePresence mode="wait" initial={false}>
              <motion.span
                key={theme}
                style={{ display: 'inline-flex' }}
                initial={{ rotate: -90, scale: 0.4, opacity: 0 }}
                animate={{ rotate: 0, scale: 1, opacity: 1 }}
                exit={{ rotate: 90, scale: 0.4, opacity: 0 }}
                transition={{ duration: 0.2 }}
              >
                {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
              </motion.span>
            </AnimatePresence>
          </button>
        </header>
        <main className="content">
          <AnimatedOutlet />
        </main>
      </div>
      <AnimatePresence>{paletteOpen && <CommandPalette onClose={() => setPaletteOpen(false)} />}</AnimatePresence>
    </div>
  )
}

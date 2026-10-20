import type { LucideIcon } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useRef, useState } from 'react'
import { panel, spring } from '../../lib/motion'

export type TabSpec = { id: string; label: string; icon?: LucideIcon; count?: number }

/** A tab list: click, or arrow keys to move between tabs (the WAI-ARIA tabs pattern). The
 * underline slides to the selected tab. */
export function TabBar({ tabs, active, onSelect, label }: { tabs: TabSpec[]; active: string; onSelect: (id: string) => void; label: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])

  function onKeyDown(event: React.KeyboardEvent, index: number) {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (!step) return
    const next = (index + step + tabs.length) % tabs.length
    refs.current[next]?.focus()
    onSelect(tabs[next].id)
  }

  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((tab, index) => {
        const Icon = tab.icon
        const selected = tab.id === active
        return (
          <button
            key={tab.id}
            ref={(element) => {
              refs.current[index] = element
            }}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={selected}
            aria-controls={`panel-${tab.id}`}
            tabIndex={selected ? 0 : -1}
            className="tab"
            onClick={() => onSelect(tab.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
          >
            {Icon && <Icon size={15} aria-hidden="true" />}
            {tab.label}
            {tab.count != null && <span className="tab-count">{tab.count}</span>}
            {selected && <motion.span layoutId={`tab-indicator:${label}`} className="tab-indicator" transition={spring} />}
          </button>
        )
      })}
    </div>
  )
}

/** The selected tab's content. It slides in from the side of the tab the user moved to. */
export function TabPanel({ id, index, children }: { id: string; index: number; children: React.ReactNode }) {
  // Remember the previous tab to know the direction (React's "store info from previous renders").
  const [last, setLast] = useState({ index, direction: 1 })
  if (last.index !== index) setLast({ index, direction: index > last.index ? 1 : -1 })

  return (
    <AnimatePresence mode="wait" initial={false} custom={last.direction}>
      <motion.div
        key={id}
        role="tabpanel"
        id={`panel-${id}`}
        aria-labelledby={`tab-${id}`}
        custom={last.direction}
        variants={panel}
        initial="enter"
        animate="center"
        exit="exit"
      >
        {children}
      </motion.div>
    </AnimatePresence>
  )
}

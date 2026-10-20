import { BarChart3, FolderGit2, GitPullRequest, LayoutDashboard, ListChecks, ListOrdered, Settings } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { motion } from 'motion/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { useOverview, useRepositories } from '../../api/hooks'
import { spring } from '../../lib/motion'

type Item = { group: string; label: string; detail?: string; to: string; icon: LucideIcon }

const PAGES: Item[] = [
  { group: 'Pages', label: 'Overview', to: '/', icon: LayoutDashboard },
  { group: 'Pages', label: 'Repositories', to: '/repositories', icon: FolderGit2 },
  { group: 'Pages', label: 'Review queue', detail: 'what to review first', to: '/queue', icon: ListOrdered },
  { group: 'Pages', label: 'Analytics', detail: 'how useful reviews are', to: '/analytics', icon: BarChart3 },
  { group: 'Pages', label: 'Jobs', to: '/jobs', icon: ListChecks },
  { group: 'Pages', label: 'Settings', to: '/settings', icon: Settings },
]

/** ⌘K: type to filter pages, repositories and notable PRs; arrows to move; Enter to open. */
export function CommandPalette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const repositories = useRepositories()
  const overview = useOverview()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => input.current?.focus(), [])

  const items = useMemo(() => {
    const all: Item[] = [
      ...PAGES,
      ...(repositories.data?.items ?? []).map((repository) => ({
        group: 'Repositories', label: repository.full_name, to: `/repositories/${repository.id}`, icon: FolderGit2,
      })),
      ...[...(overview.data?.riskiest ?? []), ...(overview.data?.recent_reviews ?? [])].map((pr) => ({
        group: 'Pull requests', label: pr.title, detail: `${pr.repository}#${pr.number}`, to: `/pull-requests/${pr.pull_request_id}`, icon: GitPullRequest,
      })),
    ]
    const seen = new Set<string>()
    const needle = query.trim().toLowerCase()
    return all.filter((item) => {
      if (seen.has(item.to)) return false
      seen.add(item.to)
      return !needle || `${item.label} ${item.detail ?? ''}`.toLowerCase().includes(needle)
    })
  }, [repositories.data, overview.data, query])

  const open = (item: Item | undefined) => {
    if (!item) return
    navigate(item.to)
    onClose()
  }
  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'Escape') onClose()
    if (event.key === 'ArrowDown') setActive((index) => Math.min(items.length - 1, index + 1))
    if (event.key === 'ArrowUp') setActive((index) => Math.max(0, index - 1))
    if (event.key === 'Enter') open(items[active])
  }

  return (
    <motion.div className="palette-backdrop" onMouseDown={onClose} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
      <motion.div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Search"
        onMouseDown={(event) => event.stopPropagation()}
        onKeyDown={onKeyDown}
        initial={{ opacity: 0, scale: 0.95, y: -12 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.97, y: -6, transition: { duration: 0.12 } }}
        transition={spring}
      >
        <input
          ref={input}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setActive(0)
          }}
          placeholder="Search pages, repositories, pull requests…"
          aria-label="Search"
        />
        <div className="palette-list" role="listbox">
          {items.length === 0 && <p className="muted" style={{ padding: 12 }}>No matches.</p>}
          {items.map((item, index) => (
            <div key={item.to}>
              {(index === 0 || items[index - 1].group !== item.group) && <div className="palette-group">{item.group}</div>}
              <motion.button
                type="button"
                role="option"
                aria-selected={index === active}
                className="palette-item"
                style={{ position: 'relative', zIndex: 0 }}
                onMouseEnter={() => setActive(index)}
                onClick={() => open(item)}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: Math.min(index, 12) * 0.02 }}
              >
                {index === active && (
                  <motion.span layoutId="palette-active" className="chip-pill" style={{ borderRadius: 8, borderColor: 'transparent' }} transition={spring} />
                )}
                <item.icon size={15} aria-hidden="true" />
                <span className="truncate grow">{item.label}</span>
                {item.detail && <span className="muted small">{item.detail}</span>}
              </motion.button>
            </div>
          ))}
        </div>
      </motion.div>
    </motion.div>
  )
}

import { ShieldCheck } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import type { Schemas } from '../../api/client'
import { spring } from '../../lib/motion'
import { Empty } from '../ui/States'
import { FindingCard } from './FindingCard'

const SEVERITIES = ['high', 'medium', 'low'] as const

/** All verified findings, filterable by severity and category. Filtering reflows the cards
 * smoothly: removed ones shrink away and the rest slide into place. */
export function FindingsTab({
  review,
  pullRequestId,
  onShowInDiff,
}: {
  review: Schemas['ReviewOut'] | null | undefined
  pullRequestId: number
  onShowInDiff: (path: string) => void
}) {
  const [severity, setSeverity] = useState<string | null>(null)
  const [category, setCategory] = useState<string | null>(null)
  if (!review) return <Empty icon={ShieldCheck} title="Not reviewed yet">Run an AI review to see findings.</Empty>

  const categories = [...new Set(review.findings.map((finding) => finding.category))].sort()
  const shown = review.findings.filter(
    (finding) => (!severity || finding.severity === severity) && (!category || finding.category === category),
  )
  const count = (value: string) => review.findings.filter((finding) => finding.severity === value).length
  const chip = (value: string | null, label: React.ReactNode) => (
    <button key={value ?? 'all'} type="button" className={`chip${severity === value ? ' active' : ''}`} aria-pressed={severity === value} onClick={() => setSeverity(value)}>
      {severity === value && <motion.span layoutId="severity-chip" className="chip-pill" transition={spring} />}
      {label}
    </button>
  )

  return (
    <div className="stack">
      <div className="row wrap" role="group" aria-label="Filter findings">
        {chip(null, `All ${review.findings.length}`)}
        {SEVERITIES.map((value) =>
          chip(
            value,
            <>
              <span className="swatch" style={{ background: `var(--${value})` }} /> {value} {count(value)}
            </>,
          ),
        )}
        <span className="grow" />
        <label className="row small muted">
          Category
          <select className="select" value={category ?? ''} onChange={(event) => setCategory(event.target.value || null)}>
            <option value="">All</option>
            {categories.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
      </div>
      <div className="alert info small">
        {review.dropped_findings === 0
          ? 'Nothing was dropped: every finding the model proposed was supported by the evidence.'
          : `${review.dropped_findings} more finding${review.dropped_findings === 1 ? ' was' : 's were'} proposed by the model and dropped: the evidence did not support ${review.dropped_findings === 1 ? 'it' : 'them'}.`}
      </div>
      {shown.length === 0 && <Empty icon={ShieldCheck} title="No findings here" />}
      <div className="stack">
        <AnimatePresence mode="popLayout" initial={false}>
          {shown.map((finding, index) => (
            <motion.div
              key={finding.id}
              layout
              initial={{ opacity: 0, y: 16, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1, transition: { ...spring, delay: index * 0.04 } }}
              exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.15 } }}
            >
              <FindingCard finding={finding} pullRequestId={pullRequestId} onShowInDiff={() => onShowInDiff(finding.path)} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  )
}

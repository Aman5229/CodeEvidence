import { Bot, FileDiff, ListOrdered, Loader2, Network, ShieldCheck } from 'lucide-react'
import { motion } from 'motion/react'
import { Fragment, useEffect, useState } from 'react'
import { Link } from 'react-router'

const STAGES = [
  { label: 'Evidence', icon: FileDiff },
  { label: 'Related code', icon: Network },
  { label: 'Model', icon: Bot },
  { label: 'Verification', icon: ShieldCheck },
  { label: 'Ranking', icon: ListOrdered },
]

/** Shown while a review runs: the pipeline with light flowing through it, and real elapsed
 * time. It does not claim a current step: the worker does not report one. */
export function ReviewProgress({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const seconds = Math.max(0, Math.floor((now - since) / 1000))
  const elapsed = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`

  return (
    <motion.div
      className="card review-progress"
      role="status"
      initial={{ opacity: 0, height: 0, marginBottom: 0 }}
      animate={{ opacity: 1, height: 'auto', marginBottom: 16 }}
      exit={{ opacity: 0, height: 0, marginBottom: 0 }}
    >
      <div className="row">
        <Loader2 size={16} className="spin" aria-hidden="true" />
        <strong className="ai-label">AI review running</strong>
        <span className="muted small">{elapsed} elapsed</span>
        <span className="grow" />
        <Link to="/jobs" className="link small">Jobs</Link>
      </div>
      <div className="pipeline" aria-hidden="true">
        {STAGES.map(({ label, icon: Icon }, index) => (
          <Fragment key={label}>
            <motion.span className="stage" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.08 }}>
              <Icon size={13} /> {label}
            </motion.span>
            {index < STAGES.length - 1 && <span className="pipe" />}
          </Fragment>
        ))}
        <span className="scan-beam" />
      </div>
      <p className="muted small" style={{ margin: 0 }}>
        Collecting evidence, asking the model, then checking every finding against the code. This page updates by itself.
      </p>
    </motion.div>
  )
}

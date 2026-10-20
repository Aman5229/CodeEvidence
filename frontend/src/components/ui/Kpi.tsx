import type { LucideIcon } from 'lucide-react'
import { motion } from 'motion/react'
import { trackGlow } from '../../lib/glow'
import { hoverLift, item } from '../../lib/motion'

/** A headline number. Inside a `list` container it rises into place in turn. */
export function Kpi({ icon: Icon, label, value, hint }: { icon: LucideIcon; label: string; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <motion.div className="card kpi glow lift" variants={item} whileHover={hoverLift} onPointerMove={trackGlow}>
      <div className="kpi-label">
        <Icon size={14} aria-hidden="true" />
        {label}
      </div>
      <div className="kpi-value">{value}</div>
      {hint && <div className="kpi-hint">{hint}</div>}
    </motion.div>
  )
}

/** A GitHub avatar for a login (bots included). */
export function Avatar({ login, size = 'sm' }: { login: string | null | undefined; size?: 'sm' | 'lg' }) {
  if (!login) return <span className={`avatar ${size === 'lg' ? 'lg' : ''}`} aria-hidden="true" />
  const name = login.replace(/\[bot\]$/, '')
  return (
    <img
      className={`avatar ${size === 'lg' ? 'lg' : ''}`}
      src={`https://github.com/${encodeURIComponent(name)}.png?size=64`}
      alt=""
      loading="lazy"
    />
  )
}

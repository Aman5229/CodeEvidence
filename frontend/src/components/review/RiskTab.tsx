import { Brain, Gauge as GaugeIcon } from 'lucide-react'
import { motion } from 'motion/react'
import type { Schemas } from '../../api/client'
import { trackGlow } from '../../lib/glow'
import { formatPercent } from '../../lib/format'
import { item, list, softSpring } from '../../lib/motion'
import { Gauge } from '../charts/Charts'
import { AnimatedNumber } from '../motion/AnimatedNumber'
import { RiskBadge } from '../ui/Badges'
import { Empty } from '../ui/States'

/** The rule score with every reason, the trained model's view, and the inputs both used. */
export function RiskTab({ risk }: { risk: Schemas['RiskOut'] | null | undefined }) {
  if (!risk) return <Empty icon={GaugeIcon} title="Risk not computed yet">It is computed after the PR's files are synced.</Empty>
  const largest = Math.max(1, ...risk.reasons.map((reason) => Math.abs(reason.points)))
  const features = risk.features
  const rows: [string, string][] = [
    ['Files changed', String(features.files_changed)],
    ['Lines changed', String(features.lines_changed)],
    ['Size within the repository', `larger than ${formatPercent(features.size_percentile)} of its PRs`],
    ['Test files among the changes', formatPercent(features.test_file_ratio)],
    ['Documentation only', features.docs_only ? 'yes' : 'no'],
    ['Opened by a bot', features.is_bot ? 'yes' : 'no'],
  ]

  return (
    <motion.div className="grid two" variants={list} initial="hidden" animate="show">
      <motion.section variants={item} className="card glow" onPointerMove={trackGlow} aria-labelledby="rule-score">
        <div className="card-header">
          <h2 id="rule-score">Rule score</h2>
          <span className="badge outline">{risk.version}</span>
        </div>
        <div className="card-body stack">
          <div className="row" style={{ gap: 20 }}>
            <Gauge score={risk.score} level={risk.level} />
            <div>
              <RiskBadge level={risk.level} />
              <p className="muted small">Low below 30, medium from 30, high from 60. Every point comes from a reason below.</p>
            </div>
          </div>
          <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {risk.reasons.map((reason, index) => (
              <li key={reason.code} className="stack" style={{ gap: 4 }}>
                <div className="row">
                  <span className="grow">{reason.message}</span>
                  <strong style={{ color: reason.points > 0 ? 'var(--high)' : 'var(--low)' }}>
                    {reason.points > 0 ? '+' : ''}{reason.points}
                  </strong>
                </div>
                <div className="bar-track">
                  <motion.div
                    className={`bar-fill ${reason.points > 0 ? 'high' : 'low'}`}
                    style={{ width: `${(Math.abs(reason.points) / largest) * 100}%`, transformOrigin: 'left' }}
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: 1 }}
                    transition={{ ...softSpring, delay: 0.3 + index * 0.1 }}
                  />
                </div>
              </li>
            ))}
          </ul>
        </div>
      </motion.section>

      <motion.div variants={item} className="stack">
        <section className="card glow" onPointerMove={trackGlow} aria-labelledby="model-score">
          <div className="card-header">
            <h2 id="model-score" className="row"><Brain size={15} aria-hidden="true" /> ML model</h2>
            {risk.model && <span className="badge outline">{risk.model.version}</span>}
          </div>
          <div className="card-body">
            {risk.model ? (
              <div className="stack">
                <div className="gauge-value"><AnimatedNumber value={risk.model.probability} format="percent" /></div>
                <p className="muted" style={{ margin: 0 }}>
                  chance this PR is closed without being merged{risk.model.flagged ? ' · above the alert threshold' : ''}.
                  The probability is calibrated: of PRs scored about this high, about this share were not merged.
                </p>
              </div>
            ) : (
              <p className="muted" style={{ margin: 0 }}>No trained model is loaded, so only the rule score applies.</p>
            )}
          </div>
        </section>
        <section className="card" aria-labelledby="features">
          <div className="card-header"><h2 id="features">Inputs</h2></div>
          <table className="table">
            <tbody>
              {rows.map(([label, value]) => (
                <tr key={label}><td className="muted">{label}</td><td><strong>{value}</strong></td></tr>
              ))}
            </tbody>
          </table>
        </section>
      </motion.div>
    </motion.div>
  )
}

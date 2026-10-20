import { motion } from 'motion/react'
import { useState } from 'react'
import { formatPercent } from '../../lib/format'
import { softSpring } from '../../lib/motion'
import { useCountUp } from '../../lib/useCountUp'
import { AnimatedNumber } from '../motion/AnimatedNumber'

const integer = (value: number) => String(Math.round(value))
const LEVEL_COLOR: Record<string, string> = { low: 'var(--low)', medium: 'var(--medium)', high: 'var(--high)' }

export type Slice = { label: string; value: number; color: string }

/** A ring split into slices that sweep in one after another; hovering a slice or its legend
 * entry highlights it. The total counts up in the middle. */
export function Donut({ slices, centerLabel }: { slices: Slice[]; centerLabel: string }) {
  const [active, setActive] = useState<string | null>(null)
  const total = slices.reduce((sum, slice) => sum + slice.value, 0)
  const centerText = useCountUp(total, integer)
  const visible = slices.filter((slice) => slice.value > 0).length
  const fractions = slices.map((slice) => (total ? slice.value / total : 0))
  const segments = slices.map((slice, index) => ({
    ...slice,
    fraction: fractions[index],
    start: fractions.slice(0, index).reduce((sum, fraction) => sum + fraction, 0), // where this slice begins
  }))
  const dimmed = (label: string) => active !== null && active !== label

  return (
    <div className="row" style={{ gap: 28, flexWrap: 'wrap' }}>
      <svg width="150" height="150" viewBox="0 0 140 140" role="img" aria-label={`${centerLabel}: ${total}`}>
        <circle cx="70" cy="70" r="54" fill="none" stroke="var(--bg-elev-2)" strokeWidth="16" />
        {segments.map(
          (segment, index) =>
            segment.fraction > 0 && (
              <motion.circle
                key={segment.label}
                cx="70"
                cy="70"
                r="54"
                fill="none"
                stroke={segment.color}
                transform="rotate(-90 70 70)"
                initial={{ pathLength: 0, pathOffset: segment.start, strokeWidth: 16 }}
                animate={{
                  pathLength: Math.max(0.001, segment.fraction - (visible > 1 ? 0.008 : 0)),
                  pathOffset: segment.start,
                  strokeWidth: active === segment.label ? 21 : 16,
                  opacity: dimmed(segment.label) ? 0.3 : 1,
                }}
                transition={{
                  pathLength: { ...softSpring, delay: 0.15 + index * 0.14 },
                  strokeWidth: { duration: 0.2 },
                  opacity: { duration: 0.2 },
                }}
                onMouseEnter={() => setActive(segment.label)}
                onMouseLeave={() => setActive(null)}
                style={{ cursor: 'pointer' }}
              />
            ),
        )}
        <motion.text x="70" y="69" textAnchor="middle" fontSize="24" fontWeight="700" fill="var(--text)">
          {centerText}
        </motion.text>
        <text x="70" y="88" textAnchor="middle" fontSize="11" fill="var(--muted)">
          {centerLabel}
        </text>
      </svg>
      <div className="legend">
        {slices.map((slice) => (
          <motion.div
            key={slice.label}
            className="legend-item"
            animate={{ opacity: dimmed(slice.label) ? 0.45 : 1 }}
            onMouseEnter={() => setActive(slice.label)}
            onMouseLeave={() => setActive(null)}
          >
            <span className="swatch" style={{ background: slice.color }} />
            <span style={{ minWidth: 70 }}>{slice.label}</span>
            <strong><AnimatedNumber value={slice.value} /></strong>
            <span className="muted small">{formatPercent(total ? slice.value / total : 0)}</span>
          </motion.div>
        ))}
      </div>
    </div>
  )
}

/** A half-circle meter for a 0–100 score: the arc sweeps to the score, ticks mark the level
 * thresholds (30 and 60), and the number counts up. */
export function Gauge({ score, level }: { score: number; level: string }) {
  const text = useCountUp(score, integer)
  const tick = (value: number) => {
    const angle = Math.PI - (value / 100) * Math.PI
    const point = (radius: number) => [100 + radius * Math.cos(angle), 100 - radius * Math.sin(angle)]
    const [x1, y1] = point(66)
    const [x2, y2] = point(94)
    return <line key={value} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--border-strong)" strokeWidth="2" />
  }
  return (
    <svg width="200" height="116" viewBox="0 0 200 116" role="img" aria-label={`Risk score ${score} of 100, ${level}`}>
      <path d="M20 100 A80 80 0 0 1 180 100" fill="none" stroke="var(--bg-elev-2)" strokeWidth="14" strokeLinecap="round" />
      <motion.path
        d="M20 100 A80 80 0 0 1 180 100"
        fill="none"
        stroke={LEVEL_COLOR[level] ?? 'var(--accent)'}
        strokeWidth="14"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: Math.max(0, Math.min(100, score)) / 100 }}
        transition={{ ...softSpring, delay: 0.15 }}
        style={{ filter: `drop-shadow(0 0 6px ${LEVEL_COLOR[level] ?? 'var(--accent)'})` }}
      />
      {[30, 60].map(tick)}
      <motion.text x="100" y="92" textAnchor="middle" fontSize="34" fontWeight="700" fill="var(--text)">
        {text}
      </motion.text>
      <text x="100" y="112" textAnchor="middle" fontSize="11" fill="var(--muted)">
        of 100
      </text>
    </svg>
  )
}

/** A small ring for a 0–100 score, for headers. */
export function ScoreRing({ score, level }: { score: number; level: string }) {
  const text = useCountUp(score, integer)
  return (
    <svg width="46" height="46" viewBox="0 0 46 46" role="img" aria-label={`Risk ${score} of 100, ${level}`}>
      <circle cx="23" cy="23" r="18" fill="none" stroke="var(--bg-elev-2)" strokeWidth="4" />
      <motion.circle
        cx="23"
        cy="23"
        r="18"
        fill="none"
        stroke={LEVEL_COLOR[level] ?? 'var(--accent)'}
        strokeWidth="4"
        strokeLinecap="round"
        transform="rotate(-90 23 23)"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: Math.max(0, Math.min(100, score)) / 100 }}
        transition={{ ...softSpring, delay: 0.25 }}
      />
      <motion.text x="23" y="27.5" textAnchor="middle" fontSize="13" fontWeight="700" fill="var(--text)">
        {text}
      </motion.text>
    </svg>
  )
}

/** GitHub-style five blocks: green for additions, red for deletions. */
export function ChangeBar({ additions, deletions }: { additions: number; deletions: number }) {
  const total = additions + deletions
  const added = total ? Math.round((additions / total) * 5) : 0
  const removed = total ? Math.min(5 - added, Math.round((deletions / total) * 5)) : 0
  return (
    <span className="change-bar" aria-hidden="true">
      {Array.from({ length: 5 }, (_, index) => (
        <span key={index} className={index < added ? 'add' : index < added + removed ? 'del' : ''} />
      ))}
    </span>
  )
}

/** A labelled bar for a share between 0 and 1 that grows when it scrolls into view. */
export function ShareBar({ label, value, tone }: { label: string; value: number | null | undefined; tone?: string }) {
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row">
        <span className="grow">{label}</span>
        <strong>{value == null ? '—' : <AnimatedNumber value={value} format="percent" />}</strong>
      </div>
      <div className="bar-track">
        <motion.div
          className={`bar-fill ${tone ?? ''}`}
          style={{ width: formatPercent(value ?? 0), transformOrigin: 'left' }}
          initial={{ scaleX: 0 }}
          whileInView={{ scaleX: 1 }}
          viewport={{ once: true }}
          transition={softSpring}
        />
      </div>
    </div>
  )
}

export type FunnelStage = { label: string; value: number; color: string; hint?: string }

/** Stages that narrow down (proposed → verified → useful), each bar growing in turn. */
export function Funnel({ stages }: { stages: FunnelStage[] }) {
  const largest = Math.max(1, ...stages.map((stage) => stage.value))
  return (
    <div className="funnel">
      {stages.map((stage, index) => (
        <div key={stage.label} className="funnel-row">
          <div>
            <div>{stage.label}</div>
            {stage.hint && <div className="muted small">{stage.hint}</div>}
          </div>
          <div className="funnel-track">
            <motion.div
              className="funnel-fill"
              style={{ width: `${(stage.value / largest) * 100}%`, background: stage.color }}
              initial={{ scaleX: 0 }}
              whileInView={{ scaleX: 1 }}
              viewport={{ once: true }}
              transition={{ ...softSpring, delay: 0.1 + index * 0.18 }}
            />
          </div>
          <strong style={{ textAlign: 'right', fontSize: 18 }}>
            <AnimatedNumber value={stage.value} />
          </strong>
        </div>
      ))}
    </div>
  )
}

export type RadarSeries = { label: string; color: string; values: (number | null)[] }

/** A spider chart for values between 0 and 1 on a few axes: each series is a polygon that grows
 * out of the centre. A missing value (null) is drawn at 0 and marked with a hollow dot. */
export function Radar({ axes, series, label }: { axes: string[]; series: RadarSeries[]; label: string }) {
  const size = 320
  const center = size / 2
  const radius = 112
  const at = (index: number, value: number) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * index) / axes.length
    return [center + radius * value * Math.cos(angle), center + radius * value * Math.sin(angle)] as const
  }
  return (
    <div className="stack" style={{ gap: 8, alignItems: 'center' }}>
      <svg viewBox={`0 0 ${size} ${size}`} className="radar" role="img" aria-label={label}>
        {[0.25, 0.5, 0.75, 1].map((ring) => (
          <polygon key={ring} points={axes.map((_, index) => at(index, ring).join(',')).join(' ')} fill="none" stroke="var(--border)" />
        ))}
        {axes.map((axis, index) => {
          const [x, y] = at(index, 1)
          const [lx, ly] = at(index, 1.2)
          return (
            <g key={axis}>
              <line x1={center} y1={center} x2={x} y2={y} stroke="var(--border)" />
              <text x={lx} y={ly + 4} textAnchor={Math.abs(lx - center) < 8 ? 'middle' : lx > center ? 'start' : 'end'} fontSize="11.5" fill="var(--text-2)">
                {axis}
              </text>
            </g>
          )
        })}
        {series.map((entry, seriesIndex) => (
          <motion.g
            key={entry.label}
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ ...softSpring, delay: 0.15 + seriesIndex * 0.2 }}
            style={{ transformOrigin: `${center}px ${center}px` }}
          >
            <polygon
              points={entry.values.map((value, index) => at(index, value ?? 0).join(',')).join(' ')}
              fill={entry.color}
              fillOpacity={0.18}
              stroke={entry.color}
              strokeWidth={2}
            />
            {entry.values.map((value, index) => {
              const [x, y] = at(index, value ?? 0)
              return (
                <circle key={index} cx={x} cy={y} r={3.5} fill={value == null ? 'var(--bg)' : entry.color} stroke={entry.color}>
                  <title>{`${entry.label}, ${axes[index]}: ${value == null ? 'no data' : formatPercent(value)}`}</title>
                </circle>
              )
            })}
          </motion.g>
        ))}
      </svg>
      <div className="row small wrap" style={{ gap: 14 }}>
        {series.map((entry) => (
          <span key={entry.label} className="row"><span className="swatch" style={{ background: entry.color }} /> {entry.label}</span>
        ))}
      </div>
    </div>
  )
}

export type StackPart = { label: string; color: string }

/** Bars per period, each split into parts (e.g. findings shown and dropped), growing in turn. */
export function StackedBars({
  periods,
  parts,
  values,
  label,
}: {
  periods: string[]
  parts: StackPart[]
  values: number[][] // values[period][part]
  label: string
}) {
  const height = 160
  const bar = 18
  const gap = 12
  const width = Math.max(320, periods.length * (bar + gap) + gap)
  const largest = Math.max(1, ...values.map((row) => row.reduce((sum, value) => sum + value, 0)))
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div style={{ overflowX: 'auto' }}>
        <svg viewBox={`0 0 ${width} ${height + 24}`} width={width} height={height + 24} role="img" aria-label={label}>
          {periods.map((period, index) => {
            const x = gap + index * (bar + gap)
            let top = height
            return (
              <g key={period}>
                {parts.map((part, partIndex) => {
                  const value = values[index][partIndex]
                  const size = (value / largest) * (height - 8)
                  top -= size
                  return (
                    <motion.rect
                      key={part.label}
                      x={x}
                      y={top}
                      width={bar}
                      height={size}
                      rx={3}
                      fill={part.color}
                      initial={{ scaleY: 0 }}
                      animate={{ scaleY: 1 }}
                      transition={{ ...softSpring, delay: 0.05 + index * 0.04 }}
                      style={{ transformOrigin: `${x}px ${height}px` }}
                    >
                      <title>{`${period}: ${value} ${part.label}`}</title>
                    </motion.rect>
                  )
                })}
                {(index % Math.ceil(periods.length / 8) === 0 || index === periods.length - 1) && (
                  <text x={x + bar / 2} y={height + 16} textAnchor="middle" fontSize="10" fill="var(--muted)">{period}</text>
                )}
              </g>
            )
          })}
          <line x1={0} y1={height} x2={width} y2={height} stroke="var(--border)" />
        </svg>
      </div>
      <div className="row small wrap" style={{ gap: 14 }}>
        {parts.map((part) => <span key={part.label} className="row"><span className="swatch" style={{ background: part.color }} /> {part.label}</span>)}
      </div>
    </div>
  )
}

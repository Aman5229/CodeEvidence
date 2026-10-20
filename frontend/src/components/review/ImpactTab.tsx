import { Database, FileCode2, FlaskConical, Network, Radar } from 'lucide-react'
import { motion } from 'motion/react'
import { useState } from 'react'
import { Link } from 'react-router'
import type { Schemas } from '../../api/client'
import { useImpact } from '../../api/hooks'
import { item, list, softSpring } from '../../lib/motion'
import { Empty, ErrorMessage, Loading } from '../ui/States'

const SIZE = 560
const CENTER = SIZE / 2
const CHANGED_RING = 125
const DEPENDENT_RING = 228
const CHANGE_TONE: Record<string, string> = { removed: 'var(--high)', modified: 'var(--medium)', changed: 'var(--medium)', added: 'var(--low)' }
// More nodes than this on a ring and their labels would overlap: the name shows on hover instead
const MAX_LABELLED_CHANGED = 12
const MAX_LABELLED_DEPENDENTS = 18

type Point = { x: number; y: number; angle: number }

const basename = (path: string) => path.split('/').pop() ?? path
const around = (index: number, count: number, radius: number, start = -Math.PI / 2): Point => {
  const angle = start + (2 * Math.PI * index) / Math.max(count, 1)
  return { x: CENTER + radius * Math.cos(angle), y: CENTER + radius * Math.sin(angle), angle }
}

/** The colour of a changed file: removed code is the riskiest, then edits, then additions. */
function fileTone(file: Schemas['ChangedFileOut']): string {
  const changes = new Set(file.symbols.map((symbol) => symbol.change))
  for (const change of ['removed', 'modified', 'changed', 'added']) if (changes.has(change)) return CHANGE_TONE[change]
  return 'var(--muted)'
}

/** Places the files: changed ones on the inner ring, the code using them on the outer ring,
 * ordered by the direction of what they use so related nodes sit near each other. */
function layout(impact: Schemas['ImpactOut']) {
  const changed = new Map(impact.changed.map((file, index) => [file.path, around(index, impact.changed.length, CHANGED_RING)]))
  const direction = (dependent: Schemas['DependentFileOut']) => {
    const targets = dependent.changed_files.map((path) => changed.get(path)).filter((point): point is Point => !!point)
    const x = targets.reduce((sum, point) => sum + Math.cos(point.angle), 0)
    const y = targets.reduce((sum, point) => sum + Math.sin(point.angle), 0)
    return Math.atan2(y, x)
  }
  const ordered = [...impact.dependents].sort((a, b) => direction(a) - direction(b))
  const start = ordered.length ? direction(ordered[0]) : -Math.PI / 2
  const dependents = new Map(ordered.map((dependent, index) => [dependent.path, around(index, ordered.length, DEPENDENT_RING, start)]))
  return { changed, dependents }
}

function curve(from: Point, to: Point): string {
  const control = { x: (from.x + to.x) / 2 + (CENTER - (from.x + to.x) / 2) * 0.35, y: (from.y + to.y) / 2 + (CENTER - (from.y + to.y) / 2) * 0.35 }
  return `M${from.x},${from.y} Q${control.x},${control.y} ${to.x},${to.y}`
}

function Label({ point, text, offset }: { point: Point; text: string; offset: number }) {
  const right = Math.cos(point.angle) >= 0
  return (
    <text
      x={point.x + Math.cos(point.angle) * offset}
      y={point.y + Math.sin(point.angle) * offset + 4}
      textAnchor={Math.abs(Math.cos(point.angle)) < 0.2 ? 'middle' : right ? 'start' : 'end'}
      fontSize="11"
      fill="var(--text-2)"
      style={{ pointerEvents: 'none' }}
    >
      {text.length > 26 ? `${text.slice(0, 25)}…` : text}
    </text>
  )
}

/** Blast radius: the functions and classes this PR changes, and the code elsewhere that uses
 * them. Hover or focus a file to see its connections; click a changed file to open its diff. */
export function ImpactTab({ pullRequestId, repositoryId, onOpenFile }: { pullRequestId: number; repositoryId: number; onOpenFile: (path: string) => void }) {
  const impact = useImpact(pullRequestId)
  const [active, setActive] = useState<string | null>(null)
  if (impact.isPending) return <Loading what="the impact of this change" lines={5} />
  if (impact.isError) return <ErrorMessage error={impact.error} />
  const data = impact.data
  const symbols = data.changed.reduce((sum, file) => sum + file.symbols.length, 0)
  if (data.changed.length === 0) {
    return <Empty icon={Radar} title="No code files changed">Impact is computed for code files: configuration and documentation have no callers.</Empty>
  }

  const { changed, dependents } = layout(data)
  const neighbours = new Set<string>()
  if (active) {
    neighbours.add(active)
    for (const dependent of data.dependents) {
      if (dependent.path === active) dependent.changed_files.forEach((path) => neighbours.add(path))
      if (dependent.changed_files.includes(active)) neighbours.add(dependent.path)
    }
  }
  const dim = (path: string) => (active && !neighbours.has(path) ? 0.2 : 1)
  const focus = (path: string | null) => () => setActive(path)
  const labelChanged = data.changed.length <= MAX_LABELLED_CHANGED
  const labelDependents = data.dependents.length <= MAX_LABELLED_DEPENDENTS
  const activeChanged = data.changed.find((file) => file.path === active)
  const activeDependent = data.dependents.find((dependent) => dependent.path === active)

  return (
    <motion.div className="stack lg" variants={list} initial="hidden" animate="show">
      {!data.indexed && (
        <motion.div variants={item} className="alert info small">
          <Database size={15} aria-hidden="true" />
          <div>
            Only the changes are known: the repository's code is not indexed, so the code that uses them cannot be found.{' '}
            <Link to={`/repositories/${repositoryId}?tab=index`} className="link">Index the code</Link> to see the blast radius.
          </div>
        </motion.div>
      )}
      <motion.div variants={item} className="grid impact-layout">
        <section className="card" aria-labelledby="blast-title">
          <div className="card-header">
            <h2 id="blast-title" className="row"><Network size={15} aria-hidden="true" /> Blast radius</h2>
            <span className="muted small">
              {data.changed.length} changed files · {symbols} symbols · {data.dependents.length} files using them{data.truncated && ' (cut)'}
            </span>
          </div>
          <div className="card-body">
            <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="impact-graph" role="group" aria-label="Blast radius graph">
              <circle cx={CENTER} cy={CENTER} r={CHANGED_RING} className="ring" />
              <circle cx={CENTER} cy={CENTER} r={DEPENDENT_RING} className="ring" />
              {data.dependents.map((dependent) =>
                dependent.changed_files.map((path, index) => {
                  const from = dependents.get(dependent.path)
                  const to = changed.get(path)
                  if (!from || !to) return null
                  const lit = active === dependent.path || active === path
                  return (
                    <motion.path
                      key={`${dependent.path}->${path}`}
                      d={curve(from, to)}
                      fill="none"
                      stroke={dependent.is_test ? 'var(--info)' : 'var(--accent)'}
                      strokeWidth={lit ? 2.2 : 1.2}
                      initial={{ pathLength: 0, opacity: 0 }}
                      animate={{ pathLength: 1, opacity: active && !lit ? 0.08 : 0.55 }}
                      transition={{ pathLength: { ...softSpring, delay: 0.35 + index * 0.05 }, opacity: { duration: 0.2 } }}
                    />
                  )
                }),
              )}
              {data.changed.map((file) => {
                const point = changed.get(file.path)!
                return (
                  <motion.line
                    key={`spoke-${file.path}`}
                    x1={CENTER} y1={CENTER} x2={point.x} y2={point.y}
                    stroke="var(--border-strong)" strokeDasharray="3 4"
                    initial={{ opacity: 0 }} animate={{ opacity: dim(file.path) * 0.9 }}
                  />
                )
              })}
              <motion.g initial={{ scale: 0 }} animate={{ scale: 1 }} transition={softSpring} style={{ transformOrigin: `${CENTER}px ${CENTER}px` }}>
                <circle cx={CENTER} cy={CENTER} r={22} fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth="2" />
                <text x={CENTER} y={CENTER + 4} textAnchor="middle" fontSize="11" fontWeight="700" fill="var(--text)">PR</text>
              </motion.g>
              {data.changed.map((file, index) => {
                const point = changed.get(file.path)!
                const label = `${file.path}: ${file.symbols.length} changed symbols`
                return (
                  <motion.g
                    key={file.path}
                    role="button"
                    tabIndex={0}
                    aria-label={label}
                    className="impact-node"
                    onMouseEnter={focus(file.path)}
                    onMouseLeave={focus(null)}
                    onFocus={focus(file.path)}
                    onBlur={focus(null)}
                    onClick={() => onOpenFile(file.path)}
                    onKeyDown={(event) => event.key === 'Enter' && onOpenFile(file.path)}
                    initial={{ opacity: 0, scale: 0 }}
                    animate={{ opacity: dim(file.path), scale: 1 }}
                    transition={{ ...softSpring, delay: 0.1 + index * 0.05 }}
                    style={{ transformOrigin: `${point.x}px ${point.y}px` }}
                  >
                    <title>{label}</title>
                    <circle cx={point.x} cy={point.y} r={9 + Math.min(6, file.symbols.length)} fill={fileTone(file)} stroke="var(--bg)" strokeWidth="2" />
                    {labelChanged && <Label point={point} text={basename(file.path)} offset={20} />}
                  </motion.g>
                )
              })}
              {data.dependents.map((dependent, index) => {
                const point = dependents.get(dependent.path)!
                const label = `${dependent.path} uses ${dependent.uses.join(', ')}`
                return (
                  <motion.g
                    key={dependent.path}
                    role="button"
                    tabIndex={0}
                    aria-label={label}
                    className="impact-node"
                    onMouseEnter={focus(dependent.path)}
                    onMouseLeave={focus(null)}
                    onFocus={focus(dependent.path)}
                    onBlur={focus(null)}
                    initial={{ opacity: 0, scale: 0 }}
                    animate={{ opacity: dim(dependent.path), scale: 1 }}
                    transition={{ ...softSpring, delay: 0.3 + Math.min(index, 30) * 0.03 }}
                    style={{ transformOrigin: `${point.x}px ${point.y}px` }}
                  >
                    <title>{label}</title>
                    <circle cx={point.x} cy={point.y} r={6 + Math.min(5, dependent.uses.length)} fill={dependent.is_test ? 'var(--info)' : 'var(--accent)'} stroke="var(--bg)" strokeWidth="2" />
                    {labelDependents && <Label point={point} text={basename(dependent.path)} offset={14} />}
                  </motion.g>
                )
              })}
            </svg>
            <p className="impact-caption small" aria-live="polite">
              {activeChanged ? (
                <><code>{activeChanged.path}</code> · {activeChanged.symbols.map((symbol) => symbol.name).join(', ') || 'no functions or classes'}</>
              ) : activeDependent ? (
                <><code>{activeDependent.path}</code> uses {activeDependent.uses.join(', ')}</>
              ) : (
                <span className="muted">Hover or focus a file to see what it changes or uses.</span>
              )}
            </p>
            <div className="row small muted wrap" style={{ gap: 14, justifyContent: 'center' }}>
              <span className="row"><span className="swatch" style={{ background: 'var(--high)' }} /> removes code</span>
              <span className="row"><span className="swatch" style={{ background: 'var(--medium)' }} /> edits code</span>
              <span className="row"><span className="swatch" style={{ background: 'var(--low)' }} /> adds code</span>
              <span className="row"><span className="swatch" style={{ background: 'var(--accent)' }} /> uses it</span>
              <span className="row"><span className="swatch" style={{ background: 'var(--info)' }} /> a test uses it</span>
            </div>
          </div>
        </section>

        <div className="stack">
          <section className="card" aria-labelledby="changed-code">
            <div className="card-header"><h2 id="changed-code" className="row"><FileCode2 size={15} aria-hidden="true" /> Changed code</h2></div>
            <div className="card-body stack" style={{ gap: 10 }}>
              {data.changed.map((file) => (
                <div key={file.path} className="stack" style={{ gap: 4 }}>
                  <button type="button" className="tree-row" onClick={() => onOpenFile(file.path)} onMouseEnter={focus(file.path)} onMouseLeave={focus(null)}>
                    <code className="truncate">{file.path}</code>
                  </button>
                  <div className="row wrap" style={{ paddingLeft: 8, gap: 6 }}>
                    {file.symbols.length === 0 && <span className="muted small">no functions or classes found</span>}
                    {file.symbols.map((symbol) => (
                      <span key={symbol.name} className="symbol" style={{ borderColor: CHANGE_TONE[symbol.change] }} title={`${symbol.kind}, ${symbol.change}`}>
                        <code>{symbol.name}</code> <span className="muted">{symbol.change}</span>
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
          <section className="card" aria-labelledby="used-by">
            <div className="card-header"><h2 id="used-by" className="row"><Network size={15} aria-hidden="true" /> Used by</h2></div>
            <div className="card-body stack" style={{ gap: 10 }}>
              {data.indexed && data.dependents.length === 0 && (
                <span className="muted small">Nothing else in the indexed code mentions the changed functions and classes.</span>
              )}
              {!data.indexed && <span className="muted small">Index the code to find its users.</span>}
              {data.dependents.map((dependent) => (
                <div key={dependent.path} className="stack" style={{ gap: 4 }} onMouseEnter={focus(dependent.path)} onMouseLeave={focus(null)}>
                  <div className="row">
                    {dependent.is_test ? <FlaskConical size={13} aria-hidden="true" /> : <FileCode2 size={13} aria-hidden="true" />}
                    <code className="truncate grow">{dependent.path}</code>
                    {dependent.is_test && <span className="badge info">test</span>}
                  </div>
                  <div className="muted small" style={{ paddingLeft: 20 }}>
                    uses {dependent.uses.map((name) => <code key={name}>{name} </code>)}
                    in {dependent.chunks.map((chunk) => `${chunk.name ?? 'code'} (${chunk.start_line}-${chunk.end_line})`).join(', ')}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </motion.div>
    </motion.div>
  )
}

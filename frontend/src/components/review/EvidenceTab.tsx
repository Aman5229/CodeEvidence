import { Boxes, FileDiff, Fingerprint, Layers, Network } from 'lucide-react'
import { motion } from 'motion/react'
import type { Schemas } from '../../api/client'
import { item, list } from '../../lib/motion'
import { highlightLine, languageOf } from '../diff/highlight'
import { Empty } from '../ui/States'

const GROUPS = [
  { kind: 'signal', title: 'Rule signals', icon: Fingerprint, hint: 'Risky patterns found by plain rules: certain, cheap, never invented.' },
  { kind: 'hunk', title: 'Diff hunks', icon: FileDiff, hint: 'The change itself, with line numbers.' },
  { kind: 'function', title: 'Enclosing functions', icon: Layers, hint: 'The whole function around each change, at the PR head.' },
  { kind: 'related', title: 'Related code', icon: Network, hint: 'Found in the repository by hybrid search (vector + keyword).' },
] as const

/** Everything the model was shown, grouped by kind, and which findings cite each item. */
export function EvidenceTab({ review }: { review: Schemas['ReviewOut'] | null | undefined }) {
  if (!review) return <Empty icon={Boxes} title="No evidence yet">Run an AI review to see what the model is shown.</Empty>
  const citedBy = new Map<string, number>()
  for (const finding of review.findings) {
    for (const item of finding.evidence) citedBy.set(item.id, (citedBy.get(item.id) ?? 0) + 1)
  }

  return (
    <motion.div className="stack lg" variants={list} initial="hidden" animate="show">
      <motion.p variants={item} className="muted" style={{ margin: 0 }}>
        The model may only cite these items; a finding citing anything else is dropped. Items are kept in this order until the token budget is used.
      </motion.p>
      {GROUPS.map(({ kind, title, icon: Icon, hint }) => {
        const items = review.evidence.filter((item) => item.kind === kind)
        return (
          <motion.section key={kind} variants={item} className="stack" aria-label={title}>
            <div className="row">
              <Icon size={16} aria-hidden="true" />
              <h2>{title}</h2>
              <span className="tab-count">{items.length}</span>
              <span className="muted small">{hint}</span>
            </div>
            {items.length === 0 ? (
              <p className="muted small" style={{ margin: 0 }}>None for this PR.</p>
            ) : (
              items.map((item) => (
                <details key={item.id} className="evidence-item">
                  <summary>
                    <span className="badge accent">{item.id}</span>
                    {item.path ? (
                      <code className="truncate">
                        {item.path}
                        {item.start_line != null && `:${item.start_line}-${item.end_line}`}
                      </code>
                    ) : (
                      // a signal about the whole PR (e.g. missing tests) has no file: show its message
                      <span className="truncate">{item.text.split('\n')[0]}</span>
                    )}
                    <span className="grow" />
                    {citedBy.get(item.id) ? (
                      <span className="badge medium">cited by {citedBy.get(item.id)}</span>
                    ) : (
                      <span className="muted small">not cited</span>
                    )}
                  </summary>
                  {kind === 'hunk' || kind === 'signal' ? (
                    <pre>{item.text}</pre>
                  ) : (
                    <pre dangerouslySetInnerHTML={{ __html: highlightLine(item.text, item.path ? languageOf(item.path) : null) }} />
                  )}
                </details>
              ))
            )}
          </motion.section>
        )
      })}
    </motion.div>
  )
}

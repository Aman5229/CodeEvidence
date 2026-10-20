import { Check, ChevronDown, Code2, Copy, Lightbulb, MessageSquare, Send, ThumbsDown, ThumbsUp } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import type { Schemas } from '../../api/client'
import { useFeedback } from '../../api/hooks'
import { spring } from '../../lib/motion'
import { highlightLine, languageOf } from '../diff/highlight'
import { SeverityBadge } from '../ui/Badges'
import { useToast } from '../ui/toast'

const KIND_LABEL: Record<string, string> = { hunk: 'Diff hunk', function: 'Enclosing function', related: 'Related code', signal: 'Rule signal' }

/** A number that pops when it changes (a vote was just counted). */
function PopCount({ value }: { value: number }) {
  return (
    <AnimatePresence initial={false} mode="popLayout">
      <motion.span key={value} className="pop" initial={{ scale: 1.8, y: -4 }} animate={{ scale: 1, y: 0 }} transition={spring}>
        {value}
      </motion.span>
    </AnimatePresence>
  )
}

/** One review finding, as a review comment: claim, the quoted code, a suggested fix, the
 * evidence it stands on, and buttons to rate it. */
export function FindingCard({
  finding,
  pullRequestId,
  compact = false,
  onShowInDiff,
}: {
  finding: Schemas['FindingOut']
  pullRequestId: number
  compact?: boolean
  onShowInDiff?: () => void
}) {
  const feedback = useFeedback(pullRequestId)
  const toast = useToast()
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const language = languageOf(finding.path)

  const rate = (verdict: 'useful' | 'not_useful') =>
    feedback.mutate(
      { findingId: finding.id, verdict },
      {
        onSuccess: () => toast({ title: 'Feedback saved', description: verdict === 'useful' ? 'Marked as useful.' : 'Marked as not useful.' }),
        onError: () => toast({ tone: 'error', title: 'Could not save feedback', description: 'Try again in a moment.' }),
      },
    )
  const copySuggestion = async () => {
    if (!finding.suggestion || !navigator.clipboard) return
    await navigator.clipboard.writeText(finding.suggestion)
    setCopied(true)
    setTimeout(() => setCopied(false), 1600)
  }

  return (
    <article className={`finding ${finding.severity}`} aria-label={`${finding.severity} ${finding.category} finding`}>
      <header className="finding-head">
        <SeverityBadge severity={finding.severity} />
        <span className="badge outline">{finding.category}</span>
        {!compact && (
          <code className="muted truncate" title={`${finding.path}:${finding.line}`}>
            {finding.path}:{finding.line}
          </code>
        )}
        <span className="grow" />
        <span className="muted small nowrap">confidence {Math.round(finding.confidence * 100)}%</span>
        {finding.github_comment_id && (
          <span className="badge info" title="Posted as a comment on GitHub">
            <Send size={12} aria-hidden="true" /> posted
          </span>
        )}
        {onShowInDiff && (
          <button type="button" className="btn ghost sm" onClick={onShowInDiff}>
            <Code2 size={13} aria-hidden="true" /> View in diff
          </button>
        )}
      </header>
      <div className="finding-body">
        <p className="finding-claim" style={{ margin: 0 }}>{finding.claim}</p>
        {!compact && (
          <div className="code-block">
            <pre dangerouslySetInnerHTML={{ __html: highlightLine(finding.quote, language) }} />
          </div>
        )}
        {finding.suggestion && (
          <div className="suggestion" style={{ position: 'relative' }}>
            <div className="suggestion-head">
              <Lightbulb size={13} aria-hidden="true" /> Suggested fix
              <span className="grow" />
              <button type="button" className="btn ghost sm" onClick={copySuggestion} aria-label={copied ? 'Copied' : 'Copy suggestion'}>
                <AnimatePresence mode="wait" initial={false}>
                  <motion.span key={copied ? 'done' : 'copy'} initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.4, opacity: 0 }} transition={{ duration: 0.15 }} style={{ display: 'inline-flex' }}>
                    {copied ? <Check size={13} /> : <Copy size={13} />}
                  </motion.span>
                </AnimatePresence>
              </button>
            </div>
            <div className="suggestion-body">{finding.suggestion}</div>
          </div>
        )}
        <div>
          <button
            type="button"
            className="btn ghost sm muted"
            aria-expanded={evidenceOpen}
            onClick={() => setEvidenceOpen(!evidenceOpen)}
          >
            <motion.span animate={{ rotate: evidenceOpen ? 0 : -90 }} transition={spring} style={{ display: 'inline-flex' }}>
              <ChevronDown size={13} aria-hidden="true" />
            </motion.span>
            Evidence: {finding.evidence.map((item) => item.id).join(', ')}
          </button>
          <AnimatePresence initial={false}>
            {evidenceOpen && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
                style={{ overflow: 'hidden' }}
              >
                <div className="stack" style={{ paddingTop: 8, gap: 8 }}>
                  {finding.evidence.map((item) => (
                    <div key={item.id} className="evidence-item">
                      <div className="row small" style={{ padding: '6px 10px', background: 'var(--bg-elev-2)' }}>
                        <span className="badge accent">{item.id}</span>
                        <span>{KIND_LABEL[item.kind] ?? item.kind}</span>
                        {item.path && (
                          <code className="muted truncate">
                            {item.path}
                            {item.start_line != null && `:${item.start_line}-${item.end_line}`}
                          </code>
                        )}
                      </div>
                      <pre>{item.text}</pre>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <div className="feedback-bar">
          <span className="muted small">Was this useful?</span>
          <motion.button whileTap={{ scale: 0.85 }} type="button" className="btn ghost sm" disabled={feedback.isPending} onClick={() => rate('useful')} aria-label="Useful">
            <ThumbsUp size={13} aria-hidden="true" /> <PopCount value={finding.feedback.useful} />
          </motion.button>
          <motion.button whileTap={{ scale: 0.85 }} type="button" className="btn ghost sm" disabled={feedback.isPending} onClick={() => rate('not_useful')} aria-label="Not useful">
            <ThumbsDown size={13} aria-hidden="true" /> <PopCount value={finding.feedback.not_useful} />
          </motion.button>
          {finding.feedback.replies > 0 && (
            <span className="muted small row">
              <MessageSquare size={12} aria-hidden="true" /> {finding.feedback.replies} replies on GitHub
            </span>
          )}
        </div>
      </div>
    </article>
  )
}

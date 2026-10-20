import { ArrowUpRight, Bot, Check, ChevronDown, Code2, Copy, History, Lightbulb, MessageSquare, Send, ThumbsDown, ThumbsUp, Wand2 } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import type { Schemas } from '../../api/client'
import { useFeedback } from '../../api/hooks'
import { spring } from '../../lib/motion'
import { useCopy } from '../../lib/useCopy'
import { highlightLine, languageOf } from '../diff/highlight'
import { SeverityBadge } from '../ui/Badges'
import { useToast } from '../ui/toast'

const KIND_LABEL: Record<string, string> = {
  hunk: 'Diff hunk', function: 'Enclosing function', related: 'Related code', signal: 'Signal', learning: 'Learning',
  instruction: 'Path instruction', guideline: 'Repository guideline', question: 'Code found for the question',
}

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

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, copy] = useCopy()
  return (
    <button
      type="button"
      className="btn ghost sm"
      onClick={(event) => {
        event.preventDefault() // inside a <summary>: copy without toggling it
        void copy(text)
      }}
      aria-label={copied ? 'Copied' : label}
    >
      <AnimatePresence mode="wait" initial={false}>
        <motion.span key={copied ? 'done' : 'copy'} initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.4, opacity: 0 }} transition={{ duration: 0.15 }} style={{ display: 'inline-flex' }}>
          {copied ? <Check size={13} /> : <Copy size={13} />}
        </motion.span>
      </AnimatePresence>
    </button>
  )
}

/** The fix as a tiny diff: the line as it is, and what replaces it. */
function OneClickFix({ finding, commentUrl }: { finding: Schemas['FindingOut']; commentUrl: string | null }) {
  const language = languageOf(finding.path)
  const replacement = finding.replacement ?? ''
  return (
    <div className="fix">
      <div className="fix-head">
        <Wand2 size={13} aria-hidden="true" /> One-click fix
        <span className="muted small">line {finding.line}</span>
        <span className="grow" />
        <CopyButton text={replacement} label="Copy fix" />
        {commentUrl && (
          <a className="btn sm" href={commentUrl} target="_blank" rel="noreferrer" title="Open the comment on GitHub and click “Commit suggestion”">
            Commit on GitHub <ArrowUpRight size={13} aria-hidden="true" />
          </a>
        )}
      </div>
      <div className="fix-diff" role="table" aria-label="Suggested change">
        {finding.original_line != null && (
          <div role="row" className="fix-line removed">
            <span className="sign" role="cell">−</span>
            <code role="cell" dangerouslySetInnerHTML={{ __html: highlightLine(finding.original_line, language) }} />
          </div>
        )}
        {replacement.split('\n').map((line, index) => (
          <div key={index} role="row" className="fix-line added">
            <span className="sign" role="cell">+</span>
            <code role="cell" dangerouslySetInnerHTML={{ __html: highlightLine(line, language) }} />
          </div>
        ))}
      </div>
    </div>
  )
}

/** One review finding, as a review comment: claim, the quoted code, a suggested fix (one click
 * when the reviewer could write it), a prompt for an AI agent, the evidence it stands on, and
 * buttons to rate it. A "not useful" with a reason becomes a learning for future reviews. */
export function FindingCard({
  finding,
  pullRequestId,
  pullRequestUrl,
  compact = false,
  onShowInDiff,
}: {
  finding: Schemas['FindingOut']
  pullRequestId: number
  pullRequestUrl?: string | null
  compact?: boolean
  onShowInDiff?: () => void
}) {
  const feedback = useFeedback(pullRequestId)
  const toast = useToast()
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const language = languageOf(finding.path)
  const commentUrl = pullRequestUrl && finding.github_comment_id ? `${pullRequestUrl}#discussion_r${finding.github_comment_id}` : null

  const rate = (verdict: 'useful' | 'not_useful', why?: string) =>
    feedback.mutate(
      { findingId: finding.id, verdict, reason: why },
      {
        onSuccess: (saved) => {
          setRejecting(false)
          setReason('')
          const description = verdict === 'useful'
            ? 'Marked as useful.'
            : saved.learning_job_id
              ? 'Marked as not useful. Your reason is being turned into a learning for future reviews.'
              : 'Marked as not useful.'
          toast({ title: 'Feedback saved', description })
        },
        onError: () => toast({ tone: 'error', title: 'Could not save feedback', description: 'Try again in a moment.' }),
      },
    )

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
        {finding.carried_from_review_id && (
          <span className="badge outline" title="Found by an earlier review; this file has not changed since">
            <History size={12} aria-hidden="true" /> from review #{finding.carried_from_review_id}
          </span>
        )}
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
          <div className="suggestion">
            <div className="suggestion-head">
              <Lightbulb size={13} aria-hidden="true" /> Suggested fix
              <span className="grow" />
              <CopyButton text={finding.suggestion} label="Copy suggestion" />
            </div>
            <div className="suggestion-body">{finding.suggestion}</div>
          </div>
        )}
        {finding.replacement && <OneClickFix finding={finding} commentUrl={commentUrl} />}
        <details className="agent-prompt">
          <summary>
            <Bot size={13} aria-hidden="true" /> Prompt for AI agents
            <span className="grow" />
            <CopyButton text={finding.agent_prompt} label="Copy prompt" />
          </summary>
          <pre>{finding.agent_prompt}</pre>
        </details>
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
                        <span>{KIND_LABEL[item.kind] ?? item.kind}{item.id.startsWith('C') && ' (from an earlier review)'}</span>
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
          <motion.button
            whileTap={{ scale: 0.85 }}
            type="button"
            className={`btn ghost sm${rejecting ? ' active' : ''}`}
            disabled={feedback.isPending}
            onClick={() => setRejecting(!rejecting)}
            aria-label="Not useful"
            aria-expanded={rejecting}
          >
            <ThumbsDown size={13} aria-hidden="true" /> <PopCount value={finding.feedback.not_useful} />
          </motion.button>
          {finding.feedback.replies > 0 && (
            <span className="muted small row">
              <MessageSquare size={12} aria-hidden="true" /> {finding.feedback.replies} replies on GitHub
            </span>
          )}
        </div>
        <AnimatePresence initial={false}>
          {rejecting && (
            <motion.form
              className="reject-form"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
              onSubmit={(event) => {
                event.preventDefault()
                rate('not_useful', reason.trim() || undefined)
              }}
            >
              <label className="field">
                Why is it not useful? (optional)
                <textarea
                  className="input"
                  rows={2}
                  maxLength={2000}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="e.g. ids are validated by middleware before handlers run"
                />
              </label>
              <span className="muted small">A reason becomes a learning: future reviews of this repository avoid the same mistake.</span>
              <div className="row">
                <button type="submit" className="btn primary sm" disabled={feedback.isPending}>Save</button>
                <button type="button" className="btn ghost sm" onClick={() => setRejecting(false)}>Cancel</button>
              </div>
            </motion.form>
          )}
        </AnimatePresence>
      </div>
    </article>
  )
}

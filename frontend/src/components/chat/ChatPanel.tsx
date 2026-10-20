import { useQueryClient } from '@tanstack/react-query'
import { ArrowUp, FileCode2, MessageCircle, MessageSquare, Sparkles, Square, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { askQuestion } from '../../api/chat'
import type { Schemas } from '../../api/client'
import { useChatHistory } from '../../api/hooks'
import { formatDuration, formatUsd } from '../../lib/format'
import { spring } from '../../lib/motion'
import { ErrorMessage } from '../ui/States'
import { Markdown } from './Markdown'

const SUGGESTIONS = ['What does this change do?', 'What could break because of it?', 'Which tests cover the changed code?']

type Pending = { question: string; answer: string }
type Message = Schemas['ChatMessageOut']

/** Where a cited item is; click to open the file. */
function Citation({ citation, onOpenFile }: { citation: Schemas['CitationOut']; onOpenFile: (path: string) => void }) {
  const where = citation.path ? `${citation.path}${citation.start_line != null ? `:${citation.start_line}-${citation.end_line}` : ''}` : citation.kind
  return (
    <button type="button" className="source" onClick={() => citation.path && onOpenFile(citation.path)} title={`${citation.kind}: ${where}`}>
      <span className="badge accent">{citation.id}</span>
      <FileCode2 size={12} aria-hidden="true" />
      <span className="truncate">{where}</span>
    </button>
  )
}

function Bubble({ message, onOpenFile }: { message: Message; onOpenFile: (path: string) => void }) {
  if (message.role === 'user') {
    return (
      <motion.div className="bubble user" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={spring}>
        {message.source === 'github' && (
          <span className="muted small row"><MessageSquare size={12} aria-hidden="true" /> asked on GitHub{message.github_user && ` by @${message.github_user}`}</span>
        )}
        {message.content}
      </motion.div>
    )
  }
  const known = new Set(message.citations.map((citation) => citation.id))
  const first = new Map(message.citations.map((citation) => [citation.id, citation]))
  return (
    <motion.div className="bubble assistant" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={spring}>
      <Markdown text={message.content} known={known} onCite={(id) => { const path = first.get(id)?.path; if (path) onOpenFile(path) }} />
      {message.citations.length > 0 && (
        <div className="sources">
          {message.citations.map((citation) => <Citation key={citation.id} citation={citation} onOpenFile={onOpenFile} />)}
        </div>
      )}
      {message.model && (
        <span className="muted small">
          {message.model} · {message.latency_ms != null && formatDuration(message.latency_ms)} · {formatUsd(message.cost_usd ?? 0)}
        </span>
      )}
    </motion.div>
  )
}

/** "Ask CodeEvidence": a button that opens a conversation about this PR. Answers stream in
 * as they are written, cite the evidence they use, and keep earlier turns for follow-ups.
 * Questions asked with @codeevidence on GitHub show up here too. */
export function ChatPanel({ pullRequestId, onOpenFile }: { pullRequestId: number; onOpenFile: (path: string) => void }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<Pending | null>(null)
  const [error, setError] = useState<string | null>(null)
  const history = useChatHistory(pullRequestId)
  const queryClient = useQueryClient()
  const abort = useRef<AbortController | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const messages = history.data ?? []

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' }) // a block body: newer browsers return a Promise here
  }, [messages.length, pending?.answer, open])
  useEffect(() => () => abort.current?.abort(), [])

  async function send(question: string) {
    const text = question.trim()
    if (!text || pending) return
    setDraft('')
    setError(null)
    setPending({ question: text, answer: '' })
    const controller = new AbortController()
    abort.current = controller
    let finished = false
    try {
      await askQuestion(
        pullRequestId,
        text,
        (event) => {
          if (event.event === 'token') setPending((current) => current && { ...current, answer: current.answer + event.text })
          if (event.event === 'done') {
            finished = true
            queryClient.setQueryData<Message[]>(['chat', pullRequestId], (old) => [...(old ?? []), event.data.question, event.data.answer])
          }
          if (event.event === 'error') {
            finished = true
            setError(event.message)
          }
        },
        controller.signal,
      )
      if (!finished) setError('The answer was cut off. Try again.')
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'The question could not be sent')
    } finally {
      setPending(null)
      abort.current = null
    }
  }

  return (
    <>
      <AnimatePresence>
        {!open && (
          <motion.button
            type="button"
            className="chat-fab btn ai"
            onClick={() => setOpen(true)}
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            transition={spring}
          >
            <MessageCircle size={16} aria-hidden="true" /> Ask CodeEvidence
            {messages.length > 0 && <span className="tab-count">{messages.length / 2}</span>}
          </motion.button>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {open && (
          <motion.aside
            className="chat-panel"
            role="dialog"
            aria-label="Ask CodeEvidence"
            initial={{ x: '105%' }}
            animate={{ x: 0 }}
            exit={{ x: '105%' }}
            transition={spring}
            onKeyDown={(event) => event.key === 'Escape' && setOpen(false)}
          >
            <header className="chat-head">
              <span className="ai-label"><Sparkles size={14} aria-hidden="true" /> Ask CodeEvidence</span>
              <span className="grow" />
              <button type="button" className="btn ghost sm" onClick={() => setOpen(false)} aria-label="Close the chat">
                <X size={15} />
              </button>
            </header>
            <div className="chat-messages" aria-live="polite">
              {history.isError && <ErrorMessage error={history.error} />}
              {messages.length === 0 && !pending && (
                <div className="stack" style={{ gap: 8 }}>
                  <p className="muted small" style={{ margin: 0 }}>
                    Questions are answered from this PR's code and review evidence, with sources. On GitHub, mention @codeevidence in a comment.
                  </p>
                  {SUGGESTIONS.map((suggestion) => (
                    <button key={suggestion} type="button" className="chip" onClick={() => void send(suggestion)}>
                      {suggestion}
                    </button>
                  ))}
                </div>
              )}
              {messages.map((message) => <Bubble key={message.id} message={message} onOpenFile={onOpenFile} />)}
              {pending && (
                <>
                  <div className="bubble user">{pending.question}</div>
                  <div className="bubble assistant">
                    {pending.answer ? <Markdown text={pending.answer} /> : <span className="typing" aria-label="Writing"><span /><span /><span /></span>}
                  </div>
                </>
              )}
              {error && <div className="alert error small" role="alert">{error}</div>}
              <div ref={end} />
            </div>
            <form
              className="chat-input"
              onSubmit={(event) => {
                event.preventDefault()
                void send(draft)
              }}
            >
              <textarea
                className="input"
                rows={2}
                maxLength={2000}
                value={draft}
                placeholder="Ask about this pull request…"
                aria-label="Your question"
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    void send(draft)
                  }
                }}
              />
              {pending ? (
                <button type="button" className="btn" onClick={() => abort.current?.abort()} aria-label="Stop">
                  <Square size={14} />
                </button>
              ) : (
                <button type="submit" className="btn primary" disabled={!draft.trim()} aria-label="Send">
                  <ArrowUp size={15} />
                </button>
              )}
            </form>
          </motion.aside>
        )}
      </AnimatePresence>
    </>
  )
}

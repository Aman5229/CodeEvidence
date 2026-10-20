import { Check, GraduationCap, Pencil, Plus, Trash2, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import type { Schemas } from '../../api/client'
import { useAddLearning, useChangeLearning, useDeleteLearning, useLearnings } from '../../api/hooks'
import { timeAgo } from '../../lib/format'
import { item, list, spring } from '../../lib/motion'
import { Empty, ErrorMessage, Loading } from '../ui/States'
import { useToast } from '../ui/toast'

type Learning = Schemas['LearningOut']

const SOURCE_LABEL: Record<string, string> = { manual: 'written here', dashboard: 'from a 👎 reason', github: 'from GitHub' }
const MIN_CHARS = 10
const MAX_CHARS = 300

function LearningForm({
  initial,
  submitLabel,
  busy,
  onSubmit,
  onCancel,
}: {
  initial?: Learning
  submitLabel: string
  busy: boolean
  onSubmit: (text: string, pathGlob: string | null) => void
  onCancel?: () => void
}) {
  const [text, setText] = useState(initial?.text ?? '')
  const [glob, setGlob] = useState(initial?.path_glob ?? '')
  const length = text.trim().length
  return (
    <form
      className="stack"
      style={{ gap: 8 }}
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit(text.trim(), glob.trim() || null)
      }}
    >
      <label className="field">
        Rule
        <textarea
          className="input"
          rows={2}
          maxLength={MAX_CHARS}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="e.g. Request bodies in src/api are validated by middleware; do not report missing validation in handlers there."
        />
      </label>
      <div className="row wrap" style={{ alignItems: 'flex-end' }}>
        <label className="field grow">
          Only for files matching (optional)
          <input className="input" value={glob} maxLength={255} onChange={(event) => setGlob(event.target.value)} placeholder="src/api/**" />
        </label>
        <span className="muted small">{length}/{MAX_CHARS}</span>
        {onCancel && <button type="button" className="btn ghost" onClick={onCancel}>Cancel</button>}
        <button type="submit" className="btn primary" disabled={busy || length < MIN_CHARS}>{submitLabel}</button>
      </div>
    </form>
  )
}

function LearningRow({ learning, repositoryId }: { learning: Learning; repositoryId: number }) {
  const change = useChangeLearning(repositoryId)
  const remove = useDeleteLearning(repositoryId)
  const toast = useToast()
  const [editing, setEditing] = useState(false)
  const proposed = !learning.enabled && learning.source === 'github'
  const save = (patch: { text?: string; path_glob?: string | null; enabled?: boolean }, done: string) =>
    change.mutate(
      { id: learning.id, change: patch },
      {
        onSuccess: () => {
          setEditing(false)
          toast({ title: done })
        },
        onError: (error) => toast({ tone: 'error', title: 'Not saved', description: error.message }),
      },
    )

  return (
    <motion.li variants={item} layout className={`learning${learning.enabled ? '' : ' off'}`}>
      {editing ? (
        <LearningForm
          initial={learning}
          submitLabel="Save"
          busy={change.isPending}
          onCancel={() => setEditing(false)}
          onSubmit={(text, pathGlob) => save({ text, path_glob: pathGlob }, 'Learning updated')}
        />
      ) : (
        <>
          <div className="row" style={{ alignItems: 'flex-start' }}>
            <p className="grow" style={{ margin: 0 }}>{learning.text}</p>
            {proposed ? (
              <button type="button" className="btn primary sm" disabled={change.isPending} onClick={() => save({ enabled: true }, 'Learning approved: reviews use it from now on')}>
                <Check size={13} aria-hidden="true" /> Approve
              </button>
            ) : (
              <label className="switch" title={learning.enabled ? 'Used in reviews' : 'Not used in reviews'}>
                <input
                  type="checkbox"
                  checked={learning.enabled}
                  disabled={change.isPending}
                  onChange={(event) => save({ enabled: event.target.checked }, event.target.checked ? 'Learning enabled' : 'Learning disabled')}
                  aria-label={`Use this learning in reviews: ${learning.text}`}
                />
                <span className="track"><motion.span className="thumb" layout transition={spring} /></span>
              </label>
            )}
          </div>
          <div className="row wrap small muted">
            <span className="badge outline">{learning.path_glob ? <code>{learning.path_glob}</code> : 'all files'}</span>
            <span>{SOURCE_LABEL[learning.source] ?? learning.source}</span>
            <span>· used in {learning.times_applied} review{learning.times_applied === 1 ? '' : 's'}</span>
            {learning.last_applied_at && <span>· last {timeAgo(learning.last_applied_at)}</span>}
            <span className="grow" />
            <button type="button" className="btn ghost sm" onClick={() => setEditing(true)} aria-label="Edit">
              <Pencil size={13} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="btn ghost sm"
              aria-label={proposed ? 'Reject' : 'Delete'}
              disabled={remove.isPending}
              onClick={() => {
                if (!window.confirm(proposed ? 'Reject this proposed learning?' : 'Delete this learning?')) return
                remove.mutate(learning.id, {
                  onSuccess: () => toast({ title: proposed ? 'Learning rejected' : 'Learning deleted' }),
                  onError: (error) => toast({ tone: 'error', title: 'Not deleted', description: error.message }),
                })
              }}
            >
              {proposed ? <X size={13} aria-hidden="true" /> : <Trash2 size={13} aria-hidden="true" />}
            </button>
          </div>
        </>
      )}
    </motion.li>
  )
}

function Group({ title, hint, learnings, repositoryId }: { title: string; hint: string; learnings: Learning[]; repositoryId: number }) {
  if (learnings.length === 0) return null
  return (
    <section className="stack" aria-label={title}>
      <div className="row">
        <h2>{title}</h2>
        <span className="tab-count">{learnings.length}</span>
        <span className="muted small">{hint}</span>
      </div>
      <motion.ul className="learnings" variants={list} initial="hidden" animate="show">
        <AnimatePresence initial={false}>
          {learnings.map((learning) => <LearningRow key={learning.id} learning={learning} repositoryId={repositoryId} />)}
        </AnimatePresence>
      </motion.ul>
    </section>
  )
}

/** The rules future reviews of this repository follow: learned from 👎 reasons and GitHub
 * replies, or written here. Rules from GitHub wait for approval: anyone who can comment could
 * have written them. */
export function LearningsTab({ repositoryId }: { repositoryId: number }) {
  const learnings = useLearnings(repositoryId)
  const add = useAddLearning(repositoryId)
  const toast = useToast()
  const [formKey, setFormKey] = useState(0)
  const all = learnings.data ?? []

  return (
    <div className="stack lg">
      <div className="alert info small">
        <GraduationCap size={15} aria-hidden="true" />
        <div>
          Learnings are given to every review whose files they match, as evidence the reviewer must follow. A 👎 with a reason
          on a finding, a reply to a CodeEvidence comment, or <code>@codeevidence remember …</code> on GitHub proposes one.
          Rules that switch off a whole category of findings are refused.
        </div>
      </div>
      <section className="card card-body stack" aria-label="Add a learning">
        <h2 className="row"><Plus size={15} aria-hidden="true" /> Add a learning</h2>
        {add.isError && <div className="alert error small" role="alert">{add.error.message}</div>}
        <LearningForm
          key={formKey}
          submitLabel="Add"
          busy={add.isPending}
          onSubmit={(text, pathGlob) =>
            add.mutate(
              { text, path_glob: pathGlob },
              {
                onSuccess: () => {
                  setFormKey((key) => key + 1)
                  toast({ title: 'Learning added', description: 'Reviews of matching files use it from now on.' })
                },
              },
            )
          }
        />
      </section>
      {learnings.isPending && <Loading what="learnings" />}
      {learnings.isError && <ErrorMessage error={learnings.error} />}
      {learnings.isSuccess && all.length === 0 && <Empty icon={GraduationCap} title="No learnings yet">They appear here as reviewers explain their 👎.</Empty>}
      <Group title="Waiting for approval" hint="proposed on GitHub; not used until approved" learnings={all.filter((l) => !l.enabled && l.source === 'github')} repositoryId={repositoryId} />
      <Group title="Active" hint="used in reviews" learnings={all.filter((l) => l.enabled)} repositoryId={repositoryId} />
      <Group title="Disabled" hint="kept, not used" learnings={all.filter((l) => !l.enabled && l.source !== 'github')} repositoryId={repositoryId} />
    </div>
  )
}

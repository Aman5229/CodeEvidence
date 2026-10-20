import { CheckCircle2, Flame, Inbox, ListOrdered, Sparkles, Timer, Users } from 'lucide-react'
import { motion } from 'motion/react'
import { Link, useSearchParams } from 'react-router'
import type { Schemas } from '../api/client'
import { useRepositories, useReviewQueue } from '../api/hooks'
import { AnimatedNumber } from '../components/motion/AnimatedNumber'
import { RiskBadge } from '../components/ui/Badges'
import { Avatar, Kpi } from '../components/ui/Kpi'
import { Empty, ErrorMessage, Loading } from '../components/ui/States'
import { formatNumber } from '../lib/format'
import { trackGlow } from '../lib/glow'
import { hoverLift, item, list, softSpring } from '../lib/motion'

const BAND_TONE: Record<string, string> = { P1: 'high', P2: 'medium', P3: 'low' }
const BAND_HINT: Record<string, string> = { P1: 'review first', P2: 'soon', P3: 'when there is time' }

function EffortDots({ effort }: { effort: Schemas['EffortOut'] }) {
  return (
    <span className="row small" title={`Estimated review effort ${effort.level} of 5`}>
      <span className="effort-dots" aria-hidden="true">
        {Array.from({ length: 5 }, (_, index) => <span key={index} className={index < effort.level ? 'on' : ''} />)}
      </span>
      ~{effort.minutes} min
    </span>
  )
}

function QueueRow({ entry, position }: { entry: Schemas['QueueItemOut']; position: number }) {
  return (
    <motion.li variants={item} whileHover={hoverLift} className="card queue-row glow" onPointerMove={trackGlow}>
      <div className="queue-rank">
        <span className={`band ${BAND_TONE[entry.band]}`} title={BAND_HINT[entry.band]}>{entry.band}</span>
        <span className="muted small">#{position}</span>
      </div>
      <div className="stack" style={{ gap: 6, minWidth: 0 }}>
        <div className="row" style={{ minWidth: 0 }}>
          <Avatar login={entry.author_login} />
          <Link to={`/pull-requests/${entry.pull_request_id}`} className="link truncate" style={{ fontWeight: 600 }}>{entry.title}</Link>
          <span className="muted small nowrap">{entry.repository}#{entry.number}</span>
        </div>
        <div className="row wrap" style={{ gap: 6 }}>
          {entry.reasons.map((reason) => <span key={reason} className="chip static">{reason}</span>)}
        </div>
        <div className="row wrap small muted" style={{ gap: 14 }}>
          <EffortDots effort={entry.effort} />
          <span>{entry.files_changed} files · {entry.lines_changed} lines</span>
          {entry.review_status ? (
            entry.findings_shown === 0 ? (
              <span className="badge low"><CheckCircle2 size={12} aria-hidden="true" /> reviewed, clean</span>
            ) : (
              <span className={`badge ${entry.findings_high ? 'high' : 'medium'}`}><Sparkles size={12} aria-hidden="true" /> {entry.findings_shown} findings</span>
            )
          ) : (
            <span>not reviewed by AI</span>
          )}
        </div>
      </div>
      <div className="stack queue-side" style={{ gap: 8 }}>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <RiskBadge level={entry.risk_level} score={entry.risk_score} />
        </div>
        <div className="priority-meter" title={`Priority ${Math.round(entry.priority * 100)} of 100`}>
          <motion.span
            className={BAND_TONE[entry.band]}
            style={{ width: `${Math.round(entry.priority * 100)}%`, transformOrigin: 'left' }}
            initial={{ scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{ ...softSpring, delay: 0.1 + Math.min(position, 20) * 0.03 }}
          />
        </div>
        <div className="row small" style={{ justifyContent: 'flex-end', gap: 4 }} aria-label="Suggested reviewers">
          {entry.suggested_reviewers.length === 0 ? (
            <span className="muted">no earlier authors of these files</span>
          ) : (
            <>
              <Users size={13} aria-hidden="true" className="muted" />
              {entry.suggested_reviewers.map((reviewer) => (
                <span key={reviewer.login} className="row" title={`${reviewer.login}: changed ${reviewer.files_touched} of these files before`}>
                  <Avatar login={reviewer.login} /> {reviewer.login}
                </span>
              ))}
            </>
          )}
        </div>
      </div>
    </motion.li>
  )
}

/** Open PRs in the order to review them, with why, how long each takes, and who knows the
 * code. The priority mixes risk, the model's prediction, waiting time and quick wins. */
export function ReviewQueuePage() {
  const [params, setParams] = useSearchParams()
  const repositoryId = params.get('repository') ? Number(params.get('repository')) : null
  const repositories = useRepositories()
  const queue = useReviewQueue(repositoryId)
  const entries = queue.data?.items ?? []
  const minutes = queue.data?.total_minutes ?? 0

  return (
    <div className="stack lg">
      <div className="page-header" style={{ marginBottom: 0 }}>
        <div>
          <h1 className="row"><ListOrdered size={20} aria-hidden="true" /> Review queue</h1>
          <p>Open pull requests in the order to review them: risk, the model's prediction, how long they have waited, and how quick they are to review.</p>
        </div>
        <label className="field">
          Repository
          <select
            className="select"
            value={repositoryId ?? ''}
            onChange={(event) => setParams(event.target.value ? { repository: event.target.value } : {}, { replace: true })}
          >
            <option value="">All repositories</option>
            {(repositories.data?.items ?? []).map((repository) => <option key={repository.id} value={repository.id}>{repository.full_name}</option>)}
          </select>
        </label>
      </div>
      {queue.isPending && <Loading what="the review queue" lines={6} />}
      {queue.isError && <ErrorMessage error={queue.error} />}
      {queue.isSuccess && (
        <>
          <motion.div className="grid kpis" variants={list} initial="hidden" animate="show">
            <Kpi
              icon={Inbox}
              label="Open pull requests"
              value={<AnimatedNumber value={queue.data.total} />}
              hint={queue.data.total > entries.length ? `the first ${entries.length} are listed` : undefined}
            />
            <Kpi icon={Flame} label="Review first (P1)" value={<AnimatedNumber value={queue.data.p1} />} hint={`${queue.data.p2} soon (P2) · ${queue.data.p3} later (P3)`} />
            <Kpi icon={Timer} label="Estimated review time" value={minutes >= 120 ? `${formatNumber(Math.round(minutes / 60))} h` : `${minutes} min`} hint="for all of them" />
            <Kpi icon={Sparkles} label="Not reviewed by AI" value={<AnimatedNumber value={queue.data.not_reviewed} />} />
          </motion.div>
          {entries.length === 0 ? (
            <Empty icon={CheckCircle2} title="No open pull requests">Nothing is waiting for a review.</Empty>
          ) : (
            <motion.ol className="queue" variants={list} initial="hidden" animate="show" aria-label="Pull requests to review, in order">
              {entries.map((entry, index) => <QueueRow key={entry.pull_request_id} entry={entry} position={index + 1} />)}
            </motion.ol>
          )}
        </>
      )}
    </div>
  )
}

import { useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, Boxes, ChevronDown, FileCode2, Gauge, GitBranch, History, Loader2, Radar, ShieldAlert, Sparkles } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import type { Schemas } from '../api/client'
import { type ReviewMode, usePullRequest, useQueueReview, useRepository, useReview, useReviewRuns, useRisk } from '../api/hooks'
import { ChatPanel } from '../components/chat/ChatPanel'
import { ScoreRing } from '../components/charts/Charts'
import { EvidenceTab } from '../components/review/EvidenceTab'
import { FilesTab } from '../components/review/FilesTab'
import { FindingsTab } from '../components/review/FindingsTab'
import { ImpactTab } from '../components/review/ImpactTab'
import { ReviewProgress } from '../components/review/ReviewProgress'
import { RiskTab } from '../components/review/RiskTab'
import { RunsTab } from '../components/review/RunsTab'
import { WalkthroughTab } from '../components/review/WalkthroughTab'
import { PullRequestState, RiskBadge } from '../components/ui/Badges'
import { Avatar } from '../components/ui/Kpi'
import { ErrorMessage, Loading } from '../components/ui/States'
import { useToast } from '../components/ui/toast'
import { TabBar, TabPanel, type TabSpec } from '../components/ui/Tabs'
import { useTab } from '../components/ui/useTab'
import { timeAgo } from '../lib/format'
import { spring } from '../lib/motion'

export function PullRequestPage() {
  const id = Number(useParams().pullRequestId)
  const queryClient = useQueryClient()
  const pullRequest = usePullRequest(id)
  const risk = useRisk(id)
  const review = useReview(id)
  const queueReview = useQueueReview(id)
  const toast = useToast()
  // While a review runs, the run list is polled; a new run appearing means it is done.
  const [queued, setQueued] = useState<{ runs: number; at: number } | null>(null)
  const runs = useReviewRuns(id, queued?.runs ?? null)
  const reviewing = queued !== null && (runs.data?.length ?? 0) <= queued.runs
  const finishedRun = queued !== null && !reviewing ? runs.data?.[0] : undefined
  const [focusPath, setFocusPath] = useState<string | null>(null)

  useEffect(() => {
    if (!finishedRun) return
    queryClient.invalidateQueries({ queryKey: ['review', id] })
    queryClient.invalidateQueries({ queryKey: ['overview'] })
    toast({
      title: 'AI review finished',
      description: `${finishedRun.findings_shown} finding${finishedRun.findings_shown === 1 ? '' : 's'} shown, ${finishedRun.findings_dropped} dropped by verification.`,
    })
  }, [finishedRun, queryClient, id, toast])

  const findings = review.data?.findings ?? []
  const tabs: TabSpec[] = [
    { id: 'walkthrough', label: 'Walkthrough', icon: Sparkles },
    { id: 'files', label: 'Files changed', icon: FileCode2, count: pullRequest.data?.files.length },
    { id: 'findings', label: 'Findings', icon: ShieldAlert, count: findings.length },
    { id: 'impact', label: 'Impact', icon: Radar },
    { id: 'risk', label: 'Risk', icon: Gauge },
    { id: 'evidence', label: 'Evidence', icon: Boxes, count: review.data?.evidence.length },
    { id: 'runs', label: 'Runs', icon: History, count: runs.data?.length },
  ]
  const [tab, setTab] = useTab(tabs)

  if (pullRequest.isPending) return <Loading what="the pull request" lines={6} />
  if (pullRequest.isError) return <ErrorMessage error={pullRequest.error} />
  const pr = pullRequest.data

  const runReview = (mode: ReviewMode = 'auto') =>
    queueReview.mutate(mode, {
      onSuccess: () => {
        setQueued({ runs: runs.data?.length ?? 0, at: Date.now() })
        const description = mode === 'full'
          ? 'Every file is reviewed again. The worker picks it up in a moment.'
          : 'Only what changed since the last review is reviewed, when possible. The worker picks it up in a moment.'
        toast({ tone: 'info', title: 'AI review queued', description })
      },
      onError: () => toast({ tone: 'error', title: 'Could not queue the review' }),
    })
  const openFile = (path: string) => {
    setFocusPath(path)
    setTab('files')
  }

  return (
    <div className="pr-page">
      <Header pr={pr} risk={risk.data} reviewing={reviewing || queueReview.isPending} onRunReview={runReview} />
      {queueReview.isError && <div style={{ marginBottom: 16 }}><ErrorMessage error={queueReview.error} /></div>}
      <AnimatePresence>{reviewing && queued && <ReviewProgress since={queued.at} />}</AnimatePresence>
      <TabBar tabs={tabs} active={tab} onSelect={setTab} label="Pull request sections" />
      <TabPanel id={tab} index={tabs.findIndex((spec) => spec.id === tab)}>
        {review.isError && <ErrorMessage error={review.error} />}
        {tab === 'walkthrough' && (
          <WalkthroughTab pullRequest={pr} review={review.data} risk={risk.data} onOpenFile={openFile} onRunReview={() => runReview()} />
        )}
        {tab === 'files' && <FilesTab pullRequest={pr} findings={findings} focusPath={focusPath} />}
        {tab === 'findings' && <FindingsTab review={review.data} pullRequestId={id} onShowInDiff={openFile} />}
        {tab === 'impact' && <ImpactTab pullRequestId={id} repositoryId={pr.repository_id} onOpenFile={openFile} />}
        {tab === 'risk' && <RiskTab risk={risk.data} />}
        {tab === 'evidence' && <EvidenceTab review={review.data} />}
        {tab === 'runs' && <RunsTab runs={runs.data} loading={runs.isPending} />}
      </TabPanel>
      <ChatPanel pullRequestId={id} onOpenFile={openFile} />
    </div>
  )
}

/** "Run AI review", with a menu for a full review. By default only the files changed since the
 * last review are reviewed (when the PR got new commits on top of it). */
function ReviewButton({ reviewing, onRun }: { reviewing: boolean; onRun: (mode: ReviewMode) => void }) {
  const [menu, setMenu] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!menu) return
    const close = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setMenu(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [menu])
  const run = (mode: ReviewMode) => {
    setMenu(false)
    onRun(mode)
  }
  return (
    <div className="split" ref={box} onKeyDown={(event) => event.key === 'Escape' && setMenu(false)}>
      <button type="button" className="btn ai" onClick={() => run('auto')} disabled={reviewing}>
        {reviewing ? <Loader2 size={15} className="spin" aria-hidden="true" /> : <Sparkles size={15} aria-hidden="true" />}
        {reviewing ? 'Reviewing…' : 'Run AI review'}
      </button>
      <button
        type="button"
        className="btn ai split-toggle"
        aria-label="Review options"
        aria-haspopup="menu"
        aria-expanded={menu}
        disabled={reviewing}
        onClick={() => setMenu(!menu)}
      >
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      <AnimatePresence>
        {menu && (
          <motion.div
            role="menu"
            className="menu"
            initial={{ opacity: 0, y: -6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, transition: { duration: 0.12 } }}
            transition={spring}
          >
            <button type="button" role="menuitem" className="menu-item" onClick={() => run('auto')}>
              <strong>Review new changes</strong>
              <span className="muted small">Only files changed since the last review; findings on the others are kept</span>
            </button>
            <button type="button" role="menuitem" className="menu-item" onClick={() => run('full')}>
              <strong>Full review</strong>
              <span className="muted small">Every file again, from scratch</span>
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function Header({
  pr,
  risk,
  reviewing,
  onRunReview,
}: {
  pr: Schemas['PullRequestDetailWithPatch']
  risk: Schemas['RiskOut'] | null | undefined
  reviewing: boolean
  onRunReview: (mode: ReviewMode) => void
}) {
  const repository = useRepository(pr.repository_id)
  const githubUrl = repository.data ? `${repository.data.html_url}/pull/${pr.number}` : null
  return (
    <div className="page-header">
      <div style={{ minWidth: 0 }}>
        <div className="crumbs">
          <Link to="/repositories">Repositories</Link> /
          <Link to={`/repositories/${pr.repository_id}`}>{repository.data?.full_name ?? '…'}</Link> /
        </div>
        <h1 className="pr-title">
          {pr.title} <span className="pr-number">#{pr.number}</span>
        </h1>
        <div className="meta">
          <PullRequestState status={pr.status} merged={pr.is_merged} />
          <span><Avatar login={pr.author_login} /> {pr.author_login ?? 'unknown'}</span>
          <span>
            <GitBranch size={14} aria-hidden="true" />
            <span className="branch">{pr.head_branch}</span> → <span className="branch">{pr.base_branch}</span>
          </span>
          <span>
            {pr.totals.files_changed} files · <span style={{ color: 'var(--low)' }}>+{pr.totals.additions}</span>{' '}
            <span style={{ color: 'var(--high)' }}>−{pr.totals.deletions}</span>
          </span>
          <span>opened {timeAgo(pr.created_at)}</span>
          {risk && <RiskBadge level={risk.level} score={risk.score} />}
        </div>
      </div>
      <div className="row">
        {risk && <ScoreRing score={risk.score} level={risk.level} />}
        {githubUrl && (
          <a href={githubUrl} target="_blank" rel="noreferrer" className="btn">
            GitHub <ArrowUpRight size={14} aria-hidden="true" />
          </a>
        )}
        <ReviewButton reviewing={reviewing} onRun={onRunReview} />
      </div>
    </div>
  )
}

import { ArrowUpRight, BarChart3, Bot, CheckCircle2, Database, FileCog, GitPullRequest, GraduationCap, Loader2, RefreshCw, Sparkles } from 'lucide-react'
import { motion } from 'motion/react'
import { Link, useParams, useSearchParams } from 'react-router'
import type { Schemas } from '../api/client'
import { useIndexStatus, useInsights, usePullRequests, useQueueIndex, useRepository, useRepositoryStats } from '../api/hooks'
import { ShareBar } from '../components/charts/Charts'
import { LearningsTab } from '../components/repository/LearningsTab'
import { ReviewSettingsTab } from '../components/repository/ReviewSettingsTab'
import { PullRequestState, RiskBadge } from '../components/ui/Badges'
import { Avatar, Kpi } from '../components/ui/Kpi'
import { Empty, ErrorMessage, Loading } from '../components/ui/States'
import { TabBar, TabPanel, type TabSpec } from '../components/ui/Tabs'
import { useTab } from '../components/ui/useTab'
import { AnimatedNumber } from '../components/motion/AnimatedNumber'
import { useToast } from '../components/ui/toast'
import { timeAgo } from '../lib/format'
import { item, list } from '../lib/motion'
import { filtersFromParams } from './filters'

const TABS: TabSpec[] = [
  { id: 'pulls', label: 'Pull requests', icon: GitPullRequest },
  { id: 'insights', label: 'Insights', icon: BarChart3 },
  { id: 'index', label: 'Code index', icon: Database },
  { id: 'learnings', label: 'Learnings', icon: GraduationCap },
  { id: 'settings', label: 'Review settings', icon: FileCog },
]

export function RepositoryPage() {
  const repositoryId = Number(useParams().repositoryId)
  const repository = useRepository(repositoryId)
  const [tab, setTab] = useTab(TABS)
  if (repository.isError) return <ErrorMessage error={repository.error} />

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="crumbs"><Link to="/repositories">Repositories</Link> /</div>
          <h1>{repository.data?.full_name ?? 'Repository'}</h1>
        </div>
        {repository.data && (
          <a href={repository.data.html_url} target="_blank" rel="noreferrer" className="btn">
            Open on GitHub <ArrowUpRight size={14} aria-hidden="true" />
          </a>
        )}
      </div>
      <TabBar tabs={TABS} active={tab} onSelect={setTab} label="Repository sections" />
      <TabPanel id={tab} index={TABS.findIndex((spec) => spec.id === tab)}>
        {tab === 'pulls' && <PullRequestsTab repositoryId={repositoryId} />}
        {tab === 'insights' && <InsightsTab repositoryId={repositoryId} />}
        {tab === 'index' && <IndexTab repositoryId={repositoryId} />}
        {tab === 'learnings' && <LearningsTab repositoryId={repositoryId} />}
        {tab === 'settings' && <ReviewSettingsTab repositoryId={repositoryId} defaultBranch={repository.data?.default_branch} />}
      </TabPanel>
    </div>
  )
}

// ---------- pull requests ----------

function FilterSelect({ name, label, options }: { name: string; label: string; options: [string, string][] }) {
  const [params, setParams] = useSearchParams()
  return (
    <label className="field">
      {label}
      <select
        className="select"
        value={params.get(name) ?? ''}
        onChange={(event) => {
          const next = new URLSearchParams(params)
          if (event.target.value) next.set(name, event.target.value)
          else next.delete(name)
          setParams(next, { replace: true })
        }}
      >
        <option value="">Any</option>
        {options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </select>
    </label>
  )
}

function FilterInput({ name, label, type = 'text' }: { name: string; label: string; type?: string }) {
  const [params, setParams] = useSearchParams()
  return (
    <label className="field">
      {label}
      <input
        className="input"
        type={type}
        value={params.get(name) ?? ''}
        onChange={(event) => {
          const next = new URLSearchParams(params)
          if (event.target.value) next.set(name, event.target.value)
          else next.delete(name)
          setParams(next, { replace: true })
        }}
      />
    </label>
  )
}

/** PRs with filters kept in the URL, cursor paging, and each PR's risk and review status. */
function PullRequestsTab({ repositoryId }: { repositoryId: number }) {
  const [params] = useSearchParams()
  const pullRequests = usePullRequests(repositoryId, filtersFromParams(params))
  const items = pullRequests.data?.pages.flatMap((page) => page.items) ?? []
  const insights = useInsights(items.slice(0, 100).map((pr) => pr.id))
  const insightOf = new Map((insights.data ?? []).map((insight) => [insight.pull_request_id, insight]))

  return (
    <div className="stack">
      <div className="row wrap" style={{ gap: 12, alignItems: 'flex-end' }}>
        <FilterSelect name="status" label="Status" options={[['open', 'Open'], ['closed', 'Closed']]} />
        <FilterSelect name="merged" label="Merged" options={[['true', 'Merged'], ['false', 'Not merged']]} />
        <FilterSelect name="is_bot" label="Author" options={[['false', 'People'], ['true', 'Bots']]} />
        <FilterInput name="author" label="Login" />
        <FilterInput name="created_after" label="From" type="date" />
        <FilterInput name="created_before" label="Before" type="date" />
      </div>
      {pullRequests.isPending && <Loading what="pull requests" />}
      {pullRequests.isError && <ErrorMessage error={pullRequests.error} />}
      {pullRequests.isSuccess && items.length === 0 && <Empty icon={GitPullRequest} title="No pull requests match these filters" />}
      {items.length > 0 && (
        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Pull request</th>
                <th scope="col">State</th>
                <th scope="col">Risk</th>
                <th scope="col">AI review</th>
                <th scope="col">Opened</th>
              </tr>
            </thead>
            <motion.tbody variants={list} initial="hidden" animate="show">
              {items.map((pr) => (
                <PullRequestRow key={pr.id} pr={pr} insight={insightOf.get(pr.id)} />
              ))}
            </motion.tbody>
          </table>
        </div>
      )}
      {pullRequests.hasNextPage && (
        <button type="button" className="btn" style={{ alignSelf: 'center' }} onClick={() => pullRequests.fetchNextPage()} disabled={pullRequests.isFetchingNextPage}>
          {pullRequests.isFetchingNextPage ? 'Loading…' : 'Load more'}
        </button>
      )}
    </div>
  )
}

function PullRequestRow({ pr, insight }: { pr: Schemas['PullRequestSummary']; insight?: Schemas['PullRequestInsight'] }) {
  return (
    <motion.tr variants={item}>
      <td>
        <div className="row">
          <Avatar login={pr.author_login} />
          <div style={{ minWidth: 0 }}>
            <Link to={`/pull-requests/${pr.id}`} className="link">{pr.title}</Link>
            <div className="muted small">
              #{pr.number} by {pr.author_login ?? 'unknown'}
              {pr.is_bot && <span className="badge outline" style={{ marginLeft: 6 }}><Bot size={11} aria-hidden="true" /> bot</span>}
            </div>
          </div>
        </div>
      </td>
      <td><PullRequestState status={pr.status} merged={pr.is_merged} /></td>
      <td><RiskBadge level={insight?.risk_level} score={insight?.risk_score} /></td>
      <td>
        {!insight?.review_status ? (
          <span className="muted small">not reviewed</span>
        ) : insight.findings_shown === 0 ? (
          <span className="badge low"><CheckCircle2 size={12} aria-hidden="true" /> clean</span>
        ) : (
          <span className={`badge ${insight.findings_high ? 'high' : 'medium'}`}>
            <Sparkles size={12} aria-hidden="true" /> {insight.findings_shown} findings
          </span>
        )}
      </td>
      <td className="muted nowrap" title={pr.created_at}>{timeAgo(pr.created_at)}</td>
    </motion.tr>
  )
}

// ---------- insights ----------

function InsightsTab({ repositoryId }: { repositoryId: number }) {
  const stats = useRepositoryStats(repositoryId)
  if (stats.isPending) return <Loading what="stats" />
  if (stats.isError) return <ErrorMessage error={stats.error} />
  const data = stats.data
  return (
    <div className="stack lg">
      <motion.div className="grid kpis" variants={list} initial="hidden" animate="show">
        <Kpi icon={GitPullRequest} label="Pull requests" value={<AnimatedNumber value={data.total_prs} />} hint={`${data.closed_prs} closed · ${data.merged_prs} merged`} />
        <Kpi icon={BarChart3} label="Median size" value={data.median_lines_changed == null ? '—' : <AnimatedNumber value={data.median_lines_changed} />} hint="lines changed" />
        <Kpi icon={RefreshCw} label="Median time to close" value={data.median_hours_to_close == null ? '—' : <><AnimatedNumber value={data.median_hours_to_close} format="decimal" /> h</>} />
        <Kpi icon={Bot} label="Bot pull requests" value={<AnimatedNumber value={data.bot_prs} />} />
      </motion.div>
      <section className="card card-body stack" aria-label="Shares">
        <ShareBar label="Merge rate (merged / closed)" value={data.merge_rate} tone="low" />
        <ShareBar label="Bot share" value={data.bot_share} tone="medium" />
      </section>
    </div>
  )
}

// ---------- code index ----------

function IndexTab({ repositoryId }: { repositoryId: number }) {
  const status = useIndexStatus(repositoryId)
  const queue = useQueueIndex(repositoryId)
  const toast = useToast()
  const startIndex = () =>
    queue.mutate(undefined, {
      onSuccess: (job) => {
        toast({ tone: 'info', title: 'Indexing started', description: `Job #${job.job_id}: the worker is embedding the code.` })
        setTimeout(() => status.refetch(), 5000)
      },
      onError: () => toast({ tone: 'error', title: 'Could not start indexing' }),
    })
  return (
    <div className="stack lg">
      <div className="alert info small">
        The code index lets the AI reviewer find related code (hybrid vector + keyword search over functions and classes of the default branch).
        Re-indexing only re-embeds files that changed.
      </div>
      {status.isPending && <Loading what="index status" />}
      {status.isError && <ErrorMessage error={status.error} />}
      {status.data && (
        <motion.div className="grid kpis" variants={list} initial="hidden" animate="show">
          <Kpi icon={Database} label="Files indexed" value={<AnimatedNumber value={status.data.files} />} />
          <Kpi icon={Database} label="Code chunks" value={<AnimatedNumber value={status.data.chunks} />} hint="functions, methods, classes" />
          <Kpi icon={Sparkles} label="Embedding model" value={<span style={{ fontSize: 14 }}>{status.data.embedding_model ?? '—'}</span>} />
          <Kpi icon={RefreshCw} label="Last indexed" value={<span style={{ fontSize: 16 }}>{status.data.last_indexed_at ? timeAgo(status.data.last_indexed_at) : 'never'}</span>} />
        </motion.div>
      )}
      <div className="row">
        <button type="button" className="btn ai" disabled={queue.isPending} onClick={startIndex}>
          {queue.isPending ? <Loader2 size={15} className="spin" aria-hidden="true" /> : <RefreshCw size={15} aria-hidden="true" />}
          {status.data?.chunks ? 'Re-index code' : 'Index code'}
        </button>
        {queue.isSuccess && <span className="muted small">Queued as job #{queue.data.job_id}: the worker is indexing. Refresh in a minute.</span>}
      </div>
    </div>
  )
}

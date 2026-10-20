import { ArrowUpRight, FolderGit2 } from 'lucide-react'
import { motion } from 'motion/react'
import { Link } from 'react-router'
import type { Schemas } from '../api/client'
import { useRepositories, useRepositoryStats } from '../api/hooks'
import { ShareBar } from '../components/charts/Charts'
import { Empty, ErrorMessage, Loading, Skeleton } from '../components/ui/States'
import { AnimatedNumber } from '../components/motion/AnimatedNumber'
import { trackGlow } from '../lib/glow'
import { timeAgo } from '../lib/format'
import { hoverLift, item, list } from '../lib/motion'

export function RepositoriesPage() {
  const repositories = useRepositories()
  return (
    <div className="stack lg">
      <div className="page-header">
        <div>
          <h1>Repositories</h1>
          <p>Every repository CodeEvidence has received webhooks or a backfill for.</p>
        </div>
      </div>
      {repositories.isPending && <Loading what="repositories" />}
      {repositories.isError && <ErrorMessage error={repositories.error} />}
      {repositories.isSuccess && repositories.data.items.length === 0 && (
        <Empty icon={FolderGit2} title="No repositories yet">Send a webhook, or run the backfill script.</Empty>
      )}
      {repositories.data && (
        <motion.div className="grid two" variants={list} initial="hidden" animate="show">
          {repositories.data.items.map((repository) => <RepositoryCard key={repository.id} repository={repository} />)}
        </motion.div>
      )}
    </div>
  )
}

function RepositoryCard({ repository }: { repository: Schemas['RepositoryOut'] }) {
  const stats = useRepositoryStats(repository.id)
  return (
    <motion.article className="card glow lift" variants={item} whileHover={hoverLift} onPointerMove={trackGlow}>
      <div className="card-header">
        <Link to={`/repositories/${repository.id}`} className="row" style={{ fontWeight: 600 }}>
          <FolderGit2 size={16} aria-hidden="true" /> {repository.full_name}
        </Link>
        <a href={repository.html_url} target="_blank" rel="noreferrer" className="btn ghost sm" aria-label={`${repository.full_name} on GitHub`}>
          <ArrowUpRight size={14} aria-hidden="true" />
        </a>
      </div>
      <div className="card-body stack">
        {stats.data ? (
          <>
            <div className="row" style={{ gap: 24 }}>
              <div><div className="kpi-label">Pull requests</div><div style={{ fontSize: 20, fontWeight: 650 }}><AnimatedNumber value={stats.data.total_prs} /></div></div>
              <div><div className="kpi-label">Median size</div><div style={{ fontSize: 20, fontWeight: 650 }}>{stats.data.median_lines_changed ?? '—'}<span className="muted small"> lines</span></div></div>
            </div>
            <ShareBar label="Merge rate" value={stats.data.merge_rate} />
            <ShareBar label="Bot share" value={stats.data.bot_share} tone="medium" />
          </>
        ) : (
          <Skeleton height={60} />
        )}
        <span className="muted small">Last synced {timeAgo(repository.last_synced_at)}</span>
      </div>
    </motion.article>
  )
}

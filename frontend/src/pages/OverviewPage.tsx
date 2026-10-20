import { ArrowRight, Coins, FolderGit2, GitPullRequest, ShieldCheck, Sparkles, ThumbsUp, TrendingUp } from 'lucide-react'
import { motion } from 'motion/react'
import { Link } from 'react-router'
import { useOverview } from '../api/hooks'
import { Donut, Funnel } from '../components/charts/Charts'
import { AnimatedNumber } from '../components/motion/AnimatedNumber'
import { RiskBadge } from '../components/ui/Badges'
import { Kpi } from '../components/ui/Kpi'
import { Empty, ErrorMessage, Loading } from '../components/ui/States'
import { trackGlow } from '../lib/glow'
import { formatUsd, share, timeAgo } from '../lib/format'
import { item, list } from '../lib/motion'

export function OverviewPage() {
  const overview = useOverview()
  if (overview.isPending) return <Loading what="the overview" lines={6} />
  if (overview.isError) return <ErrorMessage error={overview.error} />
  const data = overview.data
  const proposed = data.findings_shown + data.findings_dropped
  const rated = data.feedback_useful + data.feedback_not_useful

  return (
    <motion.div className="stack lg" variants={list} initial="hidden" animate="show">
      <motion.header variants={item} className="hero glow" onPointerMove={trackGlow}>
        <div className="row wrap" style={{ justifyContent: 'space-between', gap: 16 }}>
          <div>
            <h1 className="gradient-text">Every finding checked against the code</h1>
            <p>Risk scores, AI reviews and how well they hold up, across every repository. Findings the evidence cannot support never reach you.</p>
          </div>
          <Link to="/repositories" className="btn ai">
            <FolderGit2 size={15} aria-hidden="true" /> Browse repositories
          </Link>
        </div>
      </motion.header>

      <motion.div className="grid kpis" variants={list}>
        <Kpi icon={FolderGit2} label="Repositories" value={<AnimatedNumber value={data.repositories} />} />
        <Kpi icon={GitPullRequest} label="Pull requests" value={<AnimatedNumber value={data.pull_requests} />} hint={`${data.reviewed_pull_requests} reviewed by AI`} />
        <Kpi icon={Sparkles} label="Findings shown" value={<AnimatedNumber value={data.findings_shown} />} hint={`from ${data.reviews} review runs`} />
        <Kpi icon={ShieldCheck} label="Dropped by verification" value={<AnimatedNumber value={share(data.findings_dropped, proposed)} format="percent" />} hint={`${data.findings_dropped} of ${proposed} proposed findings`} />
        <Kpi icon={ThumbsUp} label="Rated useful" value={rated ? <AnimatedNumber value={share(data.feedback_useful, rated)} format="percent" /> : '—'} hint={`${rated} ratings`} />
        <Kpi icon={Coins} label="Review spend" value={<AnimatedNumber value={data.review_cost_usd} format="usd" />} hint={data.review_cost_usd === 0 ? 'local model: free' : undefined} />
      </motion.div>

      <motion.div variants={item} className="grid two">
        <section className="card glow" onPointerMove={trackGlow} aria-labelledby="risk-dist">
          <div className="card-header"><h2 id="risk-dist">Risk distribution</h2><span className="muted small">rule score, all scored PRs</span></div>
          <div className="card-body">
            <Donut
              centerLabel="scored PRs"
              slices={[
                { label: 'High', value: data.risk_levels.high, color: 'var(--high)' },
                { label: 'Medium', value: data.risk_levels.medium, color: 'var(--medium)' },
                { label: 'Low', value: data.risk_levels.low, color: 'var(--low)' },
              ]}
            />
          </div>
        </section>

        <section className="card glow" onPointerMove={trackGlow} aria-labelledby="funnel-title">
          <div className="card-header"><h2 id="funnel-title" className="row"><ShieldCheck size={15} aria-hidden="true" /> From proposal to useful</h2></div>
          <div className="card-body">
            <Funnel
              stages={[
                { label: 'Proposed by the model', value: proposed, color: 'linear-gradient(90deg, var(--accent), #3b82f6)' },
                { label: 'Passed verification', value: data.findings_shown, color: 'linear-gradient(90deg, #3b82f6, var(--low))', hint: 'grounded in the diff' },
                { label: 'Rated useful', value: data.feedback_useful, color: 'var(--low)', hint: rated ? `${rated} ratings so far` : 'no ratings yet' },
              ]}
            />
          </div>
        </section>
      </motion.div>

      <motion.section variants={item} className="card" aria-labelledby="riskiest">
        <div className="card-header"><h2 id="riskiest" className="row"><TrendingUp size={15} aria-hidden="true" /> Riskiest pull requests</h2></div>
        <motion.div className="card-body stack" style={{ gap: 4 }} variants={list}>
          {data.riskiest.length === 0 && <Empty title="Nothing scored yet">Backfill a repository to see scores.</Empty>}
          {data.riskiest.map((pr) => (
            <motion.div key={pr.pull_request_id} variants={item} whileHover={{ x: 4 }}>
              <Link to={`/pull-requests/${pr.pull_request_id}`} className="tree-row">
                <RiskBadge level={pr.level} score={pr.score} />
                <span className="truncate grow">{pr.title}</span>
                <span className="muted small nowrap">{pr.repository}#{pr.number}</span>
                <ArrowRight size={14} aria-hidden="true" className="muted" />
              </Link>
            </motion.div>
          ))}
        </motion.div>
      </motion.section>

      <motion.section variants={item} className="card" aria-labelledby="recent">
        <div className="card-header"><h2 id="recent">Recent AI reviews</h2></div>
        {data.recent_reviews.length === 0 ? (
          <Empty icon={Sparkles} title="No reviews yet">Open a pull request and click “Run AI review”.</Empty>
        ) : (
          <table className="table">
            <thead>
              <tr><th scope="col">Pull request</th><th scope="col">Status</th><th scope="col">Findings</th><th scope="col">Model</th><th scope="col">Cost</th><th scope="col">When</th></tr>
            </thead>
            <motion.tbody variants={list} initial="hidden" animate="show">
              {data.recent_reviews.map((review) => (
                <motion.tr key={review.review_id} variants={item}>
                  <td>
                    <Link to={`/pull-requests/${review.pull_request_id}?tab=walkthrough`} className="link">{review.title}</Link>
                    <div className="muted small">{review.repository}#{review.number}</div>
                  </td>
                  <td><span className={`badge ${review.status === 'completed' ? 'low' : 'medium'}`}>{review.status}</span></td>
                  <td>{review.findings_shown}</td>
                  <td className="small">{review.model}</td>
                  <td>{formatUsd(review.cost_usd)}</td>
                  <td className="muted nowrap">{timeAgo(review.created_at)}</td>
                </motion.tr>
              ))}
            </motion.tbody>
          </table>
        )}
      </motion.section>
    </motion.div>
  )
}

import { BarChart3, Bot, Coins, FolderTree, GraduationCap, MessageCircle, Repeat, ShieldCheck, ThumbsUp, Wrench } from 'lucide-react'
import { motion } from 'motion/react'
import { useSearchParams } from 'react-router'
import { useAnalytics, useRepositories } from '../api/hooks'
import { Radar, ShareBar, StackedBars } from '../components/charts/Charts'
import { AnimatedNumber } from '../components/motion/AnimatedNumber'
import { Kpi } from '../components/ui/Kpi'
import { Empty, ErrorMessage, Loading } from '../components/ui/States'
import { trackGlow } from '../lib/glow'
import { formatDuration, formatPercent, formatUsd, share } from '../lib/format'
import { item, list } from '../lib/motion'

const PERIODS = [30, 90, 365]
const CATEGORY_LABEL: Record<string, string> = { bug: 'Bugs', security: 'Security', performance: 'Performance', maintainability: 'Maintainability', tests: 'Tests' }
const DROP_REASON: Record<string, string> = {
  no_valid_evidence: 'cited evidence that does not exist',
  path_not_in_diff: 'about a file the PR does not change',
  line_not_in_diff: 'about a line the PR did not add',
  quote_not_found: 'quoted code that is not there',
  low_confidence: 'too unsure',
}
const weekLabel = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en', { month: 'short', day: 'numeric', timeZone: 'UTC' })

/** Is the reviewer useful, is it improving, and where does it help? Acceptance by category,
 * findings and votes per week, results per model, and whether the risk score predicts merges. */
export function AnalyticsPage() {
  const [params, setParams] = useSearchParams()
  const days = PERIODS.includes(Number(params.get('days'))) ? Number(params.get('days')) : 90
  const repositoryId = params.get('repository') ? Number(params.get('repository')) : null
  const repositories = useRepositories()
  const analytics = useAnalytics(days, repositoryId)
  const update = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  return (
    <div className="stack lg">
      <div className="page-header" style={{ marginBottom: 0 }}>
        <div>
          <h1 className="row"><BarChart3 size={20} aria-hidden="true" /> Analytics</h1>
          <p>How useful the AI reviews are, where they help, and whether they get better.</p>
        </div>
        <div className="row" style={{ alignItems: 'flex-end' }}>
          <div className="row" role="group" aria-label="Period">
            {PERIODS.map((period) => (
              <button key={period} type="button" className={`chip${period === days ? ' active' : ''}`} aria-pressed={period === days} onClick={() => update('days', String(period))}>
                {period === 365 ? '1 year' : `${period} days`}
              </button>
            ))}
          </div>
          <label className="field">
            Repository
            <select className="select" value={repositoryId ?? ''} onChange={(event) => update('repository', event.target.value || null)}>
              <option value="">All repositories</option>
              {(repositories.data?.items ?? []).map((repository) => <option key={repository.id} value={repository.id}>{repository.full_name}</option>)}
            </select>
          </label>
        </div>
      </div>
      {analytics.isPending && <Loading what="analytics" lines={6} />}
      {analytics.isError && <ErrorMessage error={analytics.error} />}
      {analytics.isSuccess && <Dashboard data={analytics.data} />}
    </div>
  )
}

function Dashboard({ data }: { data: NonNullable<ReturnType<typeof useAnalytics>['data']> }) {
  const votes = data.votes.useful + data.votes.not_useful
  const largestFolder = Math.max(1, ...data.directories.map((folder) => folder.findings))
  const largestShown = Math.max(1, ...data.categories.map((category) => category.shown))
  const reasons = data.drop_reasons.reduce((sum, reason) => sum + reason.count, 0)

  return (
    <motion.div className="stack lg" variants={list} initial="hidden" animate="show">
      <motion.div className="grid kpis" variants={list}>
        <Kpi icon={ThumbsUp} label="Acceptance" value={data.acceptance == null ? '—' : <AnimatedNumber value={data.acceptance} format="percent" />} hint={`${data.votes.useful} useful of ${votes} votes`} />
        <Kpi icon={ShieldCheck} label="Findings shown" value={<AnimatedNumber value={data.findings_shown} />} hint={`${formatPercent(share(data.findings_dropped, data.findings_proposed))} of ${data.findings_proposed} proposed were dropped`} />
        <Kpi icon={Repeat} label="Repeated after a 👎" value={<AnimatedNumber value={data.repeats_after_rejection} />} hint="learnings should keep this low" />
        <Kpi icon={GraduationCap} label="Learnings in use" value={<AnimatedNumber value={data.learnings_enabled} />} hint={`${data.learnings_proposed} waiting for approval · used ${data.learnings_applied}×`} />
        <Kpi icon={MessageCircle} label="Questions asked" value={<AnimatedNumber value={data.chat_questions} />} hint={formatUsd(data.chat_cost_usd)} />
        <Kpi icon={Coins} label="Review spend" value={<AnimatedNumber value={data.cost_usd} format="usd" />} hint={`${data.reviews} reviews · ${data.reviews_cached} cached · ${data.reviews_incremental} incremental`} />
      </motion.div>

      {data.reviews === 0 && votes === 0 ? (
        <Empty icon={BarChart3} title="No reviews in this period">Run AI reviews to see how useful they are.</Empty>
      ) : (
        <>
          <motion.div variants={item} className="grid two">
            <section className="card glow" onPointerMove={trackGlow} aria-labelledby="by-category">
              <div className="card-header"><h2 id="by-category">By category</h2><span className="muted small">acceptance, and where findings land</span></div>
              <div className="card-body">
                <Radar
                  label="Acceptance and share of findings by category"
                  axes={data.categories.map((category) => CATEGORY_LABEL[category.category] ?? category.category)}
                  series={[
                    { label: 'Acceptance (useful votes)', color: 'var(--low)', values: data.categories.map((category) => category.acceptance) },
                    { label: 'Findings shown (relative)', color: 'var(--accent)', values: data.categories.map((category) => category.shown / largestShown) },
                  ]}
                />
              </div>
            </section>
            <section className="card glow" onPointerMove={trackGlow} aria-labelledby="per-week">
              <div className="card-header"><h2 id="per-week">Per week</h2><span className="muted small">findings the model proposed</span></div>
              <div className="card-body">
                {data.weeks.length === 0 ? <span className="muted small">No activity.</span> : (
                  <StackedBars
                    label="Findings shown and dropped per week"
                    periods={data.weeks.map((week) => weekLabel(week.week))}
                    parts={[{ label: 'shown', color: 'var(--low)' }, { label: 'dropped by verification', color: 'var(--high)' }]}
                    values={data.weeks.map((week) => [week.shown, week.dropped])}
                  />
                )}
              </div>
            </section>
          </motion.div>

          <motion.section variants={item} className="card" aria-labelledby="per-model">
            <div className="card-header"><h2 id="per-model" className="row"><Bot size={15} aria-hidden="true" /> Per model and prompt</h2></div>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Model · prompt</th><th scope="col">Reviews</th><th scope="col">Shown</th><th scope="col">Dropped</th>
                  <th scope="col">Acceptance</th><th scope="col">Avg cost</th><th scope="col">Avg time</th>
                </tr>
              </thead>
              <motion.tbody variants={list} initial="hidden" animate="show">
                {data.models.map((model) => (
                  <motion.tr key={`${model.model}:${model.prompt_version}`} variants={item}>
                    <td className="small">{model.model}<br /><span className="muted">{model.prompt_version}</span></td>
                    <td>{model.reviews} <span className="muted small">({model.cached} cached)</span></td>
                    <td>{model.findings_shown}</td>
                    <td>{model.findings_dropped}</td>
                    <td>{model.acceptance == null ? <span className="muted">no votes</span> : `${formatPercent(model.acceptance)} of ${model.useful + model.not_useful}`}</td>
                    <td>{model.avg_cost_usd == null ? '—' : formatUsd(model.avg_cost_usd)}</td>
                    <td>{model.avg_latency_ms == null ? '—' : formatDuration(model.avg_latency_ms)}</td>
                  </motion.tr>
                ))}
              </motion.tbody>
            </table>
          </motion.section>

          <motion.div variants={item} className="grid two">
            <section className="card card-body stack" aria-labelledby="risk-check">
              <h2 id="risk-check">Does the risk score predict merges?</h2>
              <p className="muted small" style={{ margin: 0 }}>Merge rate of closed pull requests by risk level (all time): a useful score merges less as risk goes up.</p>
              {data.risk_outcomes.map((outcome) => (
                <ShareBar key={outcome.level} label={`${outcome.level} risk · ${outcome.merged} of ${outcome.closed} merged`} value={outcome.merge_rate} tone={outcome.level} />
              ))}
            </section>
            <section className="card card-body stack" aria-labelledby="folders">
              <h2 id="folders" className="row"><FolderTree size={15} aria-hidden="true" /> Where findings land</h2>
              {data.directories.length === 0 && <span className="muted small">No findings shown.</span>}
              {data.directories.map((folder) => (
                <div key={folder.directory} className="stack" style={{ gap: 4 }}>
                  <div className="row small"><code className="grow truncate">{folder.directory}</code><strong>{folder.findings}</strong>{folder.high > 0 && <span className="badge high">{folder.high} high</span>}</div>
                  <div className="bar-track"><motion.div className="bar-fill" style={{ width: `${(folder.findings / largestFolder) * 100}%`, transformOrigin: 'left' }} initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} /></div>
                </div>
              ))}
            </section>
          </motion.div>

          <motion.div variants={item} className="grid two">
            <section className="card card-body stack" aria-labelledby="dropped">
              <h2 id="dropped" className="row"><ShieldCheck size={15} aria-hidden="true" /> Why findings were dropped</h2>
              {data.drop_reasons.length === 0 && <span className="muted small">Nothing dropped: every finding was supported by the evidence.</span>}
              {data.drop_reasons.map((reason) => (
                <ShareBar key={reason.reason} label={`${DROP_REASON[reason.reason] ?? reason.reason} (${reason.count})`} value={share(reason.count, reasons)} tone="high" />
              ))}
            </section>
            <section className="card card-body stack" aria-labelledby="tools">
              <h2 id="tools" className="row"><Wrench size={15} aria-hidden="true" /> Static analysis</h2>
              {data.tools.length === 0 && <span className="muted small">No tool ran in this period.</span>}
              {data.tools.map((tool) => (
                <div key={tool.name} className="row">
                  <code className="grow">{tool.name}</code>
                  <span className="small">{tool.runs} runs · <strong>{tool.findings}</strong> findings</span>
                  {tool.skipped > 0 && <span className="badge outline">{tool.skipped} skipped</span>}
                </div>
              ))}
            </section>
          </motion.div>
        </>
      )}
    </motion.div>
  )
}

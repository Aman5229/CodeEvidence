import { Bot, CheckCircle2, Clock, Coins, Cpu, FileCode2, GitCommitHorizontal, Map as MapIcon, Settings2, ShieldCheck, Sparkles, Timer, Workflow, XCircle } from 'lucide-react'
import { motion } from 'motion/react'
import type { Schemas } from '../../api/client'
import { trackGlow } from '../../lib/glow'
import { formatDuration, formatNumber, formatUsd } from '../../lib/format'
import { item, list } from '../../lib/motion'
import { ChangeBar } from '../charts/Charts'
import { RevealText } from '../motion/RevealText'
import { RiskBadge, SeverityBadge } from '../ui/Badges'
import { Empty } from '../ui/States'
import { ChangeMap } from './ChangeMap'
import { SequenceDiagram } from './SequenceDiagram'

type Props = {
  pullRequest: Schemas['PullRequestDetailWithPatch']
  review: Schemas['ReviewOut'] | null | undefined
  risk: Schemas['RiskOut'] | null | undefined
  onOpenFile: (path: string) => void
  onRunReview: () => void
}

/** The overview of a PR: the AI summary with the estimated review effort, a diagram of the
 * changed flow, a table of what changed in each file, the top findings, the checks the review
 * ran and what it cost. */
export function WalkthroughTab({ pullRequest, review, risk, onOpenFile, onRunReview }: Props) {
  const findingsByFile = new Map<string, number>()
  for (const finding of review?.findings ?? []) {
    findingsByFile.set(finding.path, (findingsByFile.get(finding.path) ?? 0) + 1)
  }

  return (
    <motion.div className="stack lg" variants={list} initial="hidden" animate="show">
      <motion.section variants={item} className="summary-card card-body glow" onPointerMove={trackGlow} aria-labelledby="summary-title">
        <div className="row" style={{ marginBottom: 10 }}>
          <span className="ai-label" id="summary-title">
            <Sparkles size={14} aria-hidden="true" /> AI walkthrough
          </span>
          <span className="grow" />
          {review && (
            <>
              <span className="badge accent" title="Estimated from the lines and files a person has to read">
                <Timer size={12} aria-hidden="true" /> Review effort {review.effort.level}/5 · ~{review.effort.minutes} min
              </span>
              {review.mode === 'incremental' && review.compared_from_sha && (
                <span className="badge info" title="Only the files changed since the last review were reviewed; findings on the other files were carried over">
                  <GitCommitHorizontal size={12} aria-hidden="true" /> incremental since {review.compared_from_sha.slice(0, 7)}
                </span>
              )}
              <span className="badge outline"><Bot size={12} aria-hidden="true" /> {review.model}</span>
              <span className="badge outline">{review.prompt_version}</span>
            </>
          )}
        </div>
        {review ? (
          <p className="summary-text" style={{ margin: 0 }}>
            <RevealText key={review.id} text={review.summary ?? 'The model gave no summary that passed the faithfulness check.'} />
          </p>
        ) : (
          <Empty icon={Sparkles} title="No AI review yet">
            <button type="button" className="btn ai" onClick={onRunReview}>
              <Sparkles size={15} aria-hidden="true" /> Run AI review
            </button>
          </Empty>
        )}
        {review?.status === 'budget_exceeded' && (
          <div className="alert warn" style={{ marginTop: 12 }}>The review stopped early: it would have gone over its cost budget.</div>
        )}
      </motion.section>

      {review?.diagram && (
        <motion.section variants={item} className="card" aria-labelledby="diagram-title">
          <div className="card-header">
            <h2 id="diagram-title" className="row"><Workflow size={15} aria-hidden="true" /> Sequence diagram</h2>
            <span className="muted small">the flow this change touches, drawn from its code</span>
          </div>
          <div className="card-body">
            <SequenceDiagram source={review.diagram} />
          </div>
        </motion.section>
      )}

      <motion.section variants={item} className="card" aria-labelledby="map-title">
        <div className="card-header">
          <h2 id="map-title" className="row"><MapIcon size={15} aria-hidden="true" /> Change map</h2>
          <span className="muted small">{pullRequest.files.length} files</span>
        </div>
        <div className="card-body">
          <ChangeMap files={pullRequest.files} findings={review?.findings ?? []} onOpenFile={onOpenFile} />
        </div>
      </motion.section>

      <motion.div variants={item} className="grid two">
        <section className="card glow" onPointerMove={trackGlow} aria-labelledby="top-findings">
          <div className="card-header">
            <h2 id="top-findings">Top findings</h2>
            {review && <span className="muted small">{review.findings.length} shown · {review.dropped_findings} dropped by verification</span>}
          </div>
          <div className="card-body stack">
            {review && review.findings.length > 0 ? (
              review.findings.slice(0, 3).map((finding) => (
                <button key={finding.id} type="button" className="tree-row" style={{ alignItems: 'flex-start' }} onClick={() => onOpenFile(finding.path)}>
                  <SeverityBadge severity={finding.severity} />
                  <span style={{ textAlign: 'left' }}>
                    {finding.claim}
                    <br />
                    <code className="muted small">{finding.path}:{finding.line}</code>
                  </span>
                </button>
              ))
            ) : (
              <Empty icon={ShieldCheck} title={review ? 'Nothing the evidence could support' : 'Not reviewed yet'} />
            )}
          </div>
        </section>

        <section className="card glow" onPointerMove={trackGlow} aria-labelledby="review-stats">
          <div className="card-header">
            <h2 id="review-stats">Review run</h2>
            {risk && <RiskBadge level={risk.level} score={risk.score} />}
          </div>
          <div className="card-body">
            {review ? (
              <dl className="grid kpis" style={{ margin: 0, gridTemplateColumns: 'repeat(2, 1fr)' }}>
                <Stat icon={Cpu} label="Tokens" value={`${formatNumber(review.input_tokens)} in · ${formatNumber(review.output_tokens)} out`} />
                <Stat icon={Clock} label="Time" value={formatDuration(review.latency_ms)} />
                <Stat icon={Coins} label="Cost" value={review.cached ? 'cached · $0' : formatUsd(review.cost_usd)} />
                <Stat icon={Bot} label="Model calls" value={String(review.llm_calls)} />
              </dl>
            ) : (
              <p className="muted">Run a review to see its cost and timing.</p>
            )}
          </div>
        </section>

        {review && <ChecksCard review={review} />}
      </motion.div>

      <motion.section variants={item} className="card" aria-labelledby="changes-title">
        <div className="card-header">
          <h2 id="changes-title">Changes</h2>
          <span className="muted small">
            {pullRequest.totals.files_changed} files · <span style={{ color: 'var(--low)' }}>+{pullRequest.totals.additions}</span>{' '}
            <span style={{ color: 'var(--high)' }}>−{pullRequest.totals.deletions}</span>
          </span>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">File</th>
              <th scope="col">Status</th>
              <th scope="col">Changes</th>
              <th scope="col">Findings</th>
            </tr>
          </thead>
          <motion.tbody variants={list} initial="hidden" animate="show">
            {pullRequest.files.map((file) => (
              <motion.tr key={file.path} variants={item}>
                <td>
                  <button type="button" className="row link" style={{ border: 0, background: 'none', cursor: 'pointer', padding: 0 }} onClick={() => onOpenFile(file.path)}>
                    <FileCode2 size={14} aria-hidden="true" />
                    <code>{file.path}</code>
                  </button>
                </td>
                <td><span className="badge outline">{file.status}</span></td>
                <td className="nowrap">
                  <ChangeBar additions={file.additions} deletions={file.deletions} />{' '}
                  <span className="small" style={{ color: 'var(--low)' }}>+{file.additions}</span>{' '}
                  <span className="small" style={{ color: 'var(--high)' }}>−{file.deletions}</span>
                </td>
                <td>{findingsByFile.get(file.path) ? <span className="badge medium">{findingsByFile.get(file.path)}</span> : <span className="muted">—</span>}</td>
              </motion.tr>
            ))}
          </motion.tbody>
        </table>
      </motion.section>
    </motion.div>
  )
}

/** What the review checked besides the model: the merge check posted to GitHub, the static
 * analysis tools, and the repository settings it applied. */
function ChecksCard({ review }: { review: Schemas['ReviewOut'] }) {
  const config = review.config
  return (
    <section className="card glow" onPointerMove={trackGlow} aria-labelledby="checks-title">
      <div className="card-header">
        <h2 id="checks-title" className="row"><ShieldCheck size={15} aria-hidden="true" /> Checks and settings</h2>
      </div>
      <div className="card-body stack" style={{ gap: 10 }}>
        <div className="row">
          <span className="grow">Merge check on GitHub</span>
          {review.check_state === 'success' && <span className="badge low"><CheckCircle2 size={12} aria-hidden="true" /> passing</span>}
          {review.check_state === 'failure' && <span className="badge high"><XCircle size={12} aria-hidden="true" /> blocking</span>}
          {!review.check_state && <span className="muted small">{review.published_at ? 'not set (no permission)' : 'not published'}</span>}
        </div>
        <div className="row wrap">
          <span className="grow">Static analysis</span>
          {review.tools === null ? (
            <span className="muted small">off on this server</span>
          ) : review.tools.length === 0 ? (
            <span className="muted small">turned off in the settings</span>
          ) : (
            review.tools.map((tool) => (
              <span key={tool.name} className={`badge ${tool.ran ? (tool.findings ? 'medium' : 'low') : 'outline'}`} title={tool.error ?? `${tool.findings} on added lines, ${tool.duration_ms} ms`}>
                {tool.name} {tool.ran ? `· ${tool.findings}` : '· skipped'}
              </span>
            ))
          )}
        </div>
        <div className="row">
          <Settings2 size={14} aria-hidden="true" className="muted" />
          <span className="grow">Settings</span>
          {config ? (
            <span className="small">
              {config.source === 'file' ? <code>.codeevidence.yaml</code> : 'defaults'} · {config.profile}
              {config.guideline_files.length > 0 && ` · ${config.guideline_files.join(', ')}`}
            </span>
          ) : (
            <span className="muted small">—</span>
          )}
        </div>
        {config?.error && <div className="alert warn small">.codeevidence.yaml was not used: {config.error}</div>}
      </div>
    </section>
  )
}

function Stat({ icon: Icon, label, value }: { icon: typeof Cpu; label: string; value: string }) {
  return (
    <div>
      <dt className="kpi-label"><Icon size={13} aria-hidden="true" /> {label}</dt>
      <dd style={{ margin: '4px 0 0', fontWeight: 600 }}>{value}</dd>
    </div>
  )
}

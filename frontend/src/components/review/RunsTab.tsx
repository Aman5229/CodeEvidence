import { History } from 'lucide-react'
import { motion } from 'motion/react'
import type { Schemas } from '../../api/client'
import { formatDuration, formatNumber, formatUsd, timeAgo } from '../../lib/format'
import { item, list } from '../../lib/motion'
import { Empty, Loading } from '../ui/States'

/** Every review run of this PR: full or incremental, what model and prompt, what it cost,
 * what it found, and the merge check it posted. */
export function RunsTab({ runs, loading }: { runs: Schemas['ReviewRunOut'][] | undefined; loading: boolean }) {
  if (loading) return <Loading what="review runs" />
  if (!runs?.length) return <Empty icon={History} title="No review runs yet" />
  return (
    <div className="card">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Run</th>
            <th scope="col">Status</th>
            <th scope="col">Model · prompt</th>
            <th scope="col">Findings</th>
            <th scope="col">Tokens</th>
            <th scope="col">Time</th>
            <th scope="col">Cost</th>
            <th scope="col">When</th>
          </tr>
        </thead>
        <motion.tbody variants={list} initial="hidden" animate="show">
          {runs.map((run) => (
            <motion.tr key={run.id} variants={item}>
              <td className="mono">#{run.id}</td>
              <td>
                <span className={`badge ${run.status === 'completed' ? 'low' : 'medium'}`}>{run.status}</span>{' '}
                {run.cached && <span className="badge info">cached</span>}{' '}
                {run.mode === 'incremental' ? (
                  <span className="badge accent" title={run.base_review_id ? `Builds on review #${run.base_review_id}` : undefined}>incremental</span>
                ) : (
                  <span className="badge outline">full</span>
                )}{' '}
                {run.check_state && <span className={`badge ${run.check_state === 'success' ? 'low' : 'high'}`}>check {run.check_state}</span>}
              </td>
              <td className="small">{run.model}<br /><span className="muted">{run.prompt_version}</span></td>
              <td>{run.findings_shown} shown <span className="muted small">· {run.findings_dropped} dropped</span></td>
              <td className="small nowrap">{formatNumber(run.input_tokens)} / {formatNumber(run.output_tokens)}</td>
              <td className="nowrap">{formatDuration(run.latency_ms)}</td>
              <td>{formatUsd(run.cost_usd)}</td>
              <td className="muted nowrap" title={run.created_at}>{timeAgo(run.created_at)}</td>
            </motion.tr>
          ))}
        </motion.tbody>
      </table>
    </div>
  )
}

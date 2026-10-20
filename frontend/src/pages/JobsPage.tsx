import { CheckCircle2, Clock, Loader2, RefreshCw, RotateCcw, XCircle } from 'lucide-react'
import { motion } from 'motion/react'
import { type JobStatus, useJobs, useRetryJob } from '../api/hooks'
import { JobStatusBadge } from '../components/ui/Badges'
import { Empty, ErrorMessage, Loading } from '../components/ui/States'
import { useToast } from '../components/ui/toast'
import { TabBar, TabPanel, type TabSpec } from '../components/ui/Tabs'
import { useTab } from '../components/ui/useTab'
import { timeAgo } from '../lib/format'
import { item, list } from '../lib/motion'

const TABS: TabSpec[] = [
  { id: 'failed', label: 'Failed', icon: XCircle },
  { id: 'retrying', label: 'Retrying', icon: RotateCcw },
  { id: 'running', label: 'Running', icon: Loader2 },
  { id: 'queued', label: 'Queued', icon: Clock },
  { id: 'succeeded', label: 'Succeeded', icon: CheckCircle2 },
]

/** Background jobs by status. Failed ones are dead letters: retry them once the cause is fixed. */
export function JobsPage() {
  const [tab, setTab] = useTab(TABS)
  const jobs = useJobs(tab as JobStatus)
  const retry = useRetryJob()
  const toast = useToast()
  const retryJob = (jobId: number) =>
    retry.mutate(jobId, {
      onSuccess: () => toast({ tone: 'info', title: `Job #${jobId} queued again` }),
      onError: (error) => toast({ tone: 'error', title: `Could not retry job #${jobId}`, description: error.message }),
    })

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Jobs</h1>
          <p>File syncs, code indexing, AI reviews and publishing, run by the worker.</p>
        </div>
        <button type="button" className="btn" onClick={() => jobs.refetch()}>
          <RefreshCw size={14} aria-hidden="true" /> Refresh
        </button>
      </div>
      <TabBar tabs={TABS} active={tab} onSelect={setTab} label="Job status" />
      <TabPanel id={tab} index={TABS.findIndex((spec) => spec.id === tab)}>
        {jobs.isPending && <Loading what="jobs" />}
        {jobs.isError && <ErrorMessage error={jobs.error} />}
        {jobs.isSuccess && jobs.data.items.length === 0 && <Empty icon={CheckCircle2} title={`No ${tab} jobs`} />}
        {jobs.isSuccess && jobs.data.items.length > 0 && (
          <div className="card">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Job</th>
                  <th scope="col">Type</th>
                  <th scope="col">Status</th>
                  <th scope="col">Attempts</th>
                  <th scope="col">Last error</th>
                  <th scope="col">Updated</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <motion.tbody variants={list} initial="hidden" animate="show">
                {jobs.data.items.map((job) => (
                  <motion.tr key={job.id} variants={item}>
                    <td className="mono">#{job.id}</td>
                    <td><code>{job.job_type}</code></td>
                    <td><JobStatusBadge status={job.status} /></td>
                    <td>{job.attempts}</td>
                    <td style={{ maxWidth: 420 }}>
                      {job.last_error ? (
                        <details>
                          <summary className="truncate small" style={{ color: 'var(--high)' }}>{job.last_error}</summary>
                          <pre className="small" style={{ marginTop: 6 }}>{job.last_error}</pre>
                        </details>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="muted nowrap">{timeAgo(job.updated_at)}</td>
                    <td>
                      {job.status === 'failed' && (
                        <button type="button" className="btn sm" disabled={retry.isPending} onClick={() => retryJob(job.id)}>
                          <RotateCcw size={13} aria-hidden="true" /> Retry
                        </button>
                      )}
                    </td>
                  </motion.tr>
                ))}
              </motion.tbody>
            </table>
          </div>
        )}
      </TabPanel>
    </div>
  )
}

import { AlertTriangle, CheckCircle2, CircleDot, GitMerge, Info, ShieldAlert, XCircle } from 'lucide-react'

const SEVERITY_ICON = { high: ShieldAlert, medium: AlertTriangle, low: Info } as const

export function SeverityBadge({ severity }: { severity: string }) {
  const Icon = SEVERITY_ICON[severity as keyof typeof SEVERITY_ICON] ?? Info
  return (
    <span className={`badge ${severity}`}>
      <Icon size={12} aria-hidden="true" />
      {severity}
    </span>
  )
}

export function RiskBadge({ level, score }: { level: string | null | undefined; score?: number | null }) {
  if (!level) return <span className="badge outline">not scored</span>
  return (
    <span className={`badge ${level}`} title={`Risk ${score ?? ''}/100`}>
      {score != null && <strong>{score}</strong>} {level}
    </span>
  )
}

export function PullRequestState({ status, merged }: { status: string; merged: boolean }) {
  if (merged) {
    return (
      <span className="state merged">
        <GitMerge size={13} aria-hidden="true" /> Merged
      </span>
    )
  }
  return status === 'open' ? (
    <span className="state open">
      <CircleDot size={13} aria-hidden="true" /> Open
    </span>
  ) : (
    <span className="state closed">
      <XCircle size={13} aria-hidden="true" /> Closed
    </span>
  )
}

export function JobStatusBadge({ status }: { status: string }) {
  const tone = { succeeded: 'low', failed: 'high', retrying: 'medium', running: 'info', queued: 'outline' }[status] ?? 'outline'
  return (
    <span className={`badge ${tone}`}>
      {status === 'succeeded' && <CheckCircle2 size={12} aria-hidden="true" />}
      {status}
    </span>
  )
}

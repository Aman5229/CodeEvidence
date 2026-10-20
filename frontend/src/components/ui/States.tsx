import type { LucideIcon } from 'lucide-react'
import { AlertTriangle, Inbox } from 'lucide-react'
import { ApiError } from '../../api/client'

export function Skeleton({ height = 16, width = '100%' }: { height?: number; width?: number | string }) {
  return <div className="skeleton" style={{ height, width }} aria-hidden="true" />
}

/** A few grey bars while data loads; the text is for screen readers. */
export function Loading({ what, lines = 3 }: { what: string; lines?: number }) {
  return (
    <div className="stack" role="status" aria-live="polite">
      <span className="sr-only">Loading {what}…</span>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} height={index === 0 ? 22 : 14} width={`${90 - index * 15}%`} />
      ))}
    </div>
  )
}

export function ErrorMessage({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : 'Something went wrong'
  const unauthorized = error instanceof ApiError && error.status === 401
  return (
    <div className="alert error" role="alert">
      <AlertTriangle size={16} aria-hidden="true" />
      <div>
        {message}.
        {unauthorized && ' Add your API key in Settings.'}
      </div>
    </div>
  )
}

export function Empty({ icon: Icon = Inbox, title, children }: { icon?: LucideIcon; title: string; children?: React.ReactNode }) {
  return (
    <div className="empty">
      <Icon size={32} aria-hidden="true" />
      <strong style={{ color: 'var(--text)' }}>{title}</strong>
      {children && <div className="small">{children}</div>}
    </div>
  )
}

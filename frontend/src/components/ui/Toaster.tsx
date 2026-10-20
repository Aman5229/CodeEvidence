import { CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useState } from 'react'
import { spring } from '../../lib/motion'
import { ToastContext, type ToastInput } from './toast'

type Toast = ToastInput & { id: number }
const LIFETIME_MS = 4200
const ICONS = { success: CheckCircle2, error: XCircle, info: Info }
let nextId = 1

/** Toasts stack in the bottom-right corner, spring in, shrink a progress line, and leave. */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((toast) => toast.id !== id)), [])
  const push = useCallback(
    (toast: ToastInput) => {
      const id = nextId++
      setToasts((all) => [...all.slice(-3), { ...toast, id }])
      setTimeout(() => dismiss(id), LIFETIME_MS)
    },
    [dismiss],
  )

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        <AnimatePresence initial={false}>
          {toasts.map((toast) => {
            const tone = toast.tone ?? 'success'
            const Icon = ICONS[tone]
            return (
              <motion.div
                key={toast.id}
                layout
                className={`toast ${tone}`}
                initial={{ opacity: 0, y: 24, scale: 0.94 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, x: 60, transition: { duration: 0.18 } }}
                transition={spring}
              >
                <Icon size={17} aria-hidden="true" className="toast-icon" />
                <div className="grow">
                  <strong>{toast.title}</strong>
                  {toast.description && <div className="small muted">{toast.description}</div>}
                </div>
                <button type="button" className="btn ghost sm" onClick={() => dismiss(toast.id)} aria-label="Dismiss">
                  <X size={14} />
                </button>
                <motion.span
                  className="toast-timer"
                  initial={{ scaleX: 1 }}
                  animate={{ scaleX: 0 }}
                  transition={{ duration: LIFETIME_MS / 1000, ease: 'linear' }}
                />
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  )
}

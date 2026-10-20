import { createContext, useContext } from 'react'

export type ToastTone = 'success' | 'error' | 'info'
export type ToastInput = { tone?: ToastTone; title: string; description?: string }

export const ToastContext = createContext<(toast: ToastInput) => void>(() => {})

/** Show a short message in the corner: `toast({ title: 'Saved' })`. */
export function useToast() {
  return useContext(ToastContext)
}

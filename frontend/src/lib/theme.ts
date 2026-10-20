import { useSyncExternalStore } from 'react'

export type Theme = 'dark' | 'light'
const STORAGE_KEY = 'codeevidence.theme'
const CHANGED = 'codeevidence:theme'

export function getTheme(): Theme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'dark' || saved === 'light') return saved
  } catch {
    // storage blocked: fall back to the system preference
  }
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // not remembered; still applied for this visit
  }
  window.dispatchEvent(new Event(CHANGED))
}

/** The current theme, re-rendering whenever any component switches it. */
export function useTheme(): Theme {
  return useSyncExternalStore(
    (onChange) => {
      window.addEventListener(CHANGED, onChange)
      return () => window.removeEventListener(CHANGED, onChange)
    },
    () => (document.documentElement.dataset.theme as Theme | undefined) ?? getTheme(),
  )
}

/** Switch theme with a circle that grows from `origin` (the button that was clicked), using
 * the View Transitions API. Browsers without it, and users who prefer reduced motion, get an
 * instant switch. */
export function switchTheme(next: Theme, origin?: { x: number; y: number }): void {
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (!origin || reduced || typeof document.startViewTransition !== 'function') {
    applyTheme(next)
    return
  }
  const transition = document.startViewTransition(() => applyTheme(next))
  transition.ready
    .then(() => {
      const radius = Math.hypot(Math.max(origin.x, innerWidth - origin.x), Math.max(origin.y, innerHeight - origin.y))
      document.documentElement.animate(
        { clipPath: [`circle(0px at ${origin.x}px ${origin.y}px)`, `circle(${radius}px at ${origin.x}px ${origin.y}px)`] },
        { duration: 600, easing: 'cubic-bezier(0.22, 1, 0.36, 1)', pseudoElement: '::view-transition-new(root)' },
      )
    })
    .catch(() => {
      // the transition was skipped: the theme is already applied
    })
}

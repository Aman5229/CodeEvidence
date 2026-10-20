import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { MotionGlobalConfig } from 'motion/react'
import { afterEach, vi } from 'vitest'

// Tests check what is shown, not how it moves: every animation finishes instantly.
MotionGlobalConfig.skipAnimations = true

// jsdom has no matchMedia. Tests run as a user who prefers reduced motion, so numbers render
// their final value at once instead of counting up.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: query.includes('prefers-reduced-motion'),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }),
})

// jsdom has no IntersectionObserver (used by "animate when scrolled into view").
class NoopIntersectionObserver {
  readonly root = null
  readonly rootMargin = ''
  readonly thresholds = []
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
}
globalThis.IntersectionObserver ??= NoopIntersectionObserver as unknown as typeof IntersectionObserver

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  localStorage.clear()
})

import type { PointerEvent } from 'react'

/** Moves a `.glow` card's spotlight to the pointer: two CSS variables, no re-render. */
export function trackGlow(event: PointerEvent<HTMLElement>): void {
  const box = event.currentTarget.getBoundingClientRect()
  event.currentTarget.style.setProperty('--mx', `${event.clientX - box.left}px`)
  event.currentTarget.style.setProperty('--my', `${event.clientY - box.top}px`)
}

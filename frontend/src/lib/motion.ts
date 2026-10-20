import { stagger, type Transition, type Variants } from 'motion/react'

// One motion language for the whole app: quick, springy, never in the way.
export const spring: Transition = { type: 'spring', stiffness: 420, damping: 34, mass: 0.8 }
export const softSpring: Transition = { type: 'spring', stiffness: 220, damping: 28 }
export const easeOut: Transition = { duration: 0.35, ease: [0.22, 1, 0.36, 1] }

/** A container whose children appear one after another. */
export const list: Variants = {
  hidden: {},
  show: { transition: { delayChildren: stagger(0.045, { startDelay: 0.04 }) } },
}

/** A child of `list`: rises a little and fades in. */
export const item: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: spring },
}

/** Tab panels slide in from the side the user moved towards. */
export const panel: Variants = {
  enter: (direction: number) => ({ opacity: 0, x: direction * 28 }),
  center: { opacity: 1, x: 0, transition: { ...spring, opacity: { duration: 0.2 } } },
  exit: (direction: number) => ({ opacity: 0, x: direction * -28, transition: { duration: 0.12 } }),
}

/** Cards rise a little under the pointer (motion owns their transform, so CSS cannot). */
export const hoverLift = { y: -3, transition: spring }


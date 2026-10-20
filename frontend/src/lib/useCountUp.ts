import { animate, type MotionValue, useMotionValue, useReducedMotion, useTransform } from 'motion/react'
import { useEffect } from 'react'

/** Display text for a number that counts up to `value`, and glides when it changes.
 * `format` must be a stable function (defined once, outside the component). */
export function useCountUp(value: number, format: (value: number) => string): MotionValue<string> {
  const reduced = useReducedMotion()
  const current = useMotionValue(reduced ? value : 0)
  const text = useTransform(current, format)
  useEffect(() => {
    if (reduced) {
      current.set(value)
      return
    }
    const controls = animate(current, value, { duration: 1.1, ease: [0.22, 1, 0.36, 1] })
    return () => controls.stop()
  }, [current, value, reduced])
  return text
}

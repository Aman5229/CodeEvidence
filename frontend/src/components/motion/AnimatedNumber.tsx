import { motion } from 'motion/react'
import { formatNumber, formatPercent, formatUsd } from '../../lib/format'
import { useCountUp } from '../../lib/useCountUp'

const FORMATS = {
  number: (value: number) => formatNumber(Math.round(value)),
  percent: (value: number) => formatPercent(value),
  usd: (value: number) => formatUsd(value),
  decimal: (value: number) => value.toFixed(1),
}

/** A number that counts up when it appears. Screen readers get the final value only. */
export function AnimatedNumber({ value, format = 'number' }: { value: number; format?: keyof typeof FORMATS }) {
  const text = useCountUp(value, FORMATS[format])
  return (
    <>
      <span className="sr-only">{FORMATS[format](value)}</span>
      <motion.span aria-hidden="true">{text}</motion.span>
    </>
  )
}

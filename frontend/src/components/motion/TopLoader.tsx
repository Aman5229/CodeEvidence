import { useIsFetching, useIsMutating } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'

const BACKGROUND_POLLS = new Set(['readiness', 'review-runs'])

/** A thin light that sweeps across the top while data loads (background polling excluded). */
export function TopLoader() {
  const fetching = useIsFetching({ predicate: (query) => !BACKGROUND_POLLS.has(String(query.queryKey[0])) })
  const mutating = useIsMutating()
  return (
    <AnimatePresence>
      {fetching + mutating > 0 && (
        <motion.div
          className="top-loader"
          aria-hidden="true"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { delay: 0.2 } }}
        />
      )}
    </AnimatePresence>
  )
}

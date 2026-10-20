import { AnimatePresence, motion } from 'motion/react'
import { Suspense, useEffect } from 'react'
import { useLocation, useOutlet } from 'react-router'
import { easeOut } from '../../lib/motion'
import { Loading } from '../ui/States'

/** The current page, sliding up out of a light blur when the route changes. Pages load as
 * separate chunks; skeletons show while one downloads. */
export function AnimatedOutlet() {
  const { pathname } = useLocation()
  const outlet = useOutlet()
  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [pathname])

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={pathname}
        initial={{ opacity: 0, y: 16, filter: 'blur(6px)' }}
        animate={{ opacity: 1, y: 0, filter: 'blur(0px)', transitionEnd: { filter: 'none' } }}
        exit={{ opacity: 0, y: -8, filter: 'blur(4px)', transition: { duration: 0.14 } }}
        transition={easeOut}
      >
        <Suspense fallback={<Loading what="the page" lines={5} />}>{outlet}</Suspense>
      </motion.div>
    </AnimatePresence>
  )
}

import { motion, stagger, useReducedMotion } from 'motion/react'

const words = { hidden: {}, show: { transition: { delayChildren: stagger(0.016) } } }
const word = {
  hidden: { opacity: 0, y: 6, filter: 'blur(4px)' },
  show: { opacity: 1, y: 0, filter: 'blur(0px)', transition: { duration: 0.4 } },
}

/** Text that appears word by word, like a model writing it. Screen readers get it whole. */
export function RevealText({ text }: { text: string }) {
  const reduced = useReducedMotion()
  if (reduced) return <>{text}</>
  return (
    <>
      <span className="sr-only">{text}</span>
      <motion.span aria-hidden="true" initial="hidden" animate="show" variants={words}>
        {text.split(/(\s+)/).map((part, index) =>
          /^\s+$/.test(part) ? (
            part
          ) : (
            <motion.span key={index} variants={word} style={{ display: 'inline-block' }}>
              {part}
            </motion.span>
          ),
        )}
      </motion.span>
    </>
  )
}

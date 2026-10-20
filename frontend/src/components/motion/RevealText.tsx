import { motion, stagger, useReducedMotion } from 'motion/react'

const words = { hidden: {}, show: { transition: { delayChildren: stagger(0.016) } } }
const word = {
  hidden: { opacity: 0, y: 6, filter: 'blur(4px)' },
  show: { opacity: 1, y: 0, filter: 'blur(0px)', transition: { duration: 0.4 } },
}

// `inline code` is kept whole (it may contain spaces) and shown as code; other text splits into words
const PIECES = /(`[^`\n]+`|\s+)/

function Piece({ part }: { part: string }) {
  return part.startsWith('`') && part.endsWith('`') && part.length > 2 ? <code>{part.slice(1, -1)}</code> : <>{part}</>
}

/** Text that appears word by word, like a model writing it. Screen readers get it whole. */
export function RevealText({ text }: { text: string }) {
  const reduced = useReducedMotion()
  const parts = text.split(PIECES).filter(Boolean)
  if (reduced) return <>{parts.map((part, index) => <Piece key={index} part={part} />)}</>
  return (
    <>
      <span className="sr-only">{text.replaceAll('`', '')}</span>
      <motion.span aria-hidden="true" initial="hidden" animate="show" variants={words}>
        {parts.map((part, index) =>
          /^\s+$/.test(part) ? (
            part
          ) : (
            <motion.span key={index} variants={word} style={{ display: 'inline-block' }}>
              <Piece part={part} />
            </motion.span>
          ),
        )}
      </motion.span>
    </>
  )
}

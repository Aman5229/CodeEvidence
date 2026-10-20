import { motion } from 'motion/react'
import { useEffect, useId, useState } from 'react'
import { useTheme } from '../../lib/theme'
import { Skeleton } from '../ui/States'

type Drawn = { key: string; svg?: string; failed?: boolean }

/** The review's sequence diagram, drawn by Mermaid. Mermaid is large, so it loads only when a
 * diagram is shown. Its strict mode escapes labels and allows no links or scripts; the server
 * already accepts only a safe subset of the syntax. If drawing fails, the source is shown. */
export function SequenceDiagram({ source }: { source: string }) {
  const id = `diagram-${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  const theme = useTheme()
  const key = `${theme}\n${source}`
  const [drawn, setDrawn] = useState<Drawn>({ key: '' })

  useEffect(() => {
    let cancelled = false
    import('mermaid')
      .then(async ({ default: mermaid }) => {
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: theme === 'dark' ? 'dark' : 'neutral',
          fontFamily: 'Inter, system-ui, sans-serif',
        })
        const { svg } = await mermaid.render(id, source)
        if (!cancelled) setDrawn({ key, svg })
      })
      .catch(() => {
        if (!cancelled) setDrawn({ key, failed: true })
      })
    return () => {
      cancelled = true
    }
  }, [id, key, source, theme])

  if (drawn.key !== key) return <Skeleton height={180} />
  if (drawn.failed || !drawn.svg) {
    return (
      <div className="stack" style={{ gap: 6 }}>
        <span className="muted small">The diagram could not be drawn here; its Mermaid source:</span>
        <pre className="code-block">{source}</pre>
      </div>
    )
  }
  return (
    <motion.div
      className="diagram"
      role="img"
      aria-label="Sequence diagram of the change"
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.35 }}
      dangerouslySetInnerHTML={{ __html: drawn.svg }}
    />
  )
}

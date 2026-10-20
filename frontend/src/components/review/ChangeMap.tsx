import { motion } from 'motion/react'
import type { Schemas } from '../../api/client'
import { spring } from '../../lib/motion'

/** Every changed file as a block, sized by lines changed and coloured by its findings.
 * The blocks grow in one after another; click one to open that file's diff. */
export function ChangeMap({
  files,
  findings,
  onOpenFile,
}: {
  files: Schemas['PullRequestFileWithPatch'][]
  findings: Schemas['FindingOut'][]
  onOpenFile: (path: string) => void
}) {
  const severities = new Map<string, Set<string>>()
  for (const finding of findings) {
    severities.set(finding.path, new Set([...(severities.get(finding.path) ?? []), finding.severity]))
  }
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="change-map" role="group" aria-label="Change map: files sized by lines changed">
        {files.map((file, index) => {
          const lines = file.additions + file.deletions
          const found = severities.get(file.path)
          const tone = found?.has('high') ? 'has-high' : found ? 'has-findings' : ''
          const label = `${file.path}: ${lines} lines changed${found ? `, findings: ${[...found].join(', ')}` : ''}`
          return (
            <motion.button
              key={file.path}
              type="button"
              className={`change-cell ${tone}`}
              style={{ flexGrow: Math.max(lines, 1) }}
              initial={{ scaleY: 0, opacity: 0 }}
              animate={{ scaleY: 1, opacity: 1 }}
              transition={{ ...spring, delay: 0.05 + Math.min(index, 30) * 0.035 }}
              whileHover={{ y: -2 }}
              onClick={() => onOpenFile(file.path)}
              aria-label={label}
              title={label}
            />
          )
        })}
      </div>
      <div className="row small muted wrap" style={{ gap: 14 }}>
        <span className="row"><span className="swatch" style={{ background: 'var(--bg-hover)' }} /> no findings</span>
        <span className="row"><span className="swatch" style={{ background: 'var(--medium)' }} /> findings</span>
        <span className="row"><span className="swatch" style={{ background: 'var(--high)' }} /> high severity</span>
        <span>Width = lines changed. Click a block to open the file.</span>
      </div>
    </div>
  )
}

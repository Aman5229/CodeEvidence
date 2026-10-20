import { ChevronDown, FileCode2 } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import type { Schemas } from '../../api/client'
import { DiffView } from '../diff/DiffView'
import { FileTree } from '../diff/FileTree'
import { FindingCard } from './FindingCard'

const fileAnchor = (path: string) => `file-${encodeURIComponent(path)}`
const scrollToFile = (path: string, behavior: ScrollBehavior) =>
  document.getElementById(fileAnchor(path))?.scrollIntoView?.({ behavior, block: 'start' })

/** Every changed file's diff, with the review's findings shown under the lines they are about.
 * Files collapse and expand; the file opened from elsewhere flashes once. */
export function FilesTab({
  pullRequest,
  findings,
  focusPath,
}: {
  pullRequest: Schemas['PullRequestDetailWithPatch']
  findings: Schemas['FindingOut'][]
  focusPath: string | null
}) {
  const [onlyFlagged, setOnlyFlagged] = useState(false)
  const [selected, setSelected] = useState<string | null>(focusPath)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const byFile = new Map<string, Schemas['FindingOut'][]>()
  for (const finding of findings) byFile.set(finding.path, [...(byFile.get(finding.path) ?? []), finding])

  const files = pullRequest.files.filter((file) => !onlyFlagged || byFile.has(file.path))
  const select = (path: string) => {
    setSelected(path)
    scrollToFile(path, 'smooth')
  }
  const toggle = (path: string) =>
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  useEffect(() => {
    if (focusPath) scrollToFile(focusPath, 'auto')
  }, [focusPath])

  return (
    <div className="grid sidebar-layout">
      <div className="stack">
        <label className="row small">
          <input type="checkbox" checked={onlyFlagged} onChange={(event) => setOnlyFlagged(event.target.checked)} />
          Only files with findings ({byFile.size})
        </label>
        <FileTree
          files={files.map((file) => ({ ...file, findings: byFile.get(file.path)?.length ?? 0 }))}
          selected={selected}
          onSelect={select}
        />
      </div>
      <div className="stack">
        {files.map((file) => {
          const open = !collapsed.has(file.path)
          const comments = new Map<number, React.ReactNode>()
          for (const finding of byFile.get(file.path) ?? []) {
            comments.set(
              finding.line,
              <motion.div className="stack" style={{ gap: 8 }} initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}>
                {comments.get(finding.line)}
                <FindingCard finding={finding} pullRequestId={pullRequest.id} compact />
              </motion.div>,
            )
          }
          return (
            <section
              key={file.path}
              id={fileAnchor(file.path)}
              className={`file-block${file.path === focusPath ? ' flash' : ''}`}
              aria-label={file.path}
            >
              <div className="file-head">
                <button type="button" className="file-toggle" aria-expanded={open} aria-label={open ? `Collapse ${file.path}` : `Expand ${file.path}`} onClick={() => toggle(file.path)}>
                  <ChevronDown size={15} />
                </button>
                <FileCode2 size={14} aria-hidden="true" />
                <code className="grow truncate">{file.path}</code>
                {byFile.has(file.path) && <span className="badge medium">{byFile.get(file.path)?.length} findings</span>}
                <span className="small" style={{ color: 'var(--low)' }}>+{file.additions}</span>
                <span className="small" style={{ color: 'var(--high)' }}>−{file.deletions}</span>
              </div>
              <AnimatePresence initial={false}>
                {open && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
                    style={{ overflow: 'hidden' }}
                  >
                    <DiffView path={file.path} patch={file.patch} comments={comments} />
                  </motion.div>
                )}
              </AnimatePresence>
            </section>
          )
        })}
      </div>
    </div>
  )
}

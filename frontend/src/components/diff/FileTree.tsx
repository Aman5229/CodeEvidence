import { ChevronDown, ChevronRight, FileCode2, Folder } from 'lucide-react'
import { useState } from 'react'

export type TreeFile = { path: string; additions: number; deletions: number; findings: number }

/** Files grouped by folder, folders collapsible; each file shows its findings and size. */
export function FileTree({ files, selected, onSelect }: { files: TreeFile[]; selected: string | null; onSelect: (path: string) => void }) {
  const [closed, setClosed] = useState<Set<string>>(new Set())
  const folders = new Map<string, TreeFile[]>()
  for (const file of files) {
    const folder = file.path.includes('/') ? file.path.slice(0, file.path.lastIndexOf('/')) : ''
    folders.set(folder, [...(folders.get(folder) ?? []), file])
  }
  const toggle = (folder: string) =>
    setClosed((current) => {
      const next = new Set(current)
      if (next.has(folder)) next.delete(folder)
      else next.add(folder)
      return next
    })

  return (
    <nav className="card tree" aria-label="Changed files">
      {[...folders.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([folder, folderFiles]) => (
        <div key={folder}>
          {folder && (
            <button type="button" className="tree-row" aria-expanded={!closed.has(folder)} onClick={() => toggle(folder)}>
              {closed.has(folder) ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
              <Folder size={14} aria-hidden="true" />
              <span className="truncate" title={folder}>{folder}</span>
            </button>
          )}
          {!closed.has(folder) &&
            folderFiles.map((file) => (
              <button
                key={file.path}
                type="button"
                className={`tree-row${file.path === selected ? ' selected' : ''}`}
                style={{ paddingLeft: folder ? 30 : 8 }}
                onClick={() => onSelect(file.path)}
                title={file.path}
              >
                <FileCode2 size={14} aria-hidden="true" />
                <span className="truncate">{file.path.split('/').pop()}</span>
                <span className="tree-count">
                  {file.findings > 0 && <span className="badge medium">{file.findings}</span>}
                  <span className="small" style={{ color: 'var(--low)' }}>+{file.additions}</span>
                  <span className="small" style={{ color: 'var(--high)' }}>−{file.deletions}</span>
                </span>
              </button>
            ))}
        </div>
      ))}
    </nav>
  )
}

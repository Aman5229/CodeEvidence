import { Fragment } from 'react'
import { parseDiff } from './diff'
import { highlightLine, languageOf } from './highlight'

const MAX_LINES = 1500 // very large diffs are cut: rendering them freezes the page
const SIGN = { hunk: '', added: '+', removed: '-', context: ' ' }

/** A unified diff with line numbers and syntax colours. `comments` maps a new-file line
 * number to what is shown right under that line (the review's findings). */
export function DiffView({
  path,
  patch,
  comments = new Map(),
}: {
  path: string
  patch: string | null
  comments?: Map<number, React.ReactNode>
}) {
  if (!patch) {
    return <p className="muted small" style={{ padding: '12px 14px' }}>No diff to show: a binary file, or too large for GitHub.</p>
  }
  const language = languageOf(path)
  const lines = parseDiff(patch)
  return (
    <div className="diff" role="table" aria-label={`Diff of ${path}`}>
      {lines.slice(0, MAX_LINES).map((line, index) => {
        const comment = line.newLine != null && line.kind !== 'removed' ? comments.get(line.newLine) : undefined
        return (
          <Fragment key={index}>
            <div role="row" className={`diff-line ${line.kind}${comment ? ' flagged' : ''}`}>
              <span className="no" role="cell">{line.oldLine ?? ''}</span>
              <span className="no" role="cell">{line.newLine ?? ''}</span>
              <span className="sign" role="cell">{SIGN[line.kind]}</span>
              {line.kind === 'hunk' ? (
                <code role="cell">{line.text}</code>
              ) : (
                <code role="cell" dangerouslySetInnerHTML={{ __html: highlightLine(line.text, language) }} />
              )}
            </div>
            {comment && <div className="inline-comment">{comment}</div>}
          </Fragment>
        )
      })}
      {lines.length > MAX_LINES && <p className="muted small" style={{ padding: 12 }}>{lines.length - MAX_LINES} more lines not shown.</p>}
    </div>
  )
}

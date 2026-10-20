import { Fragment } from 'react'

const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[A-Z]\d{1,3}\])/g
const CITATION = /^\[([A-Z]\d{1,3})\]$/
const LIST_ITEM = /^\s*(?:[-*]|\d+\.)\s+(.*)$/

type Block = { kind: 'code'; text: string } | { kind: 'list'; ordered: boolean; items: string[] } | { kind: 'paragraph'; text: string }

/** Split Markdown into code blocks, lists and paragraphs. */
function blocks(markdown: string): Block[] {
  const result: Block[] = []
  const lines = markdown.replace(/\r\n/g, '\n').split('\n')
  let paragraph: string[] = []
  const flush = () => {
    if (paragraph.length) result.push({ kind: 'paragraph', text: paragraph.join(' ') })
    paragraph = []
  }
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index]
    if (line.trimStart().startsWith('```')) {
      flush()
      const code: string[] = []
      index++
      while (index < lines.length && !lines[index].trimStart().startsWith('```')) code.push(lines[index++])
      result.push({ kind: 'code', text: code.join('\n') })
    } else if (LIST_ITEM.test(line)) {
      flush()
      const ordered = /^\s*\d+\./.test(line)
      const items: string[] = []
      while (index < lines.length && LIST_ITEM.test(lines[index])) items.push(LIST_ITEM.exec(lines[index++])![1])
      index--
      result.push({ kind: 'list', ordered, items })
    } else if (!line.trim()) {
      flush()
    } else {
      paragraph.push(line.replace(/^#+\s*/, '').trim())
    }
  }
  flush()
  return result
}

function Inline({ text, onCite, known }: { text: string; onCite?: (id: string) => void; known?: Set<string> }) {
  return (
    <>
      {text.split(INLINE).map((part, index) => {
        if (!part) return null
        const citation = CITATION.exec(part)
        if (citation) {
          const id = citation[1]
          if (known && !known.has(id)) return null // made up by the model: not shown
          return (
            <button key={index} type="button" className="cite" onClick={() => onCite?.(id)} aria-label={`Evidence ${id}`}>
              {id}
            </button>
          )
        }
        if (part.startsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>
        if (part.startsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>
        return <Fragment key={index}>{part}</Fragment>
      })}
    </>
  )
}

/** A small, safe Markdown renderer for chat answers: paragraphs, lists, code, bold and
 * citations like [H2] as buttons. It builds React elements, never HTML from the text. */
export function Markdown({ text, onCite, known }: { text: string; onCite?: (id: string) => void; known?: Set<string> }) {
  return (
    <div className="markdown">
      {blocks(text).map((block, index) => {
        if (block.kind === 'code') return <pre key={index} className="code-block">{block.text}</pre>
        if (block.kind === 'list') {
          const List = block.ordered ? 'ol' : 'ul'
          return (
            <List key={index}>
              {block.items.map((entry, itemIndex) => (
                <li key={itemIndex}><Inline text={entry} onCite={onCite} known={known} /></li>
              ))}
            </List>
          )
        }
        return <p key={index}><Inline text={block.text} onCite={onCite} known={known} /></p>
      })}
    </div>
  )
}

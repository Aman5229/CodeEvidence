export type Line = { kind: 'hunk' | 'added' | 'removed' | 'context'; text: string; oldLine?: number; newLine?: number }

const HUNK_HEADER = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/

/** Turn a unified diff into lines with old and new line numbers (like app/modules/code/diff.py). */
export function parseDiff(patch: string): Line[] {
  const lines: Line[] = []
  let oldLine = 0
  let newLine = 0
  for (const raw of patch.split('\n')) {
    const header = HUNK_HEADER.exec(raw)
    if (header) {
      oldLine = Number(header[1])
      newLine = Number(header[2])
      lines.push({ kind: 'hunk', text: raw })
    } else if (raw.startsWith('\\')) {
      continue // "\ No newline at end of file"
    } else if (raw.startsWith('+')) {
      lines.push({ kind: 'added', text: raw.slice(1), newLine: newLine++ })
    } else if (raw.startsWith('-')) {
      lines.push({ kind: 'removed', text: raw.slice(1), oldLine: oldLine++ })
    } else {
      lines.push({ kind: 'context', text: raw.slice(1), oldLine: oldLine++, newLine: newLine++ })
    }
  }
  return lines
}

import { describe, expect, it } from 'vitest'
import { parseDiff } from './diff'
import { highlightLine, languageOf } from './highlight'

const PATCH = '@@ -1,3 +1,3 @@\n def f():\n-    return 1\n+    return 2\n\\ No newline at end of file'

describe('parseDiff', () => {
  it('numbers old and new lines like the backend parser', () => {
    expect(parseDiff(PATCH)).toEqual([
      { kind: 'hunk', text: '@@ -1,3 +1,3 @@' },
      { kind: 'context', text: 'def f():', oldLine: 1, newLine: 1 },
      { kind: 'removed', text: '    return 1', oldLine: 2 },
      { kind: 'added', text: '    return 2', newLine: 2 },
    ])
  })
})

describe('highlight', () => {
  it('picks the language from the extension', () => {
    expect(languageOf('app/main.py')).toBe('python')
    expect(languageOf('src/App.tsx')).toBe('typescript')
    expect(languageOf('Makefile')).toBeNull()
  })

  it('never lets code become HTML', () => {
    expect(highlightLine('<script>alert(1)</script>', null)).toBe('&lt;script&gt;alert(1)&lt;/script&gt;')
    expect(highlightLine('x = "<b>"', 'python')).not.toContain('<b>')
  })
})

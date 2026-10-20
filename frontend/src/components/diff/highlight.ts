import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import go from 'highlight.js/lib/languages/go'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import python from 'highlight.js/lib/languages/python'
import ruby from 'highlight.js/lib/languages/ruby'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'

// Only the languages these repositories use: the full highlight.js bundle is ~1 MB.
for (const [name, language] of Object.entries({ bash, css, go, javascript, json, python, ruby, sql, typescript, xml, yaml })) {
  hljs.registerLanguage(name, language)
}

const BY_EXTENSION: Record<string, string> = {
  py: 'python', js: 'javascript', jsx: 'javascript', mjs: 'javascript', cjs: 'javascript', ts: 'typescript',
  tsx: 'typescript', json: 'json', yml: 'yaml', yaml: 'yaml', sh: 'bash', go: 'go', rb: 'ruby', sql: 'sql',
  css: 'css', html: 'xml', xml: 'xml', toml: 'yaml',
}

export function languageOf(path: string): string | null {
  const extension = path.split('.').pop()?.toLowerCase() ?? ''
  return BY_EXTENSION[extension] ?? null
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** One line as highlighted HTML. highlight.js escapes the code itself, so the output is safe to inject. */
export function highlightLine(text: string, language: string | null): string {
  if (!language) return escapeHtml(text)
  return hljs.highlight(text, { language, ignoreIllegals: true }).value
}

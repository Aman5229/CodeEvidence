import { getApiKey } from './apiKey'
import { API_URL, ApiError, type Schemas } from './client'

/** The "done" event: both messages as stored (see ChatDoneEvent in app/schemas/chat.py). */
export type ChatDone = {
  question: Schemas['ChatMessageOut']
  answer: Schemas['ChatMessageOut']
  unknown_citations: string[]
}
export type ChatEvent =
  | { event: 'token'; text: string }
  | { event: 'done'; data: ChatDone }
  | { event: 'error'; message: string }

type RawEvent = { event: string; data: string }

/** Split server-sent events text into complete events and the unfinished rest (an event ends
 * with a blank line; lines starting with ":" are keep-alive comments). */
export function parseEvents(buffer: string): { events: RawEvent[]; rest: string } {
  const blocks = buffer.split(/\r?\n\r?\n/)
  const rest = blocks.pop() ?? ''
  const events: RawEvent[] = []
  for (const block of blocks) {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split(/\r?\n/)) {
      if (!line || line.startsWith(':')) continue
      const colon = line.indexOf(':')
      const field = colon === -1 ? line : line.slice(0, colon)
      const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '')
      if (field === 'event') event = value
      else if (field === 'data') data.push(value)
    }
    if (data.length) events.push({ event, data: data.join('\n') })
  }
  return { events, rest }
}

/** Ask a question about a PR; the answer arrives piece by piece through `onEvent`.
 * EventSource only sends GET, so this reads the POST response's stream itself. */
export async function askQuestion(
  pullRequestId: number,
  question: string,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await globalThis.fetch(`${API_URL}/pull-requests/${pullRequestId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', 'X-API-Key': getApiKey() },
    body: JSON.stringify({ question }),
    signal,
  })
  if (!response.ok || !response.body) {
    const body = (await response.json().catch(() => undefined)) as { error?: { code?: string; message?: string } } | undefined
    throw new ApiError(response.status, body?.error?.code ?? 'error', body?.error?.message ?? `Request failed (${response.status})`)
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    const { events, rest } = parseEvents(buffer)
    buffer = rest
    for (const { event, data } of events) {
      const payload = JSON.parse(data)
      if (event === 'token') onEvent({ event: 'token', text: payload.text })
      else if (event === 'done') onEvent({ event: 'done', data: payload })
      else if (event === 'error') onEvent({ event: 'error', message: payload.message })
    }
  }
}

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { vi } from 'vitest'

/** Render a page at a URL, with a fresh query cache (no retries, so errors show at once). */
export function renderAt(url: string, path: string, element: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path={path} element={element} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

export function renderWithClient(element: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{element}</QueryClientProvider>)
}

type Answer = [number, unknown] | ((request: Request) => Response | Promise<Response>)

/** Replace fetch: `routes` maps "METHOD /path" to [status, body], or to a function building the
 * response (e.g. a stream). Returns the mock to inspect calls. */
export function mockApi(routes: Record<string, Answer>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const request = input instanceof Request ? input : new Request(input, init)
    const url = new URL(request.url)
    const answer = routes[`${request.method} ${url.pathname}`]
    if (!answer) return new Response(JSON.stringify({ error: { code: 'not_found', message: 'Not mocked' } }), { status: 404 })
    if (typeof answer === 'function') return answer(request)
    if (answer[0] === 204) return new Response(null, { status: 204 })
    return new Response(JSON.stringify(answer[1]), { status: answer[0], headers: { 'Content-Type': 'application/json' } })
  })
}

/** A server-sent events response, delivered in two pieces cut mid-event (as a network may). */
export function eventStream(events: [string, unknown][]): Response {
  const bytes = new TextEncoder().encode(events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join(''))
  const middle = Math.floor(bytes.length / 2)
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(bytes.slice(0, middle))
      controller.enqueue(bytes.slice(middle))
      controller.close()
    },
  })
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

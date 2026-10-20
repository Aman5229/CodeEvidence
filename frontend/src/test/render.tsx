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

/** Replace fetch: `routes` maps "METHOD /path" to [status, body]. Returns the mock to inspect calls. */
export function mockApi(routes: Record<string, [number, unknown]>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const request = input as Request
    const url = new URL(request.url)
    const answer = routes[`${request.method} ${url.pathname}`]
    if (!answer) return new Response(JSON.stringify({ error: { code: 'not_found', message: 'Not mocked' } }), { status: 404 })
    return new Response(JSON.stringify(answer[1]), { status: answer[0], headers: { 'Content-Type': 'application/json' } })
  })
}

import createClient, { type Middleware } from 'openapi-fetch'
import { getApiKey } from './apiKey'
import type { components, paths } from './schema'

export type Schemas = components['schemas']

// Set at build time: VITE_API_URL=https://api.example.com npm run build
export const API_URL: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

/** An error answer from the API, in its shared shape: {"error": {"code", "message"}}. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

const sendApiKey: Middleware = {
  onRequest({ request }) {
    request.headers.set('X-API-Key', getApiKey())
    return request
  },
}

// Every call is typed from the OpenAPI spec: paths, parameters and response bodies.
// fetch is looked up on each call (not captured once), so tests can replace it.
export const api = createClient<paths>({ baseUrl: API_URL, fetch: (request) => globalThis.fetch(request) })
api.use(sendApiKey)

/** The data of a response, or an ApiError with the server's message. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data !== undefined) return result.data
  const body = result.error as { error?: { code?: string; message?: string } } | undefined
  throw new ApiError(
    result.response.status,
    body?.error?.code ?? 'error',
    body?.error?.message ?? `Request failed (${result.response.status})`,
  )
}
